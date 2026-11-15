from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from shapes import check

from senda_api import fires
from senda_api.contracts import MonthDays

T0 = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)


def _frame(rng) -> pl.DataFrame:
    rows = []
    # a fire in the west province, seen in two passes, and one in the east of the country
    for centre, passes in (((20.5, 9.5), (T0, T0 + timedelta(hours=11))), ((21.8, 9.2), (T0 + timedelta(hours=1), T0 + timedelta(hours=12)))):
        for when in passes:
            for _ in range(15):
                lon = centre[0] + rng.uniform(-0.02, 0.02)
                lat = centre[1] + rng.uniform(-0.02, 0.02)
                rows.append((lat, lon, when + timedelta(minutes=int(rng.integers(0, 5))), when.date(), 30.0))
    rows.append((9.9, 20.1, T0, T0.date(), 5.0))  # a lone detection: not a fire
    return pl.DataFrame(rows, schema=["lat", "lon", "acq_utc", "local_date", "frp_mw"], orient="row").with_columns(
        pl.col("acq_utc").dt.cast_time_unit("ms"))


@pytest.fixture
def live(store, monkeypatch):
    path = fires.places_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"id": [1, 2], "name": ["Westville", "Eastford"], "lat": [9.52, 9.0], "lon": [20.45, 21.9],
                  "country": ["XA", "XA"], "population": [2000, 5000]}).write_parquet(path)
    monkeypatch.setattr(fires, "_PLACES", {})
    found = fires.Live(store, _frame(np.random.default_rng(1)))
    monkeypatch.setitem(store.memo, "live", found)
    yield found
    path.unlink()


def test_link_joins_touching_cells_only():
    lon = np.array([10.0, 10.01, 10.5])
    lat = np.array([5.0, 5.0, 5.0])
    first = fires.link(lon, lat)
    assert first[0] == first[1] != first[2]
    days = fires.link(lon[:2], lat[:2], np.array([1, 2]))
    assert days[0] != days[1]


def test_live_fires(live):
    assert [len(f.idx) for f in live.fires] == [30, 30]
    west = next(f for f in live.fires if f.province == "XA-W")
    assert west.country == "XA" and west.province == "XA-W"
    assert sum(live.passes["XA"].counts) == 60
    assert west.place["name"] == "Westville"


def test_fires_list_and_detail(client, live):
    body = client.get("/api/fires", params={"region": "XA"}).json()
    check("FireList", body)
    assert body["available"] and len(body["fires"]) == 2 and body["days"][-1] == "2026-11-11"
    first = next(f for f in body["fires"] if f["nearest_place"]["name"] == "Westville")
    assert first["nearest_place"]["name"] == "Westville" and first["nearest_place"]["direction"] in range(8)
    assert first["growth"][-1]["detections"] == first["detection_count"] == 30
    assert first["growth"][-1]["area_ha"] == first["area_ha"] > 0
    province = client.get("/api/fires", params={"region": "XA-W"}).json()
    assert [f["id"] for f in province["fires"]] == [first["id"]]
    assert province["passes"] == body["passes"]
    detail = client.get(f"/api/fires/{first['id']}")
    check("FireDetail", detail.json())
    assert len(detail.json()["detections"]) == 30
    early = client.get(f"/api/fires/{first['id']}", params={"pass": 0}).json()
    check("FireDetail", early)
    assert 0 < len(early["detections"]) < 30
    assert client.get(f"/api/fires/{first['id']}", params={"pass": 99}).status_code == 422
    assert client.get("/api/fires/nope").status_code == 404
    assert client.get("/api/fires", params={"region": "ZZ"}).status_code == 404


def test_regions_count_live_fires(client, live):
    counts = {r["id"]: r["fires_now"] for r in client.get("/api/regions", params={"country": "XA"}).json()["regions"]}
    assert counts == {"XA": 2, "XA-W": 1}


def test_demo_and_weather_are_empty(client):
    demo = client.get("/api/fires", params={"demo": 1}).json()
    check("FireList", demo)
    assert demo["available"] is False and demo["source"] == "demo"
    check("FireWeather", client.get("/api/weather/fires").json())


def test_fires_of_a_day_and_clusters_in_days(client, store):
    day = store.last_complete_date - timedelta(days=30)
    body = client.get("/api/calendar/fires", params={"area": "XA", "date": day.isoformat()}).json()
    check("DayFires", body)
    assert body["total"] >= body["shown"] == len(body["fires"])
    detections = [f["detections"] for f in body["fires"]]
    assert detections == sorted(detections, reverse=True)
    days = client.get("/api/calendar/days", params={"area": "XA", "month": day.strftime("%Y-%m")}).json()
    MonthDays.model_validate(days)
    match = [d for d in days["days"] if d["date"] == day.isoformat()]
    assert not match or match[0]["clusters"] == body["total"]
    assert client.get("/api/calendar/fires", params={"area": "XA", "date": "1999-01-01"}).status_code == 422


def test_empty_live(store, monkeypatch):
    monkeypatch.setitem(store.memo, "live", fires.Live(store, None))
    assert fires.fires_now(store, store.regions.by_id["XA"]) == 0


def test_spread_is_measured_between_passes_or_absent(client, live):
    fires_list = client.get("/api/fires", params={"region": "XA"}).json()["fires"]
    west = next(f for f in fires_list if f["nearest_place"]["name"] == "Westville")
    spread = client.get(f"/api/fires/{west['id']}").json()["spread"]
    # the two passes are 11 hours apart; the same footprint, so the edge moved by a few hundred metres at most
    assert spread is None or (spread["rate_source"] == "measured" and spread["rate_m_per_h"] > 0)
    if spread:
        check("Spread", spread)
    assert client.get(f"/api/fires/{west['id']}", params={"pass": 0}).json()["spread"] is None
