"""`/api/fires*`, `/api/calendar/fires`."""

from __future__ import annotations

from datetime import date
from typing import Annotated

import numpy as np
import shapely
from fastapi import APIRouter, Query, Request

from . import access, areas, fires, landcover, plan, weather_routes
from .base import DEFAULT_AREA, store_of
from .contracts import AccessRoute, DayFires, FireDetail, FireList, FirePlan, LandCover, ok
from .errors import ApiError
from .months import month_start
from .summary import ATTRIBUTION as CALENDAR_ATTRIBUTION

router = APIRouter(tags=["api"])

MAX_DAY_FIRES = 1000


@router.get("/api/fires", responses=ok(FireList))
def list_fires(request: Request, demo: bool = False, region: Annotated[str | None, Query(max_length=64)] = None):
    store = store_of(request)
    if region is not None and region != areas.WORLD_ID and region not in store.regions.by_id:
        raise ApiError(404, "not_found", f"No data for region {region}")
    if demo:  # the example of the web app (Corrientes, February 2022) is not part of this data
        return {"source": "demo", "available": False, "updated_at": None, "days": [], "passes": [], "fires": [],
                "attribution": None}
    return fires.live_of(store).listing(region)


def _find(request: Request, fire_id: str, pass_: int | None) -> tuple[fires.Live, fires.Fire, int]:
    return find(store_of(request), fire_id, pass_)


def find(store, fire_id: str, pass_: int | None) -> tuple[fires.Live, fires.Fire, int]:
    live = fires.live_of(store)
    fire = live.find(fire_id)
    if fire is None:
        raise ApiError(404, "not_found", f"No fire {fire_id}")
    last = len(live.passes[fire.country].starts) - 1
    if pass_ is not None and pass_ > last:
        raise ApiError(422, "validation_error", f"pass: there is no pass {pass_}, from 0 to {last}")
    # by default the last pass in which this fire has detections: the same for the card and the plan
    return live, fire, int(live.pass_of[fire.idx].max()) if pass_ is None else pass_


def _view(live: fires.Live, fire: fires.Fire, upto: int, wind, spread: dict | None) -> plan.FireView:
    """What the planner needs of a fire at pass `upto`."""
    starts = live.passes[fire.country].starts
    number = live.pass_of[fire.idx]
    keep = fire.idx[number <= upto]
    return plan.FireView(
        fire_id=fire.id, pass_index=upto, latest_pass=len(starts) - 1, pass_time=fires.iso(starts[upto]),
        lon=live.lon[keep], lat=live.lat[keep], pass_of=live.pass_of[keep],
        rate_m_per_h=None if spread is None else spread["rate_m_per_h"], wind=wind, place=fire.place or None,
        source="live", attribution=fires.ATTRIBUTION, area_ha=float(live.growth(fire)[upto]["area_ha"]),
        hours_behind=(starts[-1] - starts[upto]) / 3_600_000, frp=live.frp[keep])


@router.get("/api/fires/{fire_id}", responses=ok(FireDetail))
def get_fire(request: Request, fire_id: str, pass_: Annotated[int | None, Query(alias="pass", ge=0)] = None):
    return fire_card(request, fire_id, pass_)


def fire_card(request: Request, fire_id: str, pass_: int | None) -> dict:
    return fire_card_of(store_of(request), weather_routes.weather_of(request), fire_id, pass_)


def fire_card_of(store, weather, fire_id: str, pass_: int | None) -> dict:
    """The card of a fire: the route and the assistant make it here, from the same data."""
    live, fire, upto = find(store, fire_id, pass_)
    detail = live.detail(fire, upto)
    spread = detail["spread"]
    start = live.passes[fire.country].starts[upto]
    found = weather_routes.conditions_at(weather, fire.lon, fire.lat, start) if spread is not None else None
    if found is not None:  # without a measured speed or without wind there is no front to draw
        wind, temperature, humidity = found
        speed, from_deg = wind(0.0)
        spread["wind"] = {"speed_kmh": round(speed, 1), "from_deg": round(from_deg), "temperature_c": round(temperature, 1),
                          "humidity_pct": round(humidity, 1), "at": detail["pass_time"]}
        spread["length_to_breadth"] = round(plan.length_to_breadth(speed), 2)
        spread["contours"] = plan.contours(_view(live, fire, upto, wind, spread))
    return {**detail, "weather": weather_routes.fire_weather_at(weather, fire)}


def land_of(request: Request) -> landcover.LandCover:
    """The land cover reader of this app; its grids are kept in `data/_work/landcover` next to the data versions."""
    state = request.app.state
    if getattr(state, "land", None) is None:
        try:
            folder = store_of(request).root.resolve().parents[1] / "_work" / "landcover"
        except (ApiError, IndexError):
            folder = None
        state.land = landcover.LandCover(folder)
    return state.land


@router.get("/api/fires/{fire_id}/land-cover", responses=ok(LandCover))
def get_land_cover(request: Request, fire_id: str, pass_: Annotated[int | None, Query(alias="pass", ge=0)] = None):
    live, fire, upto = _find(request, fire_id, pass_)
    outline = live.detail(fire, upto)["outline"]
    if outline is None:
        raise ApiError(404, "not_found", "This fire has no outline yet")
    try:
        return land_of(request).of_outline(outline)
    except landcover.LandError as error:
        raise ApiError(404, "not_found", str(error)) from None


def access_of(request: Request) -> access.Access:
    """The reader of the way to a fire; its answers are kept in `data/_work/access` next to the data versions."""
    state = request.app.state
    if getattr(state, "access", None) is None:
        try:
            folder = store_of(request).root.resolve().parents[1] / "_work" / "access"
        except (ApiError, IndexError):
            folder = None
        state.access = access.Access(folder, google_key=state.settings.google_maps_key,
                                     db=state.db if state.settings.database_url else None)
    return state.access


@router.get("/api/fires/{fire_id}/access-route", responses=ok(AccessRoute))
def get_access_route(request: Request, fire_id: str, pass_: Annotated[int | None, Query(alias="pass", ge=0)] = None):
    live, fire, upto = _find(request, fire_id, pass_)
    outline = live.detail(fire, upto)["outline"]
    if outline is None:
        raise ApiError(404, "not_found", "This fire has no outline yet")
    try:
        return access_of(request).of_outline(outline, fire.place or None)
    except access.AccessError:
        raise ApiError(404, "not_found", "There is no way to this fire from the open map services now") from None


@router.post("/api/fires/{fire_id}/plan", responses=ok(FirePlan))
def post_plan(request: Request, fire_id: str, body: plan.PlanRequest):
    return fire_plan(request, fire_id, body)


def fire_view(store, weather, fire_id: str, pass_: int | None) -> tuple[fires.Live, fires.Fire, plan.FireView | None]:
    """The fire at a pass and what the planner needs of it; no view when there is no wind for that time."""
    live, fire, upto = find(store, fire_id, pass_)
    found = weather_routes.conditions_at(weather, fire.lon, fire.lat, live.passes[fire.country].starts[upto])
    return live, fire, None if found is None else _view(live, fire, upto, found[0], live.spread(fire, upto))


def plan_of(store, weather, land: landcover.LandCover | None, fire_id: str, body: plan.PlanRequest) -> dict:
    """The plan of a fire: the route and the assistant make it here, from the same data."""
    _, _, view = fire_view(store, weather, fire_id, body.pass_index)
    if view is None:
        raise ApiError(409, "plan_unavailable", "There is no wind data for this fire at the time of the pass")
    return plan.make_plan(view, body, land=None if land is None else land.read)


def fire_plan(request: Request, fire_id: str, body: plan.PlanRequest) -> dict:
    return plan_of(store_of(request), weather_routes.weather_of(request), land_of(request), fire_id, body)


@router.get("/api/calendar/fires", responses=ok(DayFires))
def day_fires(request: Request, date_: Annotated[date, Query(alias="date")],
              area: Annotated[str, Query(min_length=1, max_length=64)] = DEFAULT_AREA,
              limit: Annotated[int, Query(ge=1, le=MAX_DAY_FIRES)] = 200):
    store = store_of(request)
    chosen = areas.parse({"id": area}, store)
    first, last = month_start(store.first_month), store.last_complete_date
    if not first <= date_ <= last:
        raise ApiError(422, "validation_error", f"date: fires are there from {first} to {last}")
    found = fires.day_clusters(store, chosen, date_, date_)
    order = np.argsort(found.first_ms, kind="stable")
    number = np.empty(len(order), dtype=np.int64)
    number[order] = np.arange(1, len(order) + 1)
    top = np.argsort(-found.detections, kind="stable")[:limit]
    provinces, _ = fires.assign_regions(store, found.lon[top], found.lat[top])
    rows = [{"id": f"{date_:%Y%m%d}-{int(number[i])}", "lon": round(float(found.lon[i]), 3),
             "lat": round(float(found.lat[i]), 3), "first_detection_at": fires.iso(found.first_ms[i]),
             "detections": round(float(found.detections[i]), 1), "detections_raw": int(found.raw[i]),
             "sensor": "viirs" if found.viirs[i] else "modis", "frp_mw": round(found.frp[i]), "province": p,
             "timezone": fires.geometry_zone(shapely.Point(float(found.lon[i]), float(found.lat[i])))}
            for i, p in zip(top, provinces, strict=True)]
    return {"date": date_.isoformat(), "area": area, "total": len(found), "shown": len(rows),
            "coverage": {"first_day": first.isoformat(), "last_day": last.isoformat()}, "fires": rows,
            "attribution": CALENDAR_ATTRIBUTION}
