"""The CSV of hotspots of an area, and of its months.

The hotspots go in two steps, so the browser saves a file of any size straight to disk and a refusal comes as JSON:
`POST /api/export/ticket` checks the area, the period, the size and the limits and answers a one-time link;
`GET /api/export/file/{ticket}` streams the file. `POST /api/export` streams it at once, with the same limits.

Limits of a hotspot export: `max_export_rows` rows a file (413), `export_per_hour` exports an address (429
`export_quota`), `export_rows_per_day` rows on the whole server a UTC day (429 `export_day_cap`), and
`export_slots` streams at once (429 `export_busy`). `POST /api/export/months` is small and has none of them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from . import areas, calendar, export
from .base import store_of
from .chat import files
from .chat.guard import address_of
from .contracts import (
    CSV_RESPONSE,
    AreaPeriodRequest,
)
from .errors import ApiError, retry_after
from .limits import SlotResponse, seconds_to_midnight
from .months import month_label

router = APIRouter(prefix="/api", tags=["api"])

CSV = "text/csv; charset=utf-8"
TICKET = r"^[A-Za-z0-9_-]{20,64}$"
KIND = "export"  # the kind of event in the guard's per-address count


class ExportTicket(BaseModel):
    url: str  # where the browser gets the file: /api/export/file/<ticket>, once, within five minutes
    rows: int
    name: str


def _order(request: Request, area: dict, from_: str | None, to: str | None):
    store = store_of(request)
    found = areas.parse(area, store)
    first, last = calendar.resolve_period(store, from_, to)
    return store, found, month_label(first), month_label(last), export.file_name(store, found, first, last)


def _counted(request: Request, body: AreaPeriodRequest):
    """The address, the order and its rows. An address over its hour is refused before the rows are counted: the count
    itself takes seconds for the world."""
    state = request.app.state
    who = address_of(request)
    state.chat_guard.limit(who, KIND, state.settings.export_per_hour, "export_quota", "Too many exports from this address")
    store, area, start, end, name = _order(request, body.area.as_dict(), body.from_, body.to)
    # past the limit the count stops: an order of too many rows is refused in seconds, not minutes
    rows = export.count_rows(store, area, start, end, stop_over=state.settings.max_export_rows)
    return who, store, area, start, end, name, rows


def _busy(wait_s: float) -> ApiError:
    return ApiError(429, "export_busy", "Other exports are being made; try again shortly", retry_after(wait_s))


def _admit(request: Request, who: str, rows: int) -> None:
    """The size of one file and the rows of the server's day; counts the export toward the address's hour."""
    state = request.app.state
    settings = state.settings
    limit = settings.max_export_rows
    if rows > limit:
        # counting the rows of a period too large is work as well: the order counts toward the address's hour
        state.chat_guard.count(who, KIND)
        # the count stopped once past the limit: `rows` is how many at least, `more` says so
        raise ApiError(413, "payload_too_large", f"The export would have at least {rows} rows and the limit is {limit}",
                       details={"rows": rows, "limit": limit, "more": True})
    if not state.export_rows.take(rows, settings.export_rows_per_day):
        raise ApiError(429, "export_day_cap", "The server has given all the rows it can today",
                       retry_after(seconds_to_midnight()))
    state.chat_guard.count(who, KIND)


def _stream(release, store, area, start: str, end: str, name: str) -> StreamingResponse:
    try:
        return SlotResponse(export.hotspots(store, area, start, end), release, media_type=CSV,
                            headers=_headers(name, store.version))
    except BaseException:
        release()
        raise


@router.post("/export/ticket", response_model=ExportTicket)
def post_export_ticket(request: Request, body: AreaPeriodRequest):
    """Orders a hotspot export; the answer is a link the browser opens to save the file."""
    who, _, _, _, _, name, rows = _counted(request, body)
    slots = request.app.state.export_slots
    if slots.free() == 0:  # the browser shows a refusal of the file step as a page: say it here, while it can be read
        raise _busy(slots.wait_s)
    _admit(request, who, rows)
    token = request.app.state.export_tickets.issue(who, {"area": body.area.as_dict(), "from": body.from_,
                                                         "to": body.to})
    return {"url": f"/api/export/file/{token}", "rows": rows, "name": name}


@router.get("/export/file/{ticket}", response_class=StreamingResponse, responses=CSV_RESPONSE)
def get_export_file(request: Request, ticket: Annotated[str, Path(pattern=TICKET)]):
    """The file of a ticket: once, within five minutes of the order, for the address that ordered it."""
    who = address_of(request)
    tickets = request.app.state.export_tickets
    order = tickets.look(ticket, who)
    if order is None:
        raise ApiError(404, "not_found", "No such export, or it was already taken")
    store, area, start, end, name = _order(request, order["area"], order["from"], order["to"])
    slots = request.app.state.export_slots
    release = slots.take()  # waits a while for its turn; the ticket stays good when none comes
    if release is None:
        raise _busy(slots.wait_s)
    if tickets.use(ticket, who) is None:  # taken by another request meanwhile
        release()
        raise ApiError(404, "not_found", "No such export, or it was already taken")
    return _stream(release, store, area, start, end, name)


@router.post("/export", response_class=StreamingResponse, responses=CSV_RESPONSE)
def post_export(request: Request, body: AreaPeriodRequest):
    """The hotspots at once, for scripts; the same limits as the ticket and the file."""
    who, store, area, start, end, name, rows = _counted(request, body)
    slots = request.app.state.export_slots
    release = slots.take()
    if release is None:
        raise _busy(slots.wait_s)
    try:
        _admit(request, who, rows)
    except BaseException:
        release()
        raise
    return _stream(release, store, area, start, end, name)


@router.post("/export/months", response_class=Response,
             responses={200: {**CSV_RESPONSE[200], "description": "Months as CSV"}})
def post_export_months(request: Request, body: AreaPeriodRequest):
    """The months of the period as the calendar shows them: one row a month, small for any area and period."""
    store = store_of(request)
    area = areas.parse(body.area.as_dict(), store)
    first, last = calendar.resolve_period(store, body.from_, body.to)
    name, text, _, _ = files.monthly(store, area, first, last)
    return Response(text, media_type=CSV, headers=_headers(name, store.version))


def _headers(name: str, version: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{name}"', "X-Data-Version": version,
            "Cache-Control": "no-store"}
