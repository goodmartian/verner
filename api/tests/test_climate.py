import json

import pytest
from climate_files import write
from fastapi.testclient import TestClient
from test_weather import decode_png

from senda_api.app import create_app
from senda_api.settings import Settings


@pytest.fixture
def cx(store, tmp_path):
    folder = write(tmp_path / "climate" / "current")
    return TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, climate_dir=folder)))


def test_without_files_every_route_says_not_found(store, tmp_path):
    client = TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, climate_dir=tmp_path / "x")))
    for path in ("legend", "grid/bounds", "grid.png?layer=rain&month=2025-06", "month?month=2025-06&area=XA"):
        got = client.get(f"/api/climate/{path}")
        assert got.status_code == 404 and got.json()["error"]["code"] == "not_found"


def test_legend_and_bounds(cx):
    legend = cx.get("/api/climate/legend").json()
    assert legend["available"] and (legend["first_month"], legend["last_month"]) == ("2024-01", "2025-06")
    assert [x["layer"] for x in legend["month_layers"]] == ["temperature", "rain"]
    bounds = cx.get("/api/climate/grid/bounds").json()
    assert bounds["bounds"][0] == -180 and bounds["width"] == 24 and bounds["coordinates"][0][0] == -180


def test_month_of_an_area_has_value_normal_anomaly_and_rank(cx):
    body = cx.get("/api/climate/month", params={"month": "2025-06", "area": "XA"}).json()
    assert body["kind"] == "observed" and body["attribution"] == "ERA5 test"
    temp, rain = body["observed"]["quantities"]
    assert (temp["key"], temp["value"], temp["normal"], temp["anomaly"]) == ("temperature_c", 17.0, 16.0, 1.0)
    assert (temp["rank"], temp["of_years"]) == (1, 2)
    assert (rain["value"], rain["normal"], rain["anomaly"], rain["anomaly_kind"]) == (100.0, 50.0, 2.0, "ratio")
    older = cx.get("/api/climate/month", params={"month": "2024-06", "area": "XA"}).json()["observed"]["quantities"]
    assert (older[0]["anomaly"], older[0]["rank"], older[1]["anomaly"]) == (0.5, 2, 0.5)


def test_month_outside_the_data_or_over_a_gap_is_none(cx, store, tmp_path):
    assert cx.get("/api/climate/month", params={"month": "2025-07", "area": "XA"}).json()["kind"] == "none"
    gapped = TestClient(create_app(store=store, settings=Settings(
        anthropic_api_key=None, climate_dir=write(tmp_path / "gap", gap_month=17))))
    got = gapped.get("/api/climate/month", params={"month": "2025-06", "area": "XA"}).json()
    assert got["kind"] == "none" and got["observed"] is None


def test_picture_is_a_png_with_etag_and_unknown_month_is_404(cx):
    got = cx.get("/api/climate/grid.png", params={"layer": "temperature", "month": "2025-06"})
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    pixels = decode_png(got.content)
    assert pixels.shape[1] == 24 and pixels[..., 3].max() > 0
    again = cx.get("/api/climate/grid.png", params={"layer": "temperature", "month": "2025-06"},
                   headers={"If-None-Match": got.headers["etag"]})
    assert again.status_code == 304
    assert cx.get("/api/climate/grid.png", params={"layer": "rain", "month": "2030-01"}).status_code == 404
    assert cx.get("/api/climate/month", params={"month": "bad", "area": "XA"}).status_code == 422
    assert cx.get("/api/climate/month", params={"month": "2025-06", "area": "nope"}).status_code in (400, 404)


def test_years_compared_stop_at_the_last_month_with_every_variable(cx, store, tmp_path):
    folder = write(tmp_path / "early")
    meta = json.loads((folder / "meta.json").read_text())
    meta["last_data_month"] = "2024-12"  # the months after it may hold one variable only
    (folder / "meta.json").write_text(json.dumps(meta))
    client = TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, climate_dir=folder)))
    got = client.get("/api/climate/month", params={"month": "2024-06", "area": "XA"}).json()["observed"]["quantities"]
    assert [q["of_years"] for q in got] == [1, 1]
    assert client.get("/api/climate/month", params={"month": "2025-06", "area": "XA"}).json()["kind"] == "none"
