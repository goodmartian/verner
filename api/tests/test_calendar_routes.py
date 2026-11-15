import pytest
from shapes import check

from senda_api.contracts import MonthDays

POLY = {"type": "Polygon", "coordinates": [[[20.0, 9.75], [20.1, 9.75], [20.1, 9.85], [20.0, 9.85], [20.0, 9.75]]]}


def test_provinces(client):
    body = client.get("/api/calendar/provinces", params={"area": "XA", "from": "2024-01", "to": "2024-12"}).json()
    check("ProvinceTable", body)
    assert [r["id"] for r in body["rows"]] == ["XA-W"]
    assert client.get("/api/calendar/provinces", params={"area": "XA-W"}).status_code == 422
    for sort in ("ratio", "name"):
        check("ProvinceTable", client.get("/api/calendar/provinces", params={"area": "XA", "sort": sort}).json())


def test_month_detail(client, store):
    body = client.get("/api/calendar/month", params={"area": "XA", "month": "2024-06"}).json()
    check("MonthDetail", body)
    assert body["calendar_month"] == 6 and body["kind"] == "seen" and body["rank"]["of"] == len(body["years"])
    province = client.get("/api/calendar/month", params={"area": "XA-W", "month": "2024-06"}).json()
    check("MonthDetail", province)
    assert province["share_of_country"] is not None
    running = client.get("/api/calendar/month", params={"area": "XA", "month": "2026-11"})
    assert running.status_code == 200 and running.json()["kind"] == "seen"
    check("MonthDetail", running.json())
    ahead = client.get("/api/calendar/month", params={"area": "XA", "month": "2026-12"}).json()
    check("MonthDetail", ahead)
    assert ahead["kind"] == "forecast" and ahead["rank"] is None and ahead["forecast"]["low"] <= ahead["value"]
    assert ahead["years"][-1]["kind"] == "forecast"
    assert client.get("/api/calendar/month", params={"area": "XA", "month": "2027-06"}).status_code == 422


def test_map(client):
    body = client.get("/api/calendar/map", params={"area": "XA", "month": "2024-06"}).json()
    check("CellMap", body)
    assert client.get("/api/calendar/map", params={"area": "XA", "month": "2026-11"}).status_code == 200
    values = [f["properties"]["v"] for f in body["features"]]
    assert values == sorted(values) and all(v > 0 for v in values)


def test_days(client, store):
    body = client.get("/api/calendar/days", params={"area": "XA", "month": "2024-06"}).json()
    MonthDays.model_validate(body)
    assert body["coverage"]["last_day"] == "2026-11-12"
    assert all(d["date"].startswith("2024-06") for d in body["days"])


def test_map_days_and_month_of_a_drawn_area(client):
    drawn = {"area": {"polygon": POLY}, "month": "2024-06"}
    cell_map = client.post("/api/calendar/map", json=drawn)
    assert cell_map.status_code == 200
    check("CellMap", cell_map.json())
    points = [f["properties"]["v"] for f in cell_map.json()["features"]]
    assert points
    # each point is its cell's weighted count rounded, the calendar rounds only the sum
    period = {"area": drawn["area"], "from": "2024-06", "to": "2024-06"}
    row = client.post("/api/calendar", json=period).json()["series"][0]
    assert abs(sum(points) - row["count"]) <= 0.5 * len(points) + 0.5
    days = client.post("/api/calendar/days", json=drawn)
    assert days.status_code == 200 and days.json()["area"] == "drawn"
    MonthDays.model_validate(days.json())
    month = client.post("/api/calendar/month", json=drawn)
    assert month.status_code == 200 and month.json()["area"]["kind"] == "drawn"
    check("MonthDetail", month.json())
    assert month.json()["value"] == row["count"]


@pytest.mark.parametrize("path", ["map", "days", "month"])
def test_a_drawn_area_is_refused_as_by_the_calendar(client, path):
    for area, status, code in (({"bbox": [0, 0, 1, 1]}, 422, "no_land"),
                               ({"bbox": [170, 0, -170, 1]}, 400, "invalid_area")):
        res = client.post(f"/api/calendar/{path}", json={"area": area, "month": "2024-06"})
        assert (res.status_code, res.json()["error"]["code"]) == (status, code)
    bad = client.post(f"/api/calendar/{path}", json={"area": {"polygon": POLY}, "month": "2024-6"})
    assert bad.status_code == 422


def test_export_of_a_drawn_area(client):
    csv = client.post("/api/export", json={"area": {"polygon": POLY}, "from": "2024-01", "to": "2024-12"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0].startswith("latitude,longitude")


def test_export_of_the_months_is_the_calendar(client):
    period = {"area": {"id": "XA"}, "from": "2024-01", "to": "2024-12"}
    csv = client.post("/api/export/months", json=period)
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.headers["content-disposition"] == 'attachment; filename="verner_xa_2024-01_2024-12_months.csv"'
    assert csv.headers["cache-control"] == "no-store" and csv.headers["x-data-version"]
    lines = csv.text.splitlines()
    assert lines[0] == "month,count,median,ratio,level,partial" and len(lines) == 13
    series = client.post("/api/calendar", json=period).json()["series"]
    assert [line.split(",")[:2] for line in lines[1:]] == [[e["month"], str(e["count"])] for e in series]


def test_export_of_the_months_holds_any_period_under_a_tiny_row_limit(client):
    from dataclasses import replace

    # the client is shared by the session: the settings go back by hand (monkeypatch on the app state left it without them)
    state = client.app.state
    before = state.settings
    state.settings = replace(before, max_export_rows=1)
    try:
        assert client.post("/api/export", json={"area": {"id": "XA"}}).status_code == 413
        assert client.post("/api/export/months", json={"area": {"id": "XA"}}).status_code == 200
    finally:
        state.settings = before


def test_days_of_a_month_after_the_data_is_empty_not_an_error(client, store):
    for label in ("2026-12", "2027-02"):
        body = client.get("/api/calendar/days", params={"area": "XA", "month": label}).json()
        MonthDays.model_validate(body)
        assert body["days"] == [] and body["month"] == label


@pytest.mark.parametrize("area", ["XA", "XA-W", "WORLD"])
@pytest.mark.parametrize("month", ["2026-11", "2026-10"])  # the running month and a finished one
def test_the_days_add_up_to_the_month(client, area, month):
    days = client.get("/api/calendar/days", params={"area": area, "month": month}).json()["days"]
    row = client.post("/api/calendar", json={"area": {"id": area}, "from": month, "to": month}).json()["series"][0]
    assert row["count"] is not None and days
    assert abs(sum(d["detections"] for d in days) - row["count"]) <= 0.5 + 1e-6


def test_running_month_is_compared_with_the_same_dates_of_past_years(client, store):
    from senda_api import areas, calendar

    ser = calendar.series_of(store, areas.parse({"id": "XA"}, store))
    usual = ser.to_date["median"]
    month = client.get("/api/calendar/month", params={"area": "XA", "month": "2026-11"}).json()
    assert month["normal"] == usual and month["value"] == ser.partial
    table = client.get("/api/calendar/provinces", params={"area": "XA", "from": "2026-11", "to": "2026-11"}).json()
    west = calendar.series_of(store, areas.parse({"id": "XA-W"}, store))
    row = table["rows"][0]
    assert row["normal"] == float(west.to_date["median"] or 0.0) and row["total"] == west.partial
    # a period of full months keeps the normal of whole months
    full = client.get("/api/calendar/provinces", params={"area": "XA", "from": "2024-01", "to": "2024-12"}).json()["rows"][0]
    assert full["normal"] == float(west.normal.sum())


def test_provinces_say_when_the_period_is_the_whole_archive(client):
    def whole(**params):
        return client.get("/api/calendar/provinces", params={"area": "XA", **params}).json()["whole"]

    assert whole(**{"from": "2003-01", "to": "2026-11"}) is True
    assert whole(**{"from": "2024-01", "to": "2024-12"}) is False
    assert whole(**{"from": "2024-06", "to": "2024-06"}) is False
