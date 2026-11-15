"""`/api/weather/*` over the NOAA GFS files (see `weather`).

Without a published run (no `weather/current` folder) every route still answers: a legend that says
`available: false`, empty fire weather, 404 `not_found` for the pictures, arrows and points.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from . import areas, fires
from .base import store_of
from .contracts import PNG_RESPONSE, FireWeather, GridBounds, WeatherAt, WeatherLegend, WindPoints, ok
from .errors import ApiError
from .weather import WIND_RANGE, Weather, WeatherSource
from .weather_legend import DRYNESS, LEGENDS, RAIN, WIND, LayerLegend, Names, hdw

router = APIRouter(prefix="/api/weather", tags=["api"])

ATTRIBUTION = "Weather: NOAA GFS 0.25 degree forecasts and analyses (NOAA/NCEP, public domain)."
MAX_FIRES = 2000
MAX_IDS = 200
LAYER = Annotated[str, Query(pattern="^(wind|rain|dryness)$", description="`rain` or `dryness`.")]
TIME = Annotated[datetime | None, Query(description="The hour, ISO 8601 (UTC without an offset); now if left out.")]
_LOCK = threading.Lock()


def published(request: Request, name: str, configured: Path | None, opener: Callable[[Path], Any] | None = None) -> WeatherSource:
    """The files of `name` (weather, climate) of this app: the folder in the settings, else `<name>/current` next to the
    data versions. Kept on the app, looked at again once a minute."""
    state = request.app.state
    attr = f"{name}_source"
    with _LOCK:
        if getattr(state, attr, None) is None:
            folder = configured
            if folder is None:
                try:
                    folder = store_of(request).root.resolve().parents[1] / name / "current"
                except (ApiError, IndexError):
                    return WeatherSource(None)  # the data is not loaded yet: ask again next time
            setattr(state, attr, WeatherSource(folder, opener))
        return getattr(state, attr)


def source_of(request: Request) -> WeatherSource:
    return published(request, "weather", request.app.state.settings.weather_dir)


def weather_of(request: Request) -> Weather | None:
    return source_of(request).current()


def grid_of(request: Request) -> Weather:
    weather = weather_of(request)
    if weather is None:
        raise ApiError(404, "not_found", "There is no weather in this data")
    return weather


def utc(time: datetime | None) -> datetime | None:
    return time if time is None or time.tzinfo else time.replace(tzinfo=UTC)


def iso(ms: int) -> str:
    return fires.iso(int(ms))


def reply(request: Request, version: str, key: str, body: Callable[[], bytes], media_type: str) -> Response:
    """The body with an ETag of the run and the question; 304 when the browser has it."""
    etag = f'"{version}-{hashlib.sha1(key.encode()).hexdigest()[:16]}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers=headers)
    return Response(content=body(), media_type=media_type, headers=headers)


def json_body(data: Any) -> Callable[[], bytes]:
    return lambda: JSONResponse(data).body


def names(value: Names) -> dict:
    return {"en": value.en, "ru": value.ru, "es": value.es}


def legend_layer(legend: LayerLegend) -> dict:
    bands = legend.bands
    return {"layer": legend.layer, "unit": legend.unit, "name": names(legend.name),
            "description": names(legend.description), "opacity": legend.opacity,
            "bands": [{"id": b.id, "low": b.low, "high": bands[i + 1].low if i + 1 < len(bands) else None,
                       "name": names(b.name), "color": b.color} for i, b in enumerate(bands)]}


def span(weather: Weather, cycle: bool) -> dict:
    return {"start": iso(weather.times[0]), "end": iso(weather.times[-1]), "hours": weather.hours,
            "updated_at": weather.built_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "cycle": weather.analysis_until.strftime("%Y-%m-%dT%H:%M:%SZ") if cycle else None}


def _rounded(values: np.ndarray, digits: int) -> list[float]:
    return np.round(values, digits).tolist()


def hourly(found: dict[str, np.ndarray], row: int = 0) -> dict[str, Any]:
    """The fields of an hourly series of one point (row `row` of `Weather.series`), with bands and the HDW index."""
    speed, vpd = found["speed"][row], found["vpd"][row]
    return {"speed_kmh": _rounded(speed, 1), "gust_kmh": _rounded(found["gust"][row], 1),
            "from_deg": [round(v) % 360 for v in found["direction"][row]],
            "wind_category": WIND.band_of(speed).tolist(), "precip_mm": _rounded(found["rain"][row], 2),
            "vpd_kpa": _rounded(vpd, 2), "hdw": _rounded(hdw(vpd, speed), 1),
            "dryness_category": DRYNESS.band_of(vpd).tolist(), "temperature_c": _rounded(found["temperature"][row], 1),
            "humidity_pct": _rounded(found["humidity"][row], 1)}


def conditions_at(weather: Weather | None, lon: float, lat: float, start_ms: int) -> tuple[Callable, float, float] | None:
    """The weather at a point from `start_ms` on: the wind as a function of hours after it (speed km/h, direction it
    blows from), and the temperature and humidity at the start. None when the grid does not cover that time."""
    if weather is None or not weather.times[0] <= start_ms <= weather.times[-1]:
        return None
    hours = np.arange(0.0, 8.0 + 0.25, 0.25)
    moments = np.minimum(start_ms + (hours * 3_600_000).astype(np.int64), weather.times[-1])
    found = weather.series(np.array([lon]), np.array([lat]), moments)
    east, north = found["u"][0], found["v"][0]

    def wind(h: float) -> tuple[float, float]:
        u, v = float(np.interp(h, hours, east)), float(np.interp(h, hours, north))
        return float(np.hypot(u, v) * 3.6), float(np.degrees(np.arctan2(-u, -v)) % 360)

    return wind, float(found["temperature"][0][0]), float(found["humidity"][0][0])


def fire_weather_at(weather: Weather | None, fire: fires.Fire) -> dict | None:
    """The `weather` of a fire's card: the hours of the grid at the fire's centre; None without weather."""
    if weather is None:
        return None
    found = weather.series(np.array([fire.lon]), np.array([fire.lat]), weather.hourly())
    return {"source": "grid", "start": iso(weather.times[0]),
            "wind_speed_kmh": _rounded(found["speed"][0], 1),
            "wind_from_deg": [round(v) % 360 for v in found["direction"][0]],
            "temperature_c": _rounded(found["temperature"][0], 1),
            "humidity_pct": [round(v) for v in found["humidity"][0]]}


@router.get("/legend", responses=ok(WeatherLegend))
def get_legend(request: Request):
    weather = weather_of(request)
    if weather is None:
        return {"available": False, "attribution": None, "grid": None, "fires": None, "layers": []}
    body = {"available": True, "attribution": ATTRIBUTION, "grid": span(weather, True), "fires": span(weather, False),
            "layers": [legend_layer(LEGENDS[n]) for n in ("wind", "rain", "dryness")]}
    return reply(request, weather.run_id, "legend", json_body(body), "application/json")


@router.get("/fires", responses=ok(FireWeather))
def get_fire_weather(request: Request, region: Annotated[str | None, Query(max_length=64)] = None,
                     ids: Annotated[str | None, Query(max_length=4000)] = None):
    """The weather at the live fires: all of them, or only those of a `region`, or only the listed `ids` (up to 200)."""
    weather = weather_of(request)
    if weather is None:
        return {"available": False, "start": None, "hours": 0, "fires": []}
    store = store_of(request)
    live = fires.live_of(store)
    if region is not None and region != areas.WORLD_ID and region not in store.regions.by_id:
        raise ApiError(404, "not_found", f"No data for region {region}")
    wanted = [i for i in (ids or "").split(",") if i]
    if len(wanted) > MAX_IDS:
        raise ApiError(422, "validation_error", f"ids: at most {MAX_IDS} fires")
    pool = live.in_region(region) if region is not None else live.fires
    if ids is not None:
        pool = [f for f in pool if f.id in set(wanted)]
    chosen = sorted(pool, key=lambda f: -len(f.idx))[:MAX_FIRES]

    def body() -> dict:
        found = (weather.series(np.array([f.lon for f in chosen]), np.array([f.lat for f in chosen]), weather.hourly())
                 if chosen else {})
        return {"available": True, "start": iso(weather.times[0]), "hours": weather.hours,
                "fires": [{"fire_id": f.id, "position": [round(f.lon, 4), round(f.lat, 4)],
                           **hourly(found, i)} for i, f in enumerate(chosen)]}

    key = f"fires/{live.updated_ms}/{region}/{','.join(sorted(wanted))}/{len(chosen)}"
    return reply(request, weather.run_id, key, lambda: JSONResponse(body()).body, "application/json")


@router.get("/wind", responses=ok(WindPoints))
def get_wind(request: Request, time: TIME = None, zoom: Annotated[float, Query(ge=0, le=22)] = 5):
    weather = grid_of(request)
    ms = weather.hour_ms(utc(time))

    def body() -> dict:
        return {"type": "FeatureCollection", "time": iso(ms),
                "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": c["position"]},
                              "properties": {k: c[k] for k in ("speed_kmh", "gust_kmh", "from_deg", "category", "color")}}
                             for c in weather.wind_cells(ms, zoom)]}

    return reply(request, weather.run_id, f"wind/{ms}/{zoom:.1f}", lambda: JSONResponse(body()).body,
                 "application/geo+json")


@router.get("/grid.png", response_class=Response, responses=PNG_RESPONSE)
def get_grid_picture(request: Request, layer: LAYER, time: TIME = None):
    if layer == "wind":
        raise ApiError(422, "validation_error", "layer: the wind is /api/weather/wind")
    weather = grid_of(request)
    ms = weather.hour_ms(utc(time))
    return reply(request, weather.run_id, f"grid/{layer}/{ms}", lambda: weather.picture(layer, ms), "image/png")


@router.get("/grid/bounds", responses=ok(GridBounds))
def get_bounds(request: Request):
    weather = grid_of(request)
    west, south, east, north = weather.bounds
    width, height = weather.picture_size()
    field_width, field_height = weather.field_size()
    body = {"bounds": [west, south, east, north],
            "coordinates": [[west, north], [east, north], [east, south], [west, south]], "width": width,
            "height": height, "start": iso(weather.times[0]), "end": iso(weather.times[-1]), "hours": weather.hours,
            "cycle": weather.analysis_until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "wind_field": {"width": field_width, "height": field_height, "u_min": -WIND_RANGE,
                           "u_max": WIND_RANGE, "v_min": -WIND_RANGE, "v_max": WIND_RANGE}}
    return reply(request, weather.run_id, "bounds", json_body(body), "application/json")


@router.get("/wind-field.png", response_class=Response, responses=PNG_RESPONSE)
def get_wind_field(request: Request, time: TIME = None):
    weather = grid_of(request)
    ms = weather.hour_ms(utc(time))
    return reply(request, weather.run_id, f"field/{ms}", lambda: weather.wind_field(ms), "image/png")


@router.get("/at", responses=ok(WeatherAt))
def get_weather_at(request: Request, lon: Annotated[float, Query(ge=-180, le=180)],
                   lat: Annotated[float, Query(ge=-90, le=90)], time: TIME = None):
    weather = grid_of(request)
    try:
        ms = weather.hour_ms(utc(time))
    except ApiError as error:  # the front reads a 404 as "nothing here" and shows no card
        raise ApiError(404, "not_found", error.message) from error

    def body() -> dict:
        found = weather.series(np.array([lon]), np.array([lat]), np.array([ms], dtype=np.int64))
        one = {k: float(v[0, 0]) for k, v in found.items()}
        wind, rain, dry = (int(L.band_of(np.array([x]))[0]) for L, x in
                           ((WIND, one["speed"]), (RAIN, one["rain"]), (DRYNESS, one["vpd"])))
        return {"time": iso(ms), "position": [lon, lat],
                "wind": {"speed_kmh": round(one["speed"], 1), "gust_kmh": round(one["gust"], 1),
                         "from_deg": round(one["direction"]) % 360, "category": wind, "color": WIND.bands[wind].color},
                "rain": {"mm_per_h": round(one["rain"], 2), "category": rain, "color": RAIN.bands[rain].color},
                "dryness": {"vpd_kpa": round(one["vpd"], 2),
                            "hdw": round(float(hdw(np.array([one["vpd"]]), np.array([one["speed"]]))[0]), 1),
                            "category": dry, "color": DRYNESS.bands[dry].color},
                "temperature_c": round(one["temperature"], 1), "humidity_pct": round(one["humidity"])}

    return reply(request, weather.run_id, f"at/{lon:.3f}/{lat:.3f}/{ms}", lambda: JSONResponse(body()).body,
                 "application/json")
