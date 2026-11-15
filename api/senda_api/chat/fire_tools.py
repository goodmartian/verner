"""Chat tools about the live fires: the list and the card, from the same functions that feed the fires screen
(`fires.Live`, `weather_routes.conditions_at`). A fire is a cluster of detections of the last three days."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from .. import access as access_module
from .. import areas, fires, landcover
from ..store import Store
from ..weather import HOUR_MS, Weather
from ..weather_routes import conditions_at

COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")
NAMES = {i: names[0] for i, names, _ in landcover.LAND_CLASSES}
MAX_ROWS = 10
GROWTH_PASSES = 4
SORTS = ("area_ha", "growth", "front_speed", "wind", "place")

LIST_FIRES = {
    "name": "list_fires",
    "description": "The live fires of a region: clusters of satellite detections of the last three days, as the Fires "
                   "screen shows them, not official incidents. Returns total, window_days, updated_at and, for each fire: "
                   "id, burn-scar area in hectares (area_ha, estimated from detection cells, not a measured perimeter), "
                   "detection_count, the growth over the last passes, area_change_last_pass_ha and "
                   "area_change_last_pass_pct (the growth between the last two passes, ready in hectares and percent), "
                   "the speed of the front measured between the last two passes from detections only "
                   "(front_speed_m_per_h, null when it cannot be measured), the nearest place with distance and direction, "
                   "and the wind, temperature and humidity at the fire at the start of the last pass (wind.at; a weather "
                   "model value, not a station). A null field means no data.\n"
                   "Use it for any question about the fires burning now (which is biggest, grows fastest, is nearest a "
                   "place, has the strongest wind) and to find the id of a fire before get_fire or make_plan; the "
                   "calendar tools do not see live fires. When the board line says tab fires and an area, pass that "
                   "area's id as region. sort_by: growth for the fastest growing, front_speed for the fastest front, wind "
                   "for the strongest wind, place for the nearest to a settlement, area_ha for the biggest. When a region "
                   "has no live fire, the whole world (WORLD) is the nearest thing that has data.\n"
                   "The person sees a card listing the fires returned, in the same order, each with its nearest place and "
                   "its area; those are not the text. The text names the fire that answers the question, and at most one "
                   "thing that sets it or a second fire apart (it still grows, the wind there is stronger), in words "
                   "rather than the card's figures; it does not go through the fires one by one or give each its "
                   "figures, and it does not explain how the area is estimated unless asked. Two or three sentences "
                   "and an offer make the whole answer. Name a fire by its nearest place, distance and direction "
                   "(the fire so many km north of a town): the id is for the tools and means nothing to the person. When "
                   "the answer goes on to get_fire or make_plan, the list card is not shown, only the card of that fire "
                   "or plan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "region": {"type": "string", "description": "Region id from find_region, or WORLD. Default: WORLD."},
            "sort_by": {"type": "string", "enum": list(SORTS), "description": "Default: area_ha. Fastest growing = growth (area added between the last two passes, hectares and percent)."},
            "limit": {"type": "integer", "description": f"How many fires, 1 to {MAX_ROWS}. Default 5."},
        },
        "additionalProperties": False,
    },
}

GET_FIRE = {
    "name": "get_fire",
    "description": "One live fire by id (from list_fires): the same figures as in the list, plus the growth over all the "
                   "passes of the window and three blocks. land_cover_shares: what the fire burns on, as classes with "
                   "their share of the area in percent (null when the map cannot be read). access: where a crew would "
                   "start (from; from_kind place means no fire station was near and the start is the nearest place), "
                   "drive_km and drive_min by road, walk_km and walk_min on foot from the end of the road, and total_min "
                   "(null when the open map services cannot say). weather_ahead: the forecast of the weather model at the "
                   "fire for up to 24 hours after the last pass: from, hours_covered, rain_mm_total (the rain of the hours "
                   "covered, in mm), max_gust_kmh, min_humidity_pct, and points at 3, 6, 12 and 24 hours with wind_kmh, "
                   "wind_from, gust_kmh, rain_mm_per_h, humidity_pct and temperature_c (null when the forecast does not "
                   "reach that far).\n"
                   "Use it when the person asks about one fire. The person sees the card of the fire with its area, "
                   "detections, power and bars of its passes; those are not the text. The blocks answer only what was "
                   "asked, each in a sentence of prose: what burns there, when asked, as the main one or two classes "
                   "(mostly forest, then grass), not every class; the way there, when asked how to get there or how "
                   "far, as where a crew starts and the part of the way that takes longest; the weather ahead, only "
                   "when the person asks how the fire may go on, about the weather or the wind, or for a plan, as the "
                   "one change that matters (the wind turning or rising, a gust well above the wind, rain with its "
                   "millimetres, or no rain in the forecast), called a forecast of a weather model. When weather_ahead is null, the text says nothing about the "
                   "weather ahead. The fields do not show a cause, containment, damage or how the fire will spread, so "
                   "neither does the text.",
    "input_schema": {
        "type": "object",
        "properties": {"fire_id": {"type": "string", "description": "Fire id, for example 20261110-f72476."}},
        "required": ["fire_id"], "additionalProperties": False,
    },
}


AHEAD_H = (3, 6, 12, 24)  # the hours after the pass the forecast is quoted at
AHEAD_MAX_H = 24


def weather_ahead(weather: Weather | None, lon: float, lat: float, start_ms: int,
                  hours: int = AHEAD_MAX_H) -> dict[str, Any] | None:
    """The forecast of the weather model at a point for the hours after `start_ms`, as far as the grid goes (at most
    `hours`): the wind, the gusts, the rain, the humidity and the temperature at a few hours, the rain summed over the
    hours covered, the strongest gust and the driest hour. None when the grid has less than an hour after that time."""
    if weather is None or not weather.times[0] <= start_ms:
        return None
    covered = int(min(hours, (int(weather.times[-1]) - start_ms) // HOUR_MS))
    if covered < 1:
        return None
    moments = start_ms + np.arange(covered + 1, dtype=np.int64) * HOUR_MS
    found = weather.series(np.array([lon]), np.array([lat]), moments)
    speed, gust, rain = found["speed"][0], found["gust"][0], found["rain"][0]
    humidity, temperature, direction = found["humidity"][0], found["temperature"][0], found["direction"][0]

    def at(h: int) -> dict[str, Any]:
        return {"in_hours": h, "at": fires.iso(int(moments[h])), "wind_kmh": round(float(speed[h]), 1),
                "wind_from": COMPASS[round(float(direction[h]) / 45) % 8], "gust_kmh": round(float(gust[h]), 1),
                "rain_mm_per_h": round(float(rain[h]), 1), "humidity_pct": round(float(humidity[h])),
                "temperature_c": round(float(temperature[h]), 1)}

    return {"from": fires.iso(start_ms), "hours_covered": covered,
            # the rate of each hour after the start, in mm per hour, summed: the millimetres of those hours
            "rain_mm_total": round(float(rain[1:].sum()), 1),
            "max_gust_kmh": round(float(gust[1:].max()), 1), "min_humidity_pct": round(float(humidity[1:].min())),
            "points": [at(h) for h in AHEAD_H if h <= covered]}


def fire_weather_ahead(store: Store, weather: Weather | None, fire_id: str, hours: int = AHEAD_MAX_H) -> dict[str, Any] | None:
    """`weather_ahead` at a live fire, from the start of its last pass."""
    live = fires.live_of(store)
    fire = live.find(fire_id)
    if fire is None or fire.country not in live.passes:
        return None
    return weather_ahead(weather, fire.lon, fire.lat, int(live.passes[fire.country].starts[-1]), hours)


def _row(live: fires.Live, fire: fires.Fire, weather: Weather | None, passes: int) -> dict[str, Any]:
    growth = live.growth(fire)
    last = len(growth) - 1
    spread = live.spread(fire, last) if last >= 1 else None
    place = fire.place or None
    wind = None
    found = conditions_at(weather, fire.lon, fire.lat, live.passes[fire.country].starts[last])
    if found is not None:
        speed, from_deg = found[0](0.0)
        wind = {"speed_kmh": round(speed, 1), "from_deg": round(from_deg), "from": COMPASS[round(from_deg / 45) % 8],
                "temperature_c": round(found[1], 1), "humidity_pct": round(found[2], 1),
                "at": fires.iso(live.passes[fire.country].starts[last])}
    change = growth[-1]["area_ha"] - growth[-2]["area_ha"] if last >= 1 else None
    before = growth[-2]["area_ha"] if last >= 1 else 0
    hours = (growth_time(live, fire, last) - growth_time(live, fire, last - 1)) if last >= 1 else None
    return {
        "id": fire.id, "area_ha": growth[-1]["area_ha"], "detection_count": len(fire.idx),
        "first_detection_at": fires.iso(live.t[fire.idx].min()), "last_detection_at": fires.iso(live.t[fire.idx].max()),
        "nearest_place": None if not place else {"name": place["name"], "distance_km": place["distance_km"],
                                                 "direction": COMPASS[place["direction"]]},
        "area_change_last_pass_ha": change,
        "area_change_last_pass_pct": round(100 * change / before, 1) if change is not None and before else None,
        "hours_between_last_passes": None if hours is None else round(hours, 1),
        "front_speed_m_per_h": None if spread is None else spread["rate_m_per_h"],
        "wind": wind,
        "growth": [{"pass_index": g["pass_index"], "time": g["time"], "area_ha": g["area_ha"],
                    "detections": g["detections"]} for g in growth[-passes:]],
    }


def growth_time(live: fires.Live, fire: fires.Fire, pass_index: int) -> float:
    """Hours since the epoch of a pass start."""
    return live.passes[fire.country].starts[pass_index] / 3_600_000


def _key(sort_by: str):
    def value(row: dict) -> float:
        if sort_by == "place":  # the nearest first: a missing place goes last
            return -(row["nearest_place"]["distance_km"] if row["nearest_place"] else float("inf"))
        if sort_by == "growth":
            return row["area_change_last_pass_ha"] or 0
        if sort_by == "front_speed":
            return row["front_speed_m_per_h"] or 0
        if sort_by == "wind":
            return row["wind"]["speed_kmh"] if row["wind"] else 0
        return row["area_ha"]
    return lambda row: -value(row)


def list_fires(store: Store, weather: Callable[[], Weather | None], region: str, sort_by: str, limit: int) -> dict:
    live = fires.live_of(store)
    if region != areas.WORLD_ID and region not in store.regions.by_id:
        raise KeyError(region)
    rows = [_row(live, f, weather(), GROWTH_PASSES) for f in live.in_region(region) if f.country in live.passes]
    rows.sort(key=_key(sort_by))
    return {"region": region, "total": len(rows), "sorted_by": sort_by, "fires": rows[:limit],
            "window_days": fires.WINDOW_DAYS, "updated_at": fires.iso(live.updated_ms) if len(live.t) else None}


def get_fire(store: Store, weather: Callable[[], Weather | None], fire_id: str,
             land: Callable[[], landcover.LandCover | None] = lambda: None,
             access: Callable[[], access_module.Access | None] = lambda: None) -> dict | None:
    live = fires.live_of(store)
    fire = live.find(fire_id)
    if fire is None or fire.country not in live.passes:
        return None
    grid = weather()
    row = _row(live, fire, grid, len(live.growth(fire)))
    # the forecast at the fire for the day after the last pass; null when the weather grid does not reach that far
    row["weather_ahead"] = weather_ahead(grid, fire.lon, fire.lat, int(live.passes[fire.country].starts[-1]))
    reader, outline = land(), live.detail(fire, int(live.pass_of[fire.idx].max()))["outline"]
    row["land_cover_shares"] = None  # what the fire burns on: null when the land cover cannot be read now
    if reader is not None and outline is not None:
        try:
            row["land_cover_shares"] = [{"class": NAMES[s["id"]], "share_pct": s["share_pct"]}
                                        for s in landcover.shares(reader.read(landcover.snapped_box(outline)), outline)]
        except landcover.LandError:
            pass
    row["access"] = None  # the way to it: from where, how far and how long; null when the open services cannot say now
    way = access()
    if way is not None and outline is not None:
        try:
            found = way.of_outline(outline, fire.place or None)
            row["access"] = {"from": found["station_name"], "from_kind": found["origin_kind"],
                             **{k: found[k] for k in ("drive_km", "drive_min", "walk_km", "walk_min", "total_min")}}
        except access_module.AccessError:
            pass
    return row
