"""`/api/climate/*`: the weather of months from ERA5 (see `climate`). Without a published `climate/current` every
route answers 404 `not_found`."""

from __future__ import annotations

from typing import Annotated, Literal

import numpy as np
from fastapi import APIRouter, Query, Request, Response

from . import areas
from .base import DEFAULT_AREA, store_of
from .climate import LAYERS, RAIN_NORMAL_MIN_MM, VARIABLE, Climate
from .contracts import PNG_RESPONSE, ClimateBounds, ClimateLegend, ClimateMonth, ok
from .errors import ApiError
from .weather_routes import json_body, legend_layer, published, reply

router = APIRouter(prefix="/api/climate", tags=["api"])

MONTH = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Month, YYYY-MM.")]
UNITS = {"temp_c": "°C", "rain_mm": "mm"}
KEYS = {"temp_c": "temperature_c", "rain_mm": "rain_mm"}


def climate_of(request: Request) -> Climate:
    found = published(request, "climate", request.app.state.settings.climate_dir, Climate.open).current()
    if found is None:
        raise ApiError(404, "not_found", "There is no climate data")
    return found


def climate_or_none(request: Request) -> Climate | None:
    """The climate of this app, or None when none is published: for a reader that goes on without it."""
    try:
        return climate_of(request)
    except ApiError:
        return None


@router.get("/legend", responses=ok(ClimateLegend))
def get_legend(request: Request):
    climate = climate_of(request)
    layers = [{**legend_layer(LAYERS[name]), "kind": "anomaly"} for name in LAYERS]
    return {"available": True, "attribution": climate.attribution, "first_month": climate.first_label,
            "last_month": climate.last_label, "month_layers": layers}


@router.get("/grid/bounds", responses=ok(ClimateBounds))
def get_bounds(request: Request):
    climate = climate_of(request)
    west, south, east, north = climate.bounds
    width, height = climate.picture_size()
    body = {"bounds": [west, south, east, north],
            "coordinates": [[west, north], [east, north], [east, south], [west, south]], "width": width,
            "height": height}
    return reply(request, climate.run_id, "bounds", json_body(body), "application/json")


@router.get("/grid.png", response_class=Response, responses=PNG_RESPONSE)
def get_picture(request: Request, layer: Annotated[Literal["temperature", "rain"], Query()], month: MONTH):
    climate = climate_of(request)
    if climate.index(month) is None:
        raise ApiError(404, "not_found", f"There is no climate for {month}")
    return reply(request, climate.run_id, f"grid/{layer}/{month}", lambda: climate.picture(layer, month) or b"",
                 "image/png")


@router.get("/month", responses=ok(ClimateMonth))
def get_month(request: Request, month: MONTH, area: Annotated[str, Query(min_length=1, max_length=64)] = DEFAULT_AREA):
    return month_weather(climate_of(request), areas.parse({"id": area}, store_of(request)), area, month)


def month_weather(climate: Climate, chosen: areas.Area, area: str, month: str) -> dict:
    """The temperature and the rain of a month averaged over an area, each against its normal and among the years;
    `kind` none when the month has no data. `area` is how the answer names the area."""
    number, i = int(month[5:7]), climate.index(month)
    end = climate.index(climate.last_label)
    body = {"area": area, "month": month, "kind": "none", "observed": None, "attribution": None}
    if i is None:
        return body
    quantities = []
    for variable in VARIABLE.values():
        series = climate.area_series(variable, chosen)
        value, normal = series[i], climate.area_normal(variable, number, chosen)
        if np.isnan(value) or normal is None:
            return body  # a gap over this area
        years = [v for v in series[(number - climate.first_month) % 12:end + 1:12] if not np.isnan(v)]
        rain = variable == "rain_mm"
        ratio = None if not rain or normal <= RAIN_NORMAL_MIN_MM else round(float(value) / normal, 3)
        quantities.append({
            "key": KEYS[variable], "unit": UNITS[variable], "value": round(float(value), 2), "normal": round(normal, 2),
            "anomaly": ratio if rain else round(float(value) - normal, 2),
            "anomaly_kind": "ratio" if rain else "difference",
            # the rain against its normal in percent, rounded here once: the assistant and its card say the same
            "change_pct": None if ratio is None else round((ratio - 1) * 100),
            "rank": 1 + int(sum(v > value for v in years)), "of_years": len(years)})
    first, last = climate.normal_years
    return {**body, "kind": "observed", "attribution": climate.attribution,
            "observed": {"quantities": quantities, "normal_first_year": first, "normal_last_year": last}}
