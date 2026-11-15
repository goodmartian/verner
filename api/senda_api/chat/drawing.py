"""Drawing on the map: the assistant names shapes, the server builds them.

The model gives plain shapes (a polygon, a line, a point, a circle) or refers to something we know: the footprint of a fire
(with a buffer, or as the planner expects it after 1, 3 or 6 hours), the border of a province, the way in, the ways out and
the safe ground of a plan. A reference is turned into plain shapes here, so the interface draws what it is given and works
out nothing. The plan is the planner's own (`plan.make_plan`), never a second calculation. A safe zone or a way out that the
model draws itself is checked against the fires near it, and what the check finds goes back to the model.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, polylabel

from .. import areas, fires, plan
from ..contracts import CircleShape, LineShape, PointShape, PolygonShape
from ..errors import ApiError
from ..fires_routes import fire_view
from ..store import Store
from ..weather import Weather

MAX_SHAPES = 20
MAX_VERTICES = 500
MAX_BUFFER_KM = 50.0
MAX_RADIUS_KM = 300.0
HOURS = (1, 3, 6)  # the fronts the planner works out
NEAR_DEG = 0.5  # fires farther than this from a shape do not matter to it
SMALL_PART = 0.02  # a part of a border smaller than this share of the biggest is left out
FIT_START_DEGREES = 0.0005
M_PER_DEG = 111_320.0
Rings = list[list[tuple[float, float]]]
Shape = PolygonShape | LineShape | PointShape | CircleShape
SHAPE = TypeAdapter(Shape)
PlanFor = Callable[[str], dict]
"""A fire id -> its plan: the one the assistant just made, or the default one."""


class Item(BaseModel):
    """One shape as the model writes it: its own geometry, or a reference to build one from."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: str
    label: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=300)
    rings: list[list[list[float]]] | None = None
    points: list[list[float]] | None = None
    position: list[float] | None = None
    center: list[float] | None = None
    radius_km: float | None = None
    role: str | None = None
    approach_from: list[float] | None = None
    source: str | None = Field(default=None, alias="from")
    buffer_km: float | None = None
    forecast_hours: int | None = None

    @property
    def name(self) -> str:
        """How a refusal calls the shape: the model gave it no id."""
        return self.label or self.kind


def _invalid(message: str) -> ApiError:
    return ApiError(422, "validation_error", message)


def _scaled(geom: BaseGeometry, lat: float, back: bool = False) -> BaseGeometry:
    """The geometry with longitude stretched to the length of latitude, so that distances in it are the same each way."""
    k = math.cos(math.radians(lat))
    return affinity.scale(geom, xfact=1 / k if back else k, yfact=1, origin=(0, 0))


def _buffer(geom: BaseGeometry, km: float, lat: float) -> BaseGeometry:
    return _scaled(_scaled(geom, lat).buffer(km * 1000 / M_PER_DEG), lat, back=True)


def _rings(polygon: Polygon) -> Rings:
    return [[(x, y) for x, y in ring.coords] for ring in (polygon.exterior, *polygon.interiors)]


def _polygons(geom: BaseGeometry) -> list[Rings]:
    """The polygons of a geometry, each as its rings."""
    parts = [geom] if isinstance(geom, Polygon) else list(getattr(geom, "geoms", []))
    return [_rings(p) for p in parts if isinstance(p, Polygon) and not p.is_empty]


def _geometry(polygons: list[list[list[float]]]) -> BaseGeometry:
    """Polygons given as `[[ring, hole, ...], ...]` of [longitude, latitude]."""
    return MultiPolygon([Polygon(p[0], p[1:]) for p in polygons if p]).buffer(0)


def fit(rings: Rings) -> Rings:
    """The polygon with fewer vertices when it has more than a shape may have."""
    if sum(len(r) for r in rings) <= MAX_VERTICES:
        return rings
    shape = Polygon(rings[0], rings[1:])
    tolerance = FIT_START_DEGREES
    while True:
        parts = _polygons(shape.simplify(tolerance, preserve_topology=True))
        if parts and sum(len(r) for r in parts[0]) <= MAX_VERTICES:
            return parts[0]
        tolerance *= 2


def _parts(item: Item, polygons: list[Rings], role: str = "area") -> list[dict[str, Any]]:
    """Plain polygon shapes, one for each part of a geometry."""
    if not polygons:
        raise _invalid(f"{item.name}: there is nothing to draw")
    return [{"kind": "polygon", "role": role, "label": item.label, "note": item.note, "rings": fit(rings)}
            for rings in polygons]


def _lines(item: Item, ways: list[list[list[float]]], role: str) -> list[dict[str, Any]]:
    return [{"kind": "line", "role": role, "label": item.label, "note": item.note, "points": [tuple(p) for p in way]}
            for way in ways if len(way) >= 2]


def _scar(live: fires.Live, fire: fires.Fire, upto: int) -> BaseGeometry:
    """The footprint of a fire: its outline, one polygon, the one the planner and the fire card work with."""
    outline = live.detail(fire, upto)["outline"]
    if not outline:
        raise _invalid(f"fire {fire.id} has no footprint")
    return _geometry([[outline]])


def _fire(store: Store, weather: Callable[[], Weather | None], item: Item, fire_id: str) -> list[dict[str, Any]]:
    live, fire, view = fire_view(store, weather(), fire_id, None)
    upto = int(live.pass_of[fire.idx].max())
    footprint = _scar(live, fire, upto)
    if item.approach_from is not None:
        if item.buffer_km is not None or item.forecast_hours is not None:
            raise _invalid(f"{item.name}: `approach_from` goes without a buffer or hours")
        if len(item.approach_from) != 2:
            raise _invalid(f"{item.name}: approach_from is [longitude, latitude]")
        start = tuple(item.approach_from)
        edge = nearest_points(_scaled(Point(start), fire.lat), _scaled(footprint, fire.lat))[1]
        end = _scaled(edge, fire.lat, back=True)
        return _lines(item, [[list(start), [end.x, end.y]]], "approach")
    if item.buffer_km is not None and item.forecast_hours is not None:
        raise _invalid(f"{item.name}: give `buffer_km` or `forecast_hours`, not both")
    if item.forecast_hours is not None:
        if item.forecast_hours not in HOURS:
            raise _invalid(f"{item.name}: forecast_hours is 1, 3 or 6")
        front = next((c for c in plan.contours(view) if c["hours"] == item.forecast_hours), None) if view else None
        if front is None:
            raise _invalid(f"{item.name}: there is no wind or no measured speed for fire {fire_id}: no forecast")
        return _parts(item, _polygons(_geometry(front["polygons"])))
    if item.buffer_km is not None:
        if not 0 < item.buffer_km <= MAX_BUFFER_KM:
            raise _invalid(f"{item.name}: buffer_km from 0 to {MAX_BUFFER_KM:g}")
        footprint = _buffer(footprint, item.buffer_km, fire.lat)
    return _parts(item, _polygons(footprint))


def _area(store: Store, item: Item, code: str) -> list[dict[str, Any]]:
    region = store.regions.by_id.get(code)
    if region is None or code == areas.WORLD_ID:
        raise _invalid(f"{item.name}: no area {code}")
    parts = sorted(_polygons(region.geometry), key=lambda rings: -Polygon(rings[0]).area)
    # the islands of a border are not worth a shape each: the big parts only
    biggest = Polygon(parts[0][0]).area
    return _parts(item, [r for r in parts if Polygon(r[0]).area >= biggest * SMALL_PART][:MAX_SHAPES])


def _of_plan(item: Item, fire_id: str, scheme: str, plan_for: PlanFor) -> list[dict[str, Any]]:
    try:
        made = plan_for(fire_id)
    except ApiError as error:
        raise _invalid(f"{item.name}: there is no plan for fire {fire_id} ({error.message}); build it first "
                       "(make_plan) or draw the way yourself") from None
    if scheme == "safe_zones":
        # an outline of the planner may cross itself: only what has an area is drawn, each part by itself
        parts = [rings for ring in made["safe_zones"] if len(ring) >= 3 for rings in _polygons(Polygon(ring).buffer(0))]
        if not parts:
            why = ("its safe zone outlines have no area to draw" if made["safe_zones"]
                   else "it has no burned ground to retreat to, so no safe zone")
            raise _invalid(f"{item.name}: the plan of fire {fire_id}: {why}")
        found = _parts(item, parts, "safe_zone")
        info = [{"safe_zone": n + 1} for n in range(len(found))]
    else:
        key = "route" if scheme == "route" else "escape"
        crews = [c for c in made["crews"] if len(c[key]) >= 2]
        found = _lines(item, [c[key] for c in crews], "path" if scheme == "route" else "escape")
        if not found:
            raise _invalid(f"{item.name}: the plan of fire {fire_id} has no way to draw")
        # the figures of what is drawn, for the model to quote
        info = [{"crew": c["number"], **({"trail_km": round(c["length_m"] / 1000, 2), "trail_min": c["walk_min"]}
                                         if scheme == "route" else {"way_out_km": round(c["safe_distance_m"] / 1000, 2)})}
                for c in crews]
    return [{**shape, "_plan": True, "_info": i} for shape, i in zip(found, info, strict=True)]


def _reference(store: Store, weather: Callable[[], Weather | None], plan_for: PlanFor, item: Item) -> list[dict[str, Any]]:
    scheme, _, value = (item.source or "").partition(":")
    if not value:
        raise _invalid(f"{item.name}: `from` is `fire:<id>`, `area:<code>`, `route:<fire_id>`, "
                       "`escape:<fire_id>` or `safe_zones:<fire_id>`")
    if scheme != "fire" and (item.buffer_km is not None or item.forecast_hours is not None
                             or item.approach_from is not None):
        raise _invalid(f"{item.name}: `buffer_km`, `forecast_hours` and `approach_from` go with `fire:` only")
    if scheme == "fire":
        return _fire(store, weather, item, value)
    if scheme == "area":
        return _area(store, item, value)
    if scheme in ("route", "escape", "safe_zones"):
        return _of_plan(item, value, scheme, plan_for)
    raise _invalid(f"{item.name}: `from` {item.source} names nothing (use fire:, area:, route:, escape: or safe_zones:)")


def _coordinates(item: Item, points: list[list[float]]) -> None:
    for p in points:
        if len(p) != 2 or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90):
            raise _invalid(f"{item.name}: a point is [longitude, latitude], longitude within 180 and latitude within 90")


def _plain(item: Item) -> dict[str, Any]:
    """The shape the model wrote itself, with only the fields of its kind."""
    fields = {"polygon": ("rings",), "line": ("points",), "point": ("position",), "circle": ("center", "radius_km")}.get(item.kind)
    if fields is None:
        raise _invalid(f"{item.name}: kind is polygon, line, point, circle or reference")
    shape: dict[str, Any] = {"kind": item.kind, "label": item.label, "note": item.note}
    if item.kind in ("polygon", "circle", "line"):
        shape["role"] = item.role or ("line" if item.kind == "line" else "area")
    for name in fields:
        value = getattr(item, name)
        if value is None:
            raise _invalid(f"{item.name}: a {item.kind} needs `{name}`")
        shape[name] = value
    if item.kind == "polygon":
        for ring in item.rings or []:
            _coordinates(item, ring)
        if not item.rings or any(len(r) < 3 for r in item.rings):
            raise _invalid(f"{item.name}: a polygon ring has at least 3 points")
        shape["rings"] = fit([[(p[0], p[1]) for p in (r if r[0] == r[-1] else [*r, r[0]])] for r in item.rings])
    elif item.kind == "line":
        _coordinates(item, item.points or [])
        if len(item.points or []) < 2 or len(item.points or []) > MAX_VERTICES:
            raise _invalid(f"{item.name}: a line has 2 to {MAX_VERTICES} points")
    elif item.kind == "circle":
        _coordinates(item, [item.center or []])
        if not 0.1 <= (item.radius_km or 0) <= MAX_RADIUS_KM:
            raise _invalid(f"{item.name}: radius_km from 0.1 to {MAX_RADIUS_KM:g}")
    else:
        _coordinates(item, [item.position or []])
    return shape


def _label_at(shape: Shape) -> tuple[float, float]:
    """Where the caption of a shape goes."""
    if isinstance(shape, PointShape):
        return shape.position
    if isinstance(shape, CircleShape):
        return shape.center
    if isinstance(shape, LineShape):
        middle = LineString(shape.points).interpolate(0.5, normalized=True)
        return (middle.x, middle.y)
    parts = _polygons(Polygon(shape.rings[0], shape.rings[1:]).buffer(0))
    if not parts:
        raise _invalid(f"{shape.label or 'polygon'}: the polygon has no area (its sides cross each other or it is flat)")
    polygon = max((Polygon(r[0], r[1:]) for r in parts), key=lambda p: p.area)
    pole = polylabel(polygon, tolerance=1e-4)
    return (pole.x, pole.y)


def _checked(raw: dict[str, Any]) -> Shape:
    """The shape as the interface gets it: checked against the contract, with its caption placed."""
    try:
        shape = SHAPE.validate_python({**raw, "label_at": (0.0, 0.0)})
    except ValidationError as error:
        first = error.errors()[0]
        raise _invalid(f"{raw.get('label') or raw['kind']}: {'.'.join(str(p) for p in first['loc'][1:])}: {first['msg']}") from None
    return shape.model_copy(update={"label_at": _label_at(shape)})


@dataclass(frozen=True)
class Built:
    shapes: list[Shape]
    from_plan: set[str]
    """Names of the shapes that come from a plan: burned ground the planner counts safe, its ways."""
    info: dict[str, dict[str, Any]]
    """The figures of the shapes of a plan, by name."""


def build(store: Store, weather: Callable[[], Weather | None], plan_for: PlanFor, raw_items: list[Any],
          first_number: int, left: int) -> Built:
    """The plain shapes of the items the model gave, named by the server (`A<first_number>` on); every refusal says what
    to change."""
    items = []
    for raw in raw_items:
        try:
            items.append(Item.model_validate(raw))
        except ValidationError as error:
            first = error.errors()[0]
            raise _invalid(f"shapes.{'.'.join(str(p) for p in first['loc'])}: {first['msg']}") from None
    raws: list[dict[str, Any]] = []
    for item in items:
        raws.extend(_reference(store, weather, plan_for, item) if item.kind == "reference" else [_plain(item)])
    if len(raws) > left:
        raise _invalid(f"at most {MAX_SHAPES} shapes in an answer: {left} left, this call makes {len(raws)}")
    shapes = [_checked({**{k: v for k, v in raw.items() if not k.startswith("_")}, "id": f"A{first_number + n}"})
              for n, raw in enumerate(raws)]
    made = [(s.id, raw) for s, raw in zip(shapes, raws, strict=True) if raw.get("_plan")]
    return Built(shapes, {name for name, _ in made}, {name: raw["_info"] for name, raw in made})


# --- the safe zones and ways out against the fires near them ---


def _geometry_of(shape: Shape) -> BaseGeometry:
    if isinstance(shape, PolygonShape):
        return Polygon(shape.rings[0], shape.rings[1:]).buffer(0)
    if isinstance(shape, LineShape):
        return LineString(shape.points)
    if isinstance(shape, CircleShape):
        return _buffer(Point(shape.center), shape.radius_km, shape.center[1])
    return Point(shape.position)


def _near(store: Store, geom: BaseGeometry) -> list[fires.Fire]:
    live = fires.live_of(store)
    west, south, east, north = geom.bounds
    return [f for f in live.fires if f.country in live.passes
            and west - NEAR_DEG <= f.lon <= east + NEAR_DEG and south - NEAR_DEG <= f.lat <= north + NEAR_DEG]


def _ground(store: Store, weather: Callable[[], Weather | None], fire: fires.Fire) -> tuple[BaseGeometry, BaseGeometry | None]:
    """What a fire covers at its last pass, and what it is expected to cover within the hour (with what it covers now)."""
    live, _, view = fire_view(store, weather(), fire.id, None)
    now = _scar(live, fire, int(live.pass_of[fire.idx].max()))
    front = next((c for c in plan.contours(view) if c["hours"] == 1), None) if view else None
    return now, None if front is None else _geometry(front["polygons"])


def warnings_for(store: Store, weather: Callable[[], Weather | None], shapes: list[Shape], from_plan: set[str]) -> list[str]:
    """What to tell the person about the safe zones and ways out among the shapes. The zones of a plan (`from_plan`, by
    name) are burned ground the planner counts safe: they lie on the fire's footprint by design and are not warned about."""
    warnings: list[str] = []
    for shape in shapes:
        zone = isinstance(shape, PolygonShape | CircleShape) and shape.role == "safe_zone"
        way = isinstance(shape, LineShape) and shape.role == "escape"
        if shape.id in from_plan or not (zone or way):
            continue
        geom = _geometry_of(shape)
        name = f"{shape.id} ({shape.label})" if shape.label else shape.id
        for fire in _near(store, geom):
            now, hour = _ground(store, weather, fire)
            if zone and geom.intersects(now):
                warnings.append(f"WARNING: the safe zone {name}: it lies on fire {fire.id} now. Say so plainly.")
            elif zone and hour is not None and geom.intersects(hour):
                warnings.append(f"WARNING: the safe zone {name}: fire {fire.id} is expected to reach it within an hour. Say so plainly.")
            elif way and hour is not None and geom.intersects(hour.difference(now)):
                warnings.append(f"WARNING: the way out {name} crosses ground fire {fire.id} is expected to reach within an hour. Say so plainly.")
    return warnings
