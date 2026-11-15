"""Limits of what is paid for or heavy: a count per UTC day (Google calls, export rows), the slots of the hotspot export
and its one-time download tickets.

A daily count is kept in Postgres (`daily_counts`) when there is one, so a restart forgets nothing; without it, or while
it is down, in the process. The slots and the tickets live in the process: the server runs one worker, and a ticket
lives five minutes.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from .db import Database
from .errors import ApiError
from .models import DailyCount

log = logging.getLogger("uvicorn.error").getChild("senda.limits")


def today_utc() -> date:
    return datetime.now(UTC).date()


class DailyCounter:
    """A count of one thing per UTC day, against a cap; `take` adds to it only while the cap holds."""

    def __init__(self, name: str, db: Database | None = None, today: Callable[[], date] = today_utc):
        self.name = name
        self._db = db
        self.today = today
        self._kept: dict[date, int] = {}  # the count of the process: alone without the database, else a fallback
        self._lock = threading.Lock()

    def take(self, n: int, cap: int) -> bool:
        """Adds `n` when the day's count stays within `cap` (0: no cap) and says whether it did."""
        if cap > 0 and n > cap:
            return False
        day = self.today()
        if self._db is not None:
            row = insert(DailyCount).values(name=self.name, day=day, value=n)
            row = row.on_conflict_do_update(
                index_elements=[DailyCount.name, DailyCount.day], set_={"value": DailyCount.value + n},
                # one statement: two threads never pass the cap together
                where=(DailyCount.value + n <= cap) if cap > 0 else None)
            try:
                with self._db.session() as s:
                    return s.execute(row.returning(DailyCount.value)).first() is not None
            except (ApiError, SQLAlchemyError) as error:
                log.warning("%s: the database cannot be written (%s); counting in the process", self.name,
                            type(error).__name__)
        with self._lock:
            for old in [d for d in self._kept if d != day]:
                del self._kept[old]
            now = self._kept.get(day, 0)
            if cap > 0 and now + n > cap:
                return False
            self._kept[day] = now + n
            return True


def seconds_to_midnight(now: Callable[[], float] = time.time) -> int:
    """Seconds until the next UTC day, at least 1."""
    return max(1, 86_400 - int(now()) % 86_400)


class Slots:
    """At most `size` hotspot exports at once on the server; one more waits a while for its turn."""

    def __init__(self, size: int, wait_s: float):
        self.wait_s = wait_s
        self._free = threading.BoundedSemaphore(size)

    def take(self) -> Callable[[], None] | None:
        """A release that may be called any number of times, or None when no slot came free in time."""
        if not self._free.acquire(timeout=self.wait_s):
            return None
        done = threading.Lock()

        def release() -> None:
            if done.acquire(blocking=False):
                self._free.release()

        return release

    def free(self) -> int:
        return self._free._value  # free slots now: the ticket refuses at once when there are none


class SlotResponse(StreamingResponse):
    """A stream that gives its slot back when it ends in any way: read to the end, failed, or the client gone.

    The release is in `__call__`, around the whole sending: when the client goes away the server cancels this call or
    a send fails, and either way the `finally` runs. The generator's own `finally` releases as well, for a stream
    that is closed without being sent."""

    def __init__(self, content: Iterator[bytes], release: Callable[[], None], **kwargs: Any):
        super().__init__(_releasing(content, release), **kwargs)
        self._release = release

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._release()


def _releasing(content: Iterator[bytes], release: Callable[[], None]) -> Iterator[bytes]:
    try:
        yield from content
    finally:
        release()


@dataclass(frozen=True)
class Ticket:
    who: str
    expires: float
    order: dict  # what to export: the area as sent, and the period


class Tickets:
    """One-time download tickets: unguessable, five minutes, for the address that ordered them."""

    LIFE_S = 300

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self._open: dict[str, Ticket] = {}
        self._lock = threading.Lock()

    def issue(self, who: str, order: dict) -> str:
        token = secrets.token_urlsafe(24)
        now = self.clock()
        with self._lock:
            for old in [t for t, ticket in self._open.items() if ticket.expires <= now]:
                del self._open[old]
            self._open[token] = Ticket(who, now + self.LIFE_S, order)
        return token

    def _order(self, token: str, who: str) -> dict | None:
        """The order of a ticket that is open and this address's; called with the lock held."""
        ticket = self._open.get(token)
        if ticket is None or ticket.who != who or ticket.expires <= self.clock():
            return None
        return ticket.order

    def look(self, token: str, who: str) -> dict | None:
        """The order of a ticket that is open and this address's, without using it."""
        with self._lock:
            return self._order(token, who)

    def use(self, token: str, who: str) -> dict | None:
        """The order of the ticket, which is then gone; None when it is not open or not this address's."""
        with self._lock:
            order = self._order(token, who)
            if order is not None:
                del self._open[token]
            return order
