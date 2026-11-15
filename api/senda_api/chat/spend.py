"""What the model calls of the chat cost today, and the daily cap on it.

The sum of a day is kept in Postgres (`chat_spend`), so a restart forgets nothing; the process keeps a copy that each
addition brings up to date. Without the database, or while it is down, the copy alone counts. Every model call is
counted, a failed question's calls too.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from ..db import Database
from ..errors import ApiError
from ..limits import today_utc
from ..models import ChatSpend
from .llm import Model, ModelRequest, Turn, Usage

log = logging.getLogger("uvicorn.error").getChild("senda.chat")

# dollars per million tokens: input, output, cache read, cache write (5-minute entries)
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
# a model that is not in the table is counted at the dearest row: it can only stop the chat early, never overspend
DEAREST = max(PRICES.values(), key=lambda row: row[1])


def cost_usd(model: str, usage: Usage) -> float:
    price_in, price_out, price_read, price_write = PRICES.get(model, DEAREST)
    return (usage.input_tokens * price_in + usage.output_tokens * price_out
            + usage.cache_read_input_tokens * price_read + usage.cache_creation_input_tokens * price_write) / 1e6


class DailySpend:
    """The dollars spent on the model in the current UTC day, against a cap; a cap of 0 is no cap."""

    def __init__(self, cap_usd: float, today: Callable[[], date] = today_utc, db: Database | None = None):
        self.cap_usd = cap_usd
        self.today = today
        self._db = db
        self._day = today()
        self._spent = 0.0
        self._read: date | None = None  # the day whose sum was read from the database
        self._lock = threading.Lock()

    def _roll(self) -> None:
        day = self.today()
        if day != self._day:
            self._day, self._spent = day, 0.0
        if self._db is not None and self._read != day:
            try:
                with self._db.session() as s:
                    found = s.get(ChatSpend, day)
            except (ApiError, SQLAlchemyError) as error:
                log.warning("chat spend: the database cannot be read (%s); counting in the process", type(error).__name__)
                return
            # what was counted here while the database was down is kept, if it is more
            self._spent = max(self._spent, found.usd if found else 0.0)
            self._read = day

    def _store(self, usd: float) -> None:
        """Adds to the day's row in one statement, so two threads never overwrite each other."""
        if self._db is None:
            return
        row = insert(ChatSpend).values(day=self._day, usd=usd)
        row = row.on_conflict_do_update(index_elements=[ChatSpend.day], set_={"usd": ChatSpend.usd + row.excluded.usd})
        try:
            with self._db.session() as s:
                total = s.execute(row.returning(ChatSpend.usd)).scalar_one()
        except (ApiError, SQLAlchemyError) as error:
            log.warning("chat spend: the database cannot be written (%s); counting in the process", type(error).__name__)
            return
        self._spent = max(self._spent, total)

    def spent(self) -> float:
        with self._lock:
            self._roll()
            return self._spent

    def reached(self) -> bool:
        return self.cap_usd > 0 and self.spent() >= self.cap_usd

    def add(self, usd: float) -> None:
        with self._lock:
            self._roll()
            before = self._spent
            self._spent += usd
            self._store(usd)
            if self.cap_usd > 0 and before < self.cap_usd <= self._spent:
                log.warning("chat daily cap reached: %.2f of %.2f USD on %s; the chat answers 429 until the next "
                            "UTC day", self._spent, self.cap_usd, self._day.isoformat())


class Metered:
    """A model whose every call is added to the day's spend."""

    def __init__(self, model: Model, spend: DailySpend):
        self._model = model
        self._spend = spend

    def complete(self, request: ModelRequest) -> Turn:
        turn = self._model.complete(request)
        self._spend.add(cost_usd(request.model, turn.usage))
        return turn
