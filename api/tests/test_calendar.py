import json

import fixture
import numpy as np
import oracle
import pytest

from senda_api import areas, calendar, weights

TWO_CELLS = {"bbox": [20.0, 9.75, 20.5, 10.0]}
FRACTIONAL = {"bbox": [20.1, 9.1, 21.9, 9.9]}
NEVER = {"bbox": [22.25, 9.0, 22.5, 9.25]}


def cell(r, c):
    return (fixture.ROW0 + r) * 1440 + fixture.COL0 + c


def post(client, area, **kw):
    res = client.post("/api/calendar", json={"area": area, **kw})
    assert res.status_code == 200, res.text
    return res.json()


def weights_of(store, selector):
    idx, w = weights.cell_weights(store, areas.parse(selector, store))
    return {int(store.cells.cell_id[i]): float(x) for i, x in zip(idx, w, strict=True)}


@pytest.fixture(scope="module")
def daily(data_dir):
    return oracle.load_daily(data_dir)


def seen(body):
    return [e for e in body["series"] if e["kind"] != "forecast"]


def by_month(body):
    return {e["month"]: e for e in seen(body)}


def test_response_shape(client):
    body = post(client, TWO_CELLS)
    assert list(body) == ["area", "first_month", "last_complete_date", "series", "normals", "current_month", "yearly",
                          "season", "quality", "forecast", "trend", "check", "presets", "data_version"]
    assert set(body["area"]) == {"id", "name", "bbox", "area_km2", "approximate", "geometry"}
    assert body["area"]["geometry"]["type"] == "Polygon"
    el = body["series"][0]
    assert set(el) == {"month", "count", "raw", "frp_mw", "median", "mean", "ratio", "level", "rank", "of", "partial",
                       "complete_through", "source", "converted", "sensors", "lo", "hi", "kind", "forecast"}
    assert set(el["raw"]) == {"modis_terra", "modis_aqua", "viirs_snpp", "viirs_noaa20"}
    assert body["series"][0]["month"] == "2003-01" and body["series"][-1]["month"] == "2027-05"
    assert [e["kind"] for e in body["series"][-7:]] == ["running"] + ["forecast"] * 6
    assert body["data_version"] == "test-1"
    assert set(body["normals"][0]) == {"month", "median", "mean", "p10", "p90", "years"}


def test_series_matches_manual_sum(client, store, daily):
    body = post(client, TWO_CELLS)
    truth = oracle.month_totals(daily, {cell(0, 0): 1.0, cell(0, 1): 1.0})
    for e in seen(body):
        y, m = int(e["month"][:4]), int(e["month"][5:])
        assert e["count"] == oracle.rint(truth.get((y, m), 0.0)), e["month"]


def test_raw_comes_from_monthly_parquet(client, data_dir):
    import polars as pl

    body = post(client, TWO_CELLS)
    monthly = pl.read_parquet(data_dir / "monthly.parquet").filter(pl.col("cell_id").is_in([cell(0, 0), cell(0, 1)]))
    for label, month in (("2005-07", fixture.mi(2005, 7)), ("2015-07", fixture.mi(2015, 7)), ("2026-11", fixture.mi(2026, 11))):
        part = monthly.filter(pl.col("month") == month)
        for sensor in ("modis_aqua", "viirs_snpp", "viirs_noaa20"):
            want = part.filter(pl.col("sensor") == sensor).select((pl.col("n_day") + pl.col("n_night")).sum()).item() or 0
            assert by_month(body)[label]["raw"][sensor] == want, (label, sensor)


def test_fractional_weights_match_manual_sum(client, store, daily):
    body = post(client, FRACTIONAL)
    truth = oracle.month_totals(daily, weights_of(store, FRACTIONAL))
    for e in seen(body):
        y, m = int(e["month"][:4]), int(e["month"][5:])
        assert e["count"] == oracle.rint(truth.get((y, m), 0.0)), e["month"]


@pytest.mark.parametrize(
    "ratio,level", [(0.79, 0), (0.8, 1), (1.24, 1), (1.25, 2), (1.99, 2), (2.0, 3), (3.99, 3), (4.0, 4), (50, 4)]
)
def test_levels(ratio, level):
    assert calendar.level_of(ratio) == level


def test_zero_median_rules():
    assert calendar.ratio_level(0, 0) == (1.0, 1)
    ratio, level = calendar.ratio_level(5, 0)
    assert ratio == 5.0 and level == 4
    assert calendar.ratio_level(0, 10) == (0.0, 0)
    assert calendar.ratio_level(10, 10) == (1.0, 1)
    assert calendar.ratio_level(7, None) == (None, None)


def test_never_burned_area_no_nan(client):
    res = client.post("/api/calendar", json={"area": NEVER})
    assert res.status_code == 200
    assert "NaN" not in res.text and "Infinity" not in res.text
    json.loads(res.text, parse_constant=lambda c: pytest.fail(c))
    body = res.json()
    assert all(e["count"] == 0 for e in body["series"])
    assert all(e["ratio"] == 1.0 and e["level"] == 1 for e in body["series"] if e["median"] == 0)
    assert body["quality"]["expected_error"] is None and body["quality"]["unharmonized_share"] == 0.0
    assert all(e["lo"] is None and e["hi"] is None for e in body["series"])


def test_tiny_area_is_approximate_with_zero_calendar(client):
    body = post(client, {"bbox": [22.26, 9.01, 22.27, 9.02]})
    assert body["area"]["approximate"] is True
    assert all(e["count"] == 0 for e in body["series"])


def test_partial_year_not_in_baseline(client):
    body = post(client, TWO_CELLS)
    normals = {n["month"]: n for n in body["normals"]}
    assert all(n["years"] == 23 for n in normals.values())  # 2003..2025, not 2026 although Jan-Oct are present


def test_incomplete_month_stays_in_normals_flagged(client):
    body = post(client, TWO_CELLS)
    el = by_month(body)["2008-03"]
    assert el["partial"] is True and el["complete_through"] is None and el["count"] is not None
    assert {n["month"]: n for n in body["normals"]}[3]["years"] == 23
    y2008 = next(y for y in body["yearly"] if y["year"] == 2008)
    assert y2008["complete"] is True and y2008["gaps"] is True


def test_months_after_archive_end_are_null(client):
    body = post(client, TWO_CELLS, to="2027-02")
    tail = body["series"][-3:]
    assert [e["month"] for e in tail] == ["2026-12", "2027-01", "2027-02"]
    for e in tail:
        assert e["count"] is None and e["level"] is None and e["ratio"] is None and e["rank"] is None
        assert e["source"] == "none" and e["partial"] is False and e["complete_through"] is None
        assert e["sensors"] == [] and e["converted"] is False
    assert [y["year"] for y in body["yearly"]][-1] == 2026
    assert body["current_month"]["month"] == "2026-11"


def test_rounding_yearly_is_sum_of_rounded_months(client):
    body = post(client, FRACTIONAL)
    months = by_month(body)
    for y in body["yearly"]:
        total = sum(months[f"{y['year']}-{m:02d}"]["count"] for m in range(1, 13) if f"{y['year']}-{m:02d}" in months)
        assert y["count"] == total


def test_yearly_flags(client):
    yearly = {y["year"]: y for y in post(client, TWO_CELLS)["yearly"]}
    assert yearly[2025]["complete"] is True and yearly[2025]["gaps"] is False
    assert yearly[2026]["complete"] is False
    assert yearly[2003]["complete"] is True


def test_yearly_converted_needs_every_month_of_the_year(client, store):
    body = post(client, TWO_CELLS)
    months = by_month(body)
    for y in body["yearly"]:  # the flag of a year is the flag of its months
        flags = [months[f"{y['year']}-{m:02d}"]["converted"] for m in range(1, 13) if f"{y['year']}-{m:02d}" in months]
        assert y["converted"] == all(flags)
    converted = np.zeros(store.cur_month + 1, dtype=bool)
    converted[(2005 - 2000) * 12:(2007 - 2000) * 12] = True  # 2005 and 2006
    converted[(2007 - 2000) * 12] = True  # one month of 2007 does not make the year
    yearly = {y["year"]: y["converted"] for y in calendar._yearly(store, np.ones(store.cur_month + 1), converted)}
    assert yearly[2005] is True and yearly[2006] is True and yearly[2007] is False and yearly[2008] is False


def test_trend_is_the_slope_of_the_last_ten_full_years(client, store):
    body = post(client, TWO_CELLS)
    ser = calendar.series_of(store, areas.parse({"bbox": TWO_CELLS["bbox"]}, store))
    last = ser.last_full_year
    percent = ser.trend_percent()
    expected = None if percent is None else {"first_year": last - 9, "last_year": last, "percent_per_year": percent}
    assert body["trend"] == expected
    assert post(client, NEVER)["trend"] is None  # a quiet area has no trend


def test_converted_and_band(client):
    body = post(client, {"bbox": [20.0, 9.75, 20.25, 10.0]})  # exactly cell A
    months = by_month(body)
    old = months["2005-07"]
    assert old["converted"] is True and old["count"] == 60
    assert old["lo"] < old["count"] < old["hi"]
    err = body["quality"]["expected_error"]
    assert old["lo"] == oracle.rint(60 * (1 - err)) and old["hi"] == oracle.rint(60 * (1 + err))
    new = months["2015-07"]
    assert new["converted"] is False and new["lo"] is None and new["hi"] is None and new["count"] == 7
    assert months["2022-03"]["converted"] is True and months["2022-03"]["count"] == 30


def test_sensors_listed_for_mixed_month(client):
    months = by_month(post(client, TWO_CELLS))
    assert months["2026-11"]["sensors"] == ["viirs_snpp", "viirs_noaa20"]
    assert months["2005-07"]["sensors"] == ["modis_aqua"]
    assert months["2015-07"]["sensors"] == ["viirs_snpp"]
    assert months["2022-03"]["sensors"] == ["viirs_snpp", "modis_aqua"]
    assert months["2026-11"]["source"] == "nrt" and months["2015-07"]["source"] == "sp"


def test_current_month_is_partial_and_to_date_matches_month(client):
    body = post(client, TWO_CELLS, to="2026-06")
    cur = body["current_month"]
    assert cur["month"] == "2026-11" and cur["partial"] is True and cur["complete_through"] == "2026-11-12"
    td = cur["to_date"]
    assert td["through"] == "2026-11-12" and td["count"] == cur["count"]  # the month holds only days 1..12
    assert set(td) == {"through", "count", "median", "ratio", "rank", "of"} and td["of"] == 24


def test_to_date_same_dates(client, store, daily):
    from datetime import date

    w = weights_of(store, TWO_CELLS)
    body = post(client, TWO_CELLS)
    values = sorted(oracle.rint(oracle.window_total(daily, w, date(y, 11, 1), date(y, 11, 12))) for y in range(2003, 2026))
    import numpy as np

    td = body["current_month"]["to_date"]
    assert td["median"] == oracle.rint(np.median(values))
    full_median = {n["month"]: n for n in body["normals"]}[11]["median"]
    assert td["median"] != full_median or full_median == 0  # compares days 1..12, not the whole month


def test_series_ratio_rank(client):
    body = post(client, FRACTIONAL)
    normals = {n["month"]: n for n in body["normals"]}
    for e in body["series"]:
        if e["count"] is None:
            continue
        median = normals[int(e["month"][5:])]["median"]
        assert e["median"] == median
        assert e["ratio"] == (1.0 if e["count"] == 0 and median == 0 else round(e["count"] / max(median, 1), 2))
        assert 1 <= e["rank"] <= e["of"]
        assert e["of"] in (23, 24)


def test_period_clipping(client):
    body = post(client, TWO_CELLS, **{"from": "2010-01", "to": "2010-12"})
    assert body["series"][0]["month"] == "2010-01" and len(body["series"]) == 12
    assert body["normals"][0]["years"] == 23 and body["season"] is not None  # norms always from the whole archive
    early = post(client, TWO_CELLS, **{"from": "1999-01", "to": "2003-02"})
    assert [e["month"] for e in early["series"]] == ["2003-01", "2003-02"]


@pytest.mark.parametrize("kw,status,code", [({"from": "2010/01"}, 422, "validation_error"),
                                            ({"to": "x"}, 422, "validation_error"),
                                            ({"to": "2010-13"}, 422, "validation_error"),
                                            ({"from": "2011-01", "to": "2010-01"}, 400, "invalid_period")])
def test_bad_period(client, kw, status, code):
    res = client.post("/api/calendar", json={"area": TWO_CELLS, **kw})
    assert res.status_code == status and res.json()["error"]["code"] == code


def test_period_beyond_the_forecast_is_cut_or_refused(client):
    whole = post(client, TWO_CELLS)
    end = whole["series"][-1]["month"]
    cut = post(client, TWO_CELLS, **{"from": "2024-01", "to": "2031-01"})
    assert cut["series"][-1]["month"] == end
    res = client.post("/api/calendar", json={"area": TWO_CELLS, "from": "2030-01", "to": "2031-01"})
    assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_period" and end in res.json()["error"]["message"]


def test_every_form_of_the_selector_is_accepted(client):
    ring = [[20.0, 9.75], [20.1, 9.75], [20.1, 9.85], [20.0, 9.85], [20.0, 9.75]]
    forms = [{"id": "XA"}, {"bbox": [20.0, 9.0, 21.0, 10.0]}, {"polygon": {"type": "Polygon", "coordinates": [ring]}},
             {"polygon": {"type": "MultiPolygon", "coordinates": [[ring]]}},
             {"point": {"lat": 9.5, "lon": 20.5}, "radius_km": 20}]
    for form in forms:
        assert client.post("/api/calendar", json={"area": form}).status_code == 200, form
    for bad in ({"id": "XA", "bbox": [0, 0, 1, 1]}, {"point": {"lat": 1, "lon": 1}}, {"radius_km": 5}):
        assert client.post("/api/calendar", json={"area": bad}).status_code == 422, bad


def test_bad_area_errors_have_shape(client):
    for payload, status, code in (
        ({"area": {"bbox": [170, 0, -170, 1]}}, 400, "invalid_area"),
        ({"area": {"bbox": [0, 0, 1, 1]}}, 422, "no_land"),
        ({"area": {"id": "ZZ"}}, 404, "not_found"),
        ({}, 422, "validation_error"),
        ({"area": "x"}, 422, "validation_error"),
    ):
        res = client.post("/api/calendar", json=payload)
        assert (res.status_code, res.json()["error"]["code"]) == (status, code), payload
        assert set(res.json()) == {"error"}


def test_world_and_region(client):
    world = post(client, {"id": "WORLD"})
    assert world["area"]["id"] == "WORLD" and world["area"]["name"] == "World"
    region = post(client, {"id": "XA-W"})
    assert region["area"]["id"] == "XA-W" and region["area"]["name"] == "West Xland"


def test_no_nan_anywhere(client):
    for area in (TWO_CELLS, FRACTIONAL, NEVER, {"id": "WORLD"}, {"point": {"lat": 9.5, "lon": 21}, "radius_km": 30}):
        text = client.post("/api/calendar", json={"area": area}).text
        assert "NaN" not in text and "Infinity" not in text


def test_frp_follows_same_k(client):
    months = by_month(post(client, {"bbox": [20.0, 9.75, 20.25, 10.0]}))
    # cell A, 2005-07: 10 day fires x 12.5 MW x k 4 plus 5 night fires x 8 MW x k 4
    assert months["2005-07"]["frp_mw"] == 10 * 12.5 * 4 + 5 * 8.0 * 4


def test_noaa20_bridge_month_is_not_converted(client):
    months = by_month(post(client, {"id": "XA"}))
    assert months["2026-11"]["count"] > 0 and months["2026-11"]["converted"] is False
    assert months["2026-11"]["lo"] is None and months["2026-11"]["hi"] is None


def test_board_has_forecast_check_and_presets(client):
    body = post(client, TWO_CELLS)
    assert body["forecast"]["first_month"] == "2026-12" and body["forecast"]["last_month"] == "2027-05"
    assert body["forecast"]["accuracy"] is not None
    ahead = [e for e in body["series"] if e["kind"] == "forecast"]
    assert len(ahead) == 6 and all(e["count"] is None and e["forecast"]["low"] <= e["forecast"]["high"] for e in ahead)
    # three full years, then the forecast; no fixed season, which is the season of no area in particular
    assert [p["kind"] for p in body["presets"]] == ["year", "year", "year", "forecast"]
    assert body["first_month"] == "2003-01"
    assert 0 <= body["quality"]["unharmonized_share"] <= 1
    check = body["check"]
    assert check is None or {"climatology", "poisson", "boosting"} <= set(check)


def test_explicit_period_stops_where_asked(client):
    body = post(client, TWO_CELLS, to="2026-11")
    assert body["series"][-1]["month"] == "2026-11" and body["series"][-1]["kind"] == "running"
    body = post(client, TWO_CELLS, **{"from": "2026-10", "to": "2027-02"})
    assert [e["kind"] for e in body["series"]] == ["seen", "running", "forecast", "forecast", "forecast"]


def test_no_forecast_for_a_never_burned_area(client):
    body = post(client, NEVER)
    assert body["forecast"] is None and body["check"] is None
    assert all(e["kind"] != "forecast" for e in body["series"])


def test_schema_describes_the_board_and_meta(client):
    spec = client.get("/api/openapi.json").json()
    ref = spec["paths"]["/api/calendar"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/Calendar")
    ref = spec["paths"]["/api/meta"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/Meta")
