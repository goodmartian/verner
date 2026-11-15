import struct
import zlib

import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapes import check
from test_fires import live  # noqa: F401
from weather_files import COLS, LAT0, LON0, ROWS, START, STEP, STEPS, lat_of, lon_of, values, write

from senda_api import weather_routes
from senda_api.app import create_app
from senda_api.settings import Settings
from senda_api.weather import WIND_BLOCK, WIND_RANGE, WeatherSource
from senda_api.weather_legend import DRYNESS, WIND, vpd_kpa

T = "2026-11-10T{:02d}:00:00Z"


@pytest.fixture
def folder(tmp_path):
    return write(tmp_path / "weather" / "current")


@pytest.fixture
def wx(store, folder):
    return TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=folder)))


def decode_png(data: bytes) -> np.ndarray:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, size = 8, b"", None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            size = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    width, height = size
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(height, 1 + width * 4)
    assert not raw[:, 0].any()
    return raw[:, 1:].reshape(height, width, 4)


def test_without_weather_files_everything_says_no_data(store, tmp_path):
    client = TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=tmp_path / "none")))
    legend = client.get("/api/weather/legend").json()
    check("WeatherLegend", legend)
    assert legend["available"] is False and legend["layers"] == []
    fires = client.get("/api/weather/fires").json()
    check("FireWeather", fires)
    assert fires["available"] is False
    for path in ("grid/bounds", "wind", "wind-field.png", "grid.png?layer=rain", "at?lon=1&lat=1"):
        assert client.get(f"/api/weather/{path}").status_code == 404
    assert client.get("/api/regions").status_code == 200  # the rest of the app works


def test_legend_and_bounds_follow_the_forms(wx):
    legend = wx.get("/api/weather/legend").json()
    check("WeatherLegend", legend)
    assert [layer["layer"] for layer in legend["layers"]] == ["wind", "rain", "dryness"]
    assert legend["available"] and "NOAA GFS" in legend["attribution"]
    assert legend["grid"]["start"] == T.format(0) and legend["grid"]["end"] == T.format(24).replace("10T24", "11T00")
    assert legend["grid"]["hours"] == 25 and legend["grid"]["cycle"] == T.format(12)
    assert legend["fires"]["cycle"] is None
    rain = legend["layers"][1]
    assert rain["bands"][0]["high"] == 0.1 and rain["bands"][-1]["high"] is None and rain["opacity"] == 0.7
    bounds = wx.get("/api/weather/grid/bounds").json()
    check("GridBounds", bounds)
    assert bounds["bounds"][0] == -180 and bounds["wind_field"]["width"] == COLS // WIND_BLOCK
    assert wx.headers.get("x") is None
    again = wx.get("/api/weather/grid/bounds", headers={"If-None-Match": wx.get("/api/weather/grid/bounds").headers["etag"]})
    assert again.status_code == 304


def test_value_at_a_point_in_space_and_time(wx):
    # halfway between columns 13 and 14 (lon 15 and 30), rows 2 and 3 (lat 60 and 45), at 01:30 (steps 0 and 1 half)
    lon, lat, hour = 22.5, 52.5, "2026-11-10T01:30:00Z"
    body = wx.get("/api/weather/at", params={"lon": lon, "lat": lat, "time": hour}).json()
    check("WeatherAt", body)
    step = 0.5
    u = 2.0 + lon / 30.0 + step
    v = -3.0 + lat / 30.0
    assert body["wind"]["speed_kmh"] == pytest.approx(np.hypot(u, v) * 3.6, abs=0.15)
    assert body["wind"]["from_deg"] == round(np.degrees(np.arctan2(-u, -v)) % 360) % 360
    assert body["temperature_c"] == pytest.approx(20 + lon / 15 + 2 * step, abs=0.06)
    assert body["humidity_pct"] == round(40 + step * 5)
    vpd = float(vpd_kpa(np.array(body["temperature_c"]), np.array(body["humidity_pct"])))
    assert body["dryness"]["vpd_kpa"] == pytest.approx(vpd, abs=0.1)
    assert body["dryness"]["category"] == int(DRYNESS.band_of(np.array([body["dryness"]["vpd_kpa"]]))[0])
    assert body["wind"]["category"] == int(WIND.band_of(np.array([body["wind"]["speed_kmh"]]))[0])
    assert body["wind"]["gust_kmh"] >= body["wind"]["speed_kmh"]


def test_time_interpolation_is_linear_between_steps(wx):
    def temp(hour):
        return wx.get("/api/weather/at", params={"lon": 30, "lat": 45, "time": f"2026-11-10T{hour:02d}:00:00Z"}).json()["temperature_c"]

    a, b, mid = temp(3), temp(6), temp(4)
    assert b - a == pytest.approx(2.0, abs=0.02)  # 2 degrees per step
    assert mid == pytest.approx(a + (b - a) / 3, abs=0.06)
    rain = [wx.get("/api/weather/at", params={"lon": 30, "lat": 75, "time": f"2026-11-10T{h:02d}:00:00Z"}).json()["rain"]["mm_per_h"]
            for h in (9, 10, 11, 12, 13, 14, 15)]
    assert rain == pytest.approx([0, 1, 2, 3, 2, 1, 0], abs=0.01)  # a shower at step 4 (12:00), 3 mm/h


def test_outside_the_window_there_is_no_data(wx):
    late = "2026-11-12T00:00:00Z"
    assert wx.get("/api/weather/at", params={"lon": 1, "lat": 1, "time": late}).status_code == 404
    for path in ("grid.png?layer=rain&time=" + late, "wind-field.png?time=" + late, "wind?time=" + late):
        res = wx.get(f"/api/weather/{path}")
        assert res.status_code == 422 and res.json()["error"]["code"] == "validation_error"
    assert wx.get("/api/weather/grid.png", params={"layer": "wind"}).status_code == 422
    assert wx.get("/api/weather/at", params={"lon": 500, "lat": 1}).status_code == 422


def test_wind_field_picture_decodes_back_to_u_and_v(wx):
    res = wx.get("/api/weather/wind-field.png", params={"time": T.format(6)})
    assert res.headers["content-type"] == "image/png"
    pixels = decode_png(res.content)
    info = wx.get("/api/weather/grid/bounds").json()["wind_field"]
    assert pixels.shape == (info["height"], info["width"], 4)
    first = 1  # row 0 is the pole, outside the map; the 11 rows within +-75 make whole blocks
    assert (info["height"], info["width"]) == ((ROWS - 2) // WIND_BLOCK, COLS // WIND_BLOCK)
    want = values(2)
    tolerance = 2 * WIND_RANGE / 255 / 2 + 0.011
    for row in range(info["height"]):
        for col in (0, 3, info["width"] - 1):
            block = (slice(first + WIND_BLOCK * row, first + WIND_BLOCK * (row + 1)), slice(WIND_BLOCK * col, WIND_BLOCK * (col + 1)))
            u = pixels[row, col, 0] / 255 * 2 * WIND_RANGE - WIND_RANGE
            v = pixels[row, col, 1] / 255 * 2 * WIND_RANGE - WIND_RANGE
            assert u == pytest.approx(want["wind_u"][block].mean(), abs=tolerance)
            assert v == pytest.approx(want["wind_v"][block].mean(), abs=tolerance)
            assert pixels[row, col, 3] == 255


def test_layer_pictures_are_painted_with_the_bands(wx):
    bounds = wx.get("/api/weather/grid/bounds").json()
    rain = decode_png(wx.get("/api/weather/grid.png", params={"layer": "rain", "time": T.format(12)}).content)
    assert rain.shape == (bounds["height"], bounds["width"], 4)
    assert rain[..., 3].min() == 0 and rain[..., 3].max() == 255  # dry cells are clear, the shower is painted
    north = rain[: rain.shape[0] // 4]
    assert (north[..., 3] == 255).any() and not (rain[-rain.shape[0] // 4:][..., 3] == 255).any()
    dry = decode_png(wx.get("/api/weather/grid.png", params={"layer": "dryness", "time": T.format(12)}).content)
    assert (dry[..., 3] == 255).all()
    assert len({tuple(p) for p in dry.reshape(-1, 4)}) > 1


def test_wind_arrows_thin_out_by_zoom(wx):
    few = wx.get("/api/weather/wind", params={"time": T.format(6), "zoom": 2}).json()
    check("WindPoints", few)
    many = wx.get("/api/weather/wind", params={"time": T.format(6), "zoom": 9}).json()
    check("WindPoints", many)
    assert 0 < len(many["features"]) and len(few["features"]) <= len(many["features"]) and many["time"] == T.format(6)
    assert all(abs(f["geometry"]["coordinates"][1]) <= 80 for f in many["features"])


def test_files_are_memory_mapped_and_a_new_run_is_picked_up(store, tmp_path):
    folder = write(tmp_path / "w" / "current", "one")
    source = WeatherSource(folder)
    first = source.current()
    assert first and first.run_id == "one" and first.hours == 25
    assert all(isinstance(array, np.memmap) for array, _ in first.arrays.values())
    write(folder, "two", gap=True)
    assert source.current() is first  # looked a moment ago: not again before a minute has passed
    source._checked = -1e9
    second = source.current()
    assert second and second.run_id == "two" and second is not first
    assert second.field("precip", int(second.times[0])).min() == 0  # a gap reads as 0


def test_fire_weather_and_the_fire_card(store, wx, live):  # noqa: F811
    fires = wx.get("/api/fires", params={"region": "XA"}).json()["fires"]
    series = wx.get("/api/weather/fires").json()
    check("FireWeather", series)
    assert series["available"] and series["hours"] == 25 and {f["fire_id"] for f in series["fires"]} >= {f["id"] for f in fires}
    one = next(f for f in series["fires"] if f["fire_id"] == fires[0]["id"])
    assert len(one["speed_kmh"]) == 25 and one["position"] == pytest.approx(fires[0]["center"], abs=1e-3)
    detail = wx.get(f"/api/fires/{fires[0]['id']}").json()
    check("FireDetail", detail)
    assert detail["weather"]["source"] == "grid" and len(detail["weather"]["wind_speed_kmh"]) == 25
    assert detail["weather"]["wind_speed_kmh"] == pytest.approx(one["speed_kmh"], abs=0.1)


def test_helpers_are_the_formulas():
    assert lat_of(0) == LAT0 and lon_of(0) == LON0 and STEP == 15 and ROWS == 13 and STEPS == 9 and START.hour == 0
    assert weather_routes.ATTRIBUTION.startswith("Weather: NOAA GFS")
