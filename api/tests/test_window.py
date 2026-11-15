from dataclasses import replace
from datetime import date

import pytest

from senda_api import areas, daily, weights
from senda_api import window as window_mod
from senda_api.errors import ApiError
from senda_api.months import parse_date

FRACTIONAL = {"bbox": [20.1, 9.1, 21.9, 9.9]}
MAX_KM2 = 3_000_000.0


def window(store, area, start, end):
    return window_mod.compare(store, areas.parse(area, store), parse_date(start, "start"), parse_date(end, "end"), MAX_KM2)


def refused(store, area, start, end):
    with pytest.raises(ApiError) as error:
        window(store, area, start, end)
    return error.value.status, error.value.code


def test_window_matches_same_dates(store):
    body = window(store, FRACTIONAL, "2025-07-01", "2025-07-31")
    idx, w = weights.cell_weights(store, areas.parse(FRACTIONAL, store))
    want = daily.same_dates(store, idx, w, date(2025, 7, 1), date(2025, 7, 31))
    for key, value in want.items():
        assert body[key] == value, key
    assert body["window"] == {"start": "2025-07-01", "end": "2025-07-31"}
    assert body["partial"] is False and body["complete_through"] is None and body["data_version"] == "test-1"


def test_window_over_a_whole_month_equals_calendar_month(client, store):
    cal = client.post("/api/calendar", json={"area": FRACTIONAL}).json()
    month = next(e for e in cal["series"] if e["month"] == "2015-07")
    body = window(store, FRACTIONAL, "2015-07-01", "2015-07-31")
    assert body["count"] == month["count"]
    assert body["median"] == month["median"] and body["ratio"] == month["ratio"] and body["rank"] == month["rank"]


def test_window_too_large_area(store):
    assert refused(store, {"id": "WORLD"}, "2025-07-01", "2025-07-31") == (422, "area_too_large_for_window")
    assert window(store, {"id": "XA"}, "2025-07-01", "2025-07-31")["count"] is not None


def test_window_past_archive_end_clipped(client, store):
    body = window(store, FRACTIONAL, "2026-11-01", "2026-12-31")
    assert body["window"] == {"start": "2026-11-01", "end": "2026-11-12"}
    assert body["partial"] is True and body["complete_through"] == "2026-11-12"
    cur = client.post("/api/calendar", json={"area": FRACTIONAL}).json()["current_month"]
    assert body["count"] == cur["count"] == cur["to_date"]["count"]
    assert body["median"] == cur["to_date"]["median"] and body["rank"] == cur["to_date"]["rank"]


def test_window_without_complete_days_is_null(store):
    body = window(store, FRACTIONAL, "2026-12-01", "2026-12-31")
    assert body["count"] is None and body["ratio"] is None and body["median"] is None and body["rank"] is None
    assert body["partial"] is True and body["complete_through"] == "2026-11-12"


def test_window_before_archive_is_clipped_to_its_start(store):
    assert window(store, FRACTIONAL, "2002-12-20", "2003-01-10")["window"]["start"] == "2003-01-01"


def test_window_fewer_than_three_base_years_is_null_median(store):
    body = window(replace(store, base_years=[2003, 2004]), FRACTIONAL, "2025-07-01", "2025-07-31")
    assert body["count"] is not None and body["median"] is None and body["ratio"] is None and body["rank"] is None


@pytest.mark.parametrize(
    "start,end",
    [("2025-07-31", "2025-07-01"), ("2024-01-01", "2025-06-01"), ("x", "2025-07-01"), ("2025-07-01", "2025-13-01")],
)
def test_window_bad_period(store, start, end):
    assert refused(store, FRACTIONAL, start, end) == (400, "invalid_period")


def test_window_366_days_allowed(store):
    assert window(store, FRACTIONAL, "2023-01-01", "2024-01-01")["count"] is not None


def test_window_bad_area(store):
    assert refused(store, {"bbox": [170, 0, -170, 1]}, "2025-07-01", "2025-07-31") == (400, "invalid_area")
