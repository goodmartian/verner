"""Any date window against the same dates of the baseline years."""

from __future__ import annotations

from datetime import date

from . import daily
from .areas import Area
from .errors import ApiError
from .months import month_start
from .store import Store
from .weights import cell_weights

MAX_WINDOW_DAYS = 366


def compare(store: Store, area: Area, start: date, end: date, max_area_km2: float) -> dict:
    if area.area_km2 > max_area_km2:
        raise ApiError(422, "area_too_large_for_window",
                       f"The area is larger than {max_area_km2:,.0f} km2: choose a smaller area for a date window")
    if start > end:
        raise ApiError(400, "invalid_period", "start must not be after end")
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise ApiError(400, "invalid_period", f"The window is longer than {MAX_WINDOW_DAYS} days")
    last = store.last_complete_date
    s, e = max(start, month_start(store.first_month)), min(end, last)
    partial = e < end
    out = {"count": None, "median": None, "p10": None, "p90": None, "rank": None, "of": None, "ratio": None,
           "years": 0, "window": {"start": s.isoformat(), "end": e.isoformat()}, "partial": partial,
           "complete_through": last.isoformat() if partial else None, "data_version": store.version}
    if s > e:
        return out
    idx, w = cell_weights(store, area)
    out.update(daily.same_dates(store, idx, w, s, e))
    return out
