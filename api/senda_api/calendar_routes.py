"""`/api/calendar/*`: one catalog area, answered from the same series as `calendar.build`.

The map and the days of a month are kept per area and month for the data version (`Store.lru`): for the world each
takes about a second to make, the same for every visitor. They are kept as the JSON that is sent, so no request can
change what another gets, and a world map is a few MB that way (about 35 MB as Python objects). After a start and
after a new data version `warm_later` makes what the first visitor of the world asks for, in one background thread.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response

from . import areas, calendar, summary
from .base import DEFAULT_AREA, store_of
from .contracts import AreaMonthRequest, CellMap, MonthDays, MonthDetail, ProvinceTable, ok
from .errors import ApiError, SafeJSONResponse
from .store import Store
from .world import world_of

log = logging.getLogger("uvicorn.error").getChild("senda.warm")
router = APIRouter(prefix="/api/calendar", tags=["api"])
MAPS_KEPT = 16  # a world map is about 5 MB of JSON: 16 of them stay under 100 MB, a country's are far smaller
DAYS_KEPT = 128  # a month of days is a few KB

MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
AreaQuery = Annotated[str, Query(min_length=1, max_length=64)]
MonthQuery = Annotated[str, Query(pattern=MONTH)]
OptionalMonth = Annotated[str | None, Query(alias="from", pattern=MONTH)]
OptionalEnd = Annotated[str | None, Query(alias="to", pattern=MONTH)]


def _area(request: Request, rid: str):
    store = store_of(request)
    area = areas.parse({"id": rid}, store)
    return store, area, calendar.series_of(store, area)


@router.get("/provinces", responses=ok(ProvinceTable))
def provinces(request: Request, from_: OptionalMonth = None, to: OptionalEnd = None,
              sort: Literal["total", "ratio", "name"] = "total", area: AreaQuery = DEFAULT_AREA):
    store, chosen, ser = _area(request, area)
    if summary.kind_of(store, chosen) != "country":
        raise ApiError(422, "validation_error", "area: provinces are listed for a country")
    first, last = summary.resolve_period(ser, from_, to)
    return summary.provinces(store, chosen, ser, first, last, sort)


@router.get("/month", responses=ok(MonthDetail))
def month(request: Request, month: MonthQuery, area: AreaQuery = DEFAULT_AREA):
    store, chosen, ser = _area(request, area)
    return summary.month(store, chosen, ser, month)


def _kept(store: Store, name: str, key: tuple, make: Callable[[], dict], limit: int) -> Response:
    """The JSON of an answer, made once per data version and key; an error is raised each time, never kept."""
    body = store.lru(name, key, lambda: SafeJSONResponse(make()).body, limit)
    return Response(body, media_type="application/json")


def _map(store: Store, rid: str, month: str) -> Response:
    chosen = areas.parse({"id": rid}, store)
    ser = calendar.series_of(store, chosen)
    return _kept(store, "calendar_map", (chosen.id, month), lambda: summary.cell_map(store, chosen, ser, month),
                 MAPS_KEPT)


def _days(store: Store, rid: str, month: str) -> Response:
    chosen = areas.parse({"id": rid}, store)
    return _kept(store, "calendar_days", (chosen.id, month), lambda: summary.days(store, chosen, month), DAYS_KEPT)


@router.get("/map", responses=ok(CellMap))
def cell_map(request: Request, month: MonthQuery, area: AreaQuery = DEFAULT_AREA):
    return _map(store_of(request), area, month)


@router.get("/days", responses=ok(MonthDays))
def days(request: Request, month: MonthQuery, area: AreaQuery = DEFAULT_AREA):
    return _days(store_of(request), area, month)


# A drawn area has no stable key, so these are made on each ask and never kept.
def _drawn(request: Request, body: AreaMonthRequest):
    store = store_of(request)
    return store, areas.parse(body.area.as_dict(), store)


@router.post("/month", responses=ok(MonthDetail))
def post_month(request: Request, body: AreaMonthRequest):
    store, chosen = _drawn(request, body)
    return summary.month(store, chosen, calendar.series_of(store, chosen), body.month)


@router.post("/map", responses=ok(CellMap))
def post_cell_map(request: Request, body: AreaMonthRequest):
    store, chosen = _drawn(request, body)
    return summary.cell_map(store, chosen, calendar.series_of(store, chosen), body.month)


@router.post("/days", responses=ok(MonthDays))
def post_days(request: Request, body: AreaMonthRequest):
    store, chosen = _drawn(request, body)
    return summary.days(store, chosen, body.month)


def warm(store: Store) -> None:
    """What the first visitor of the world waits for: the countries of the world tab, and the map and the days of the
    world in the running month. A failure is one line in the log; the answers are then made on the first ask."""
    started = time.monotonic()
    month = f"{2000 + store.cur_month // 12}-{store.cur_month % 12 + 1:02d}"
    steps = (("countries", lambda: world_of(store).countries(None, None, None)),
             ("world map", lambda: _map(store, areas.WORLD_ID, month)),
             ("world days", lambda: _days(store, areas.WORLD_ID, month)))
    for name, step in steps:
        try:
            step()
        except Exception as err:  # noqa: BLE001 - a warm-up that fails changes nothing but the wait of the first visitor
            log.warning("warm-up of %s for %s failed: %s: %s", name, store.version, type(err).__name__, err)
    log.info("warm-up of %s done in %.1f s", store.version, time.monotonic() - started)


def warm_later(store: Store) -> threading.Thread:
    """`warm` in one background thread: the start and the answers do not wait for it."""
    thread = threading.Thread(target=warm, args=(store,), name="warm", daemon=True)
    thread.start()
    return thread
