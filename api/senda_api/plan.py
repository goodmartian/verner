"""Work plan for crews at a fire: where they enter, how they walk, where they escape, and what is wrong with it.

Crews enter at the heel of the fire (against the wind), walk a foot trail over land cover to the hot spots (round water,
fire of the last two passes and the ground the front will cross during the work), escape onto ground that burned out at
least two passes ago and leave before the forecast front arrives. The operator may add entry and hot-spot marks, a work
area and overrides of the blocks the planner would otherwise put on a crew.

It works from the data of this API: the measured speed of the front, the GFS wind at the time of
the pass and the detections. Without land cover (no network, open sea) every way is a straight line and the plan says
so (`straight_line_only`). Pure numpy/shapely; the caller supplies a `FireView` and the land cover, and gets plain JSON
types back, so the planner is as easy to call from the assistant as from a route.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import shapely
from pydantic import BaseModel, ConfigDict, Field
from scipy.spatial import cKDTree
from shapely.geometry import MultiPoint, Point, Polygon

from senda_api import landcover
from senda_api.blob import blob_of
from senda_api.errors import ApiError
from senda_api.trail import Frame, Grid, Trail, find_trail

M_PER_DEG = 111_320.0
PIXEL_M = 375.0  # VIIRS pixel size: every detection stands for a disc of half of it, widened to an outline
RING_STEP_M = 120.0  # the outline is walked in steps of this length
HEEL_OFFSET_M = 250.0  # entry: this far outside the outline at its windward vertex
FLANK_OFFSET_M = 150.0  # flank path: this far outside the outline
FLANK_LIMIT_M = 3000.0  # a flank is shown up to this length
HEAD_HALF_ANGLE = math.radians(55)  # the head sector, around the direction of the wind
ZONE_SEARCH_M = 3000.0  # burned ground farther than this from the work point is not a retreat
ACTIVE_CLEARANCE_M = 300.0  # safe ground is at least this far from fire of the last two passes
ZONE_BACK_M = 300.0  # without burned ground: a point this far behind the entry, against the wind
BURNED_OUT_CLEARANCE_M = 400.0  # a safety zone outline takes burned ground at least this far from live fire
ZONE_RADIUS_M = 650.0  # ... within this distance of the safe point
DEDUP_ZONE_M = 400.0  # safe points closer than this make one zone
WINDY_KMH = 30.0  # wind of this speed or more blocks crews until the operator overrules it
MARK_RADIUS_M = 25_000.0  # operator marks farther than this from the fire are ignored
HOT_SPACING_M = 1500.0  # hot spots the planner picks are at least this far apart
HOT_WORK_OFFSET_M = 150.0  # work point: this far from the hot spot, against the wind
STEP_H = 0.25  # the front is tested every quarter of an hour
LIMIT_H = 8.0  # and up to this many hours
MIN_GAP_H, MAX_GAP_H = 1.0, 24.0
STALE_H = 6.0  # a plan at a pass this many hours before the latest common pass is flagged `stale`
LEVELS = {"block": 0, "risk": 1, "info": 2}

Wind = Callable[[float], tuple[float, float]]
"""Hours after the pass -> (speed km/h, direction the wind blows from, degrees)."""
LandSource = Callable[[tuple[float, float, float, float]], dict]
"""Box (west, south, east, north) -> land cover grid, raising `landcover.LandError` when there is none."""


class PlanMark(BaseModel):
    kind: Literal["entry", "hot"] = Field(description="`entry`: a place a crew may enter; `hot`: a place to work at.")
    position: tuple[float, float]


class PlanRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    pass_index: int | None = Field(default=None, alias="pass", ge=0, description="Pass to plan at; default: the last.")
    crews: int = Field(default=2, ge=1, le=20)
    hours: Literal[1, 3, 6] = Field(default=3, description="Length of the work window, hours.")
    marks: list[PlanMark] = Field(default_factory=list, max_length=50)
    area: list[tuple[float, float]] | None = Field(
        default=None, min_length=3, max_length=200, description="Work area: the planner takes hot spots from inside it."
    )
    overrides: list[str] = Field(
        default_factory=list, max_length=50, description="Keys of blocks the operator overrules, as in `issues[].key`."
    )


@dataclass
class FireView:
    """What the planner needs of a fire at one pass."""

    fire_id: str
    pass_index: int
    latest_pass: int
    pass_time: str
    lon: np.ndarray
    lat: np.ndarray
    pass_of: np.ndarray
    """Detections up to `pass_index`, and the pass of each."""
    rate_m_per_h: float | None
    """Speed of the head measured between the last two passes; None when it could not be measured."""
    wind: Wind
    place: dict[str, Any] | None = None
    source: str = "live"
    area_ha: float | None = None
    """Burn-scar area at this pass by cells, the figure of the fire card; the outline's own area is used when None."""
    hours_behind: float = 0.0
    """Hours between this pass and the latest common pass."""
    attribution: str | None = None
    frp: np.ndarray | None = None
    """Fire radiative power of each detection, MW; the planner sends crews to the strongest ones."""


def unavailable() -> ApiError:
    return ApiError(
        409,
        "plan_unavailable",
        f"A plan needs two satellite passes {MIN_GAP_H:g} to {MAX_GAP_H:g} hours apart in which the fire's edge moved; "
        "this fire has no such pair at this pass.",
    )


def length_to_breadth(wind_kmh: float) -> float:
    """Anderson (1983) ellipse of a fire in wind, speed in mph, capped at 8: 1 without wind."""
    mph = wind_kmh * 0.621371
    return min(8.0, max(1.0, 0.936 * math.exp(0.2566 * mph) + 0.461 * math.exp(-0.1548 * mph) - 0.397))


def _unit(from_deg: float) -> np.ndarray:
    """(east, north) unit vector of where the wind blows to."""
    a = math.radians(from_deg + 180)
    return np.array([math.sin(a), math.cos(a)])


def _mean_wind(wind: Wind, hours: float) -> tuple[float, float]:
    vec = np.mean([wind(t)[0] * _unit(wind(t)[1]) for t in (0.0, hours / 2, hours)], axis=0)
    return float(np.hypot(*vec)), float((math.degrees(math.atan2(vec[0], vec[1])) + 180) % 360)


def bearing(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dx, dy)) % 360


def compass(degrees: float) -> int:
    return round(degrees / 45) % 8


def _densify(ring: np.ndarray, step: float) -> np.ndarray:
    """Points along a closed ring, at most `step` apart."""
    out = []
    for a, b in zip(ring, np.roll(ring, -1, axis=0), strict=True):
        n = max(1, math.ceil(float(np.hypot(*(b - a))) / step))
        out.extend(a + (b - a) * k / n for k in range(n))
    return np.array(out)


class _Model:
    """The fire in metres around the centre of its outline, its ground and its front at any hour."""

    def __init__(self, v: FireView):
        if v.rate_m_per_h is None or v.rate_m_per_h <= 0 or len(v.lon) == 0:
            raise unavailable()
        self.v = v
        self.lon0, self.lat0 = float(v.lon.mean()), float(v.lat.mean())
        self.kx = M_PER_DEG * math.cos(math.radians(self.lat0))
        xy = self.xy(v.lon, v.lat)
        hull = MultiPoint(xy.tolist()).buffer(PIXEL_M / 2).convex_hull
        centre = np.array(hull.centroid.coords[0])
        self.shift = centre
        self.frame = Frame(self.lon0, self.lat0, self.kx, M_PER_DEG, (float(centre[0]), float(centre[1])))
        self.hull: Polygon = Polygon(np.asarray(hull.exterior.coords) - centre)
        self.corners = np.asarray(self.hull.exterior.coords)[:-1]
        self.ring = _densify(self.corners, RING_STEP_M)
        old = v.pass_of <= v.pass_index - 2
        self.burned = self.xy(v.lon[old], v.lat[old]) - centre
        self.burned_ll = np.column_stack([v.lon[old], v.lat[old]])
        act = v.pass_of >= v.pass_index - 1
        self.active = self.xy(v.lon[act], v.lat[act]) - centre
        self.from_active = (
            cKDTree(self.active).query(self.burned)[0] if len(self.active) and len(self.burned)
            else np.full(len(self.burned), np.inf)
        )
        self._fronts: dict[int, Polygon] = {}
        self.base_ha = v.area_ha if v.area_ha is not None else self.hull.area / 10_000

    def xy(self, lon: Any, lat: Any) -> np.ndarray:
        return np.column_stack([(np.asarray(lon) - self.lon0) * self.kx, (np.asarray(lat) - self.lat0) * M_PER_DEG])

    def ll(self, p: np.ndarray) -> list[float]:
        q = np.asarray(p) + self.shift
        return [round(self.lon0 + q[0] / self.kx, 5), round(self.lat0 + q[1] / M_PER_DEG, 5)]

    def lls(self, line: Any) -> list[list[float]]:
        return [self.ll(p) for p in line]

    def front(self, step: int) -> Polygon:
        """The outline widened by the ellipse of the fire after `step` quarter-hours."""
        if step not in self._fronts:
            hours = step * STEP_H
            speed, from_deg = _mean_wind(self.v.wind, hours)
            lb = length_to_breadth(speed)
            e = math.sqrt(1 - 1 / lb**2)
            head = self.v.rate_m_per_h * hours
            back = head * (1 - e) / (1 + e)
            a, c = (head + back) / 2, (head - back) / 2
            t = np.linspace(0, 2 * math.pi, 48, endpoint=False)
            u, w = c + a * np.cos(t), a / lb * np.sin(t)
            d = _unit(from_deg)
            ell = np.column_stack([u * d[0] - w * d[1], u * d[1] + w * d[0]])
            pts = (self.corners[:, None, :] + ell[None, :, :]).reshape(-1, 2)
            self._fronts[step] = shapely.convex_hull(shapely.multipoints(pts))
        return self._fronts[step]

    def reach_h(self, geom: Any, limit: float = LIMIT_H) -> float | None:
        """First time the front covers the geometry (point, or touches a line); None inside the fire or beyond limit."""
        if self.hull.intersects(geom):
            return None
        for step in range(1, int(limit / STEP_H) + 1):
            if self.front(step).intersects(geom):
                return step * STEP_H
        return None

    def nearest_burned(self, q: np.ndarray, clear: bool = True) -> tuple[np.ndarray, int] | None:
        """The ground that burned out two passes ago nearest to `q` within 3 km (and clear of live fire), with its index."""
        if not len(self.burned):
            return None
        d = np.hypot(*(self.burned - q).T)
        if clear:
            d = np.where(self.from_active >= ACTIVE_CLEARANCE_M, d, np.inf)
        i = int(d.argmin())
        return (self.burned[i], i) if d[i] < ZONE_SEARCH_M else None


def _contour(m: _Model, hours: int) -> dict[str, Any]:
    poly = m.front(int(hours / STEP_H))
    return {
        "hours": hours,
        "polygons": [[m.lls(poly.exterior.coords)]],
        "area_ha": round(m.base_ha + (poly.area - m.hull.area) / 10_000, 1),
    }


def contours(v: FireView, horizons: tuple[int, ...] = (1, 3, 6)) -> list[dict[str, Any]]:
    """The front after 1, 3 and 6 hours (also for the fire card); empty when the speed is not known."""
    try:
        m = _Model(v)
    except ApiError:
        return []
    return [_contour(m, h) for h in horizons]


def _is_head(q: np.ndarray, toward: np.ndarray) -> bool:
    return float(q @ toward) / (float(np.hypot(*q)) or 1.0) > math.cos(HEAD_HALF_ANGLE)


def _flanks(ring: np.ndarray, toward: np.ndarray) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Entry at the heel and the two flank paths from it up to the head sector, left one first."""
    n, heel = len(ring), int(np.argmin(ring @ toward))
    entry = ring[heel] - toward * HEEL_OFFSET_M
    flanks = []
    for direction in (1, -1):
        line, j, length = [entry], heel, 0.0
        for _ in range(n - 1):
            if length >= FLANK_LIMIT_M:
                break
            j = (j + direction) % n
            q = ring[j]
            if _is_head(q, toward):
                break
            p = q + q / (float(np.hypot(*q)) or 1.0) * FLANK_OFFSET_M
            length += float(np.hypot(*(p - line[-1])))
            line.append(p)
        mid = line[len(line) // 2]
        side_value = toward[0] * (mid[1] - entry[1]) - toward[1] * (mid[0] - entry[0])
        flanks.append({"line": np.array(line), "length": length, "value": side_value})
    flanks.sort(key=lambda f: -f["value"])
    for side, f in enumerate(flanks):
        f["side"] = side
    return entry, flanks


def _length(line: np.ndarray | list) -> float:
    pts = np.asarray(line)
    return float(np.hypot(*np.diff(pts, axis=0).T).sum()) if len(pts) > 1 else 0.0


def _walk_min(length_m: float, walk_kmh: float = 4.0) -> int:
    return max(5, math.floor(length_m / (walk_kmh * 1000 / 60) / 5 + 0.5) * 5)


def _distinct(zones: list[np.ndarray]) -> list[np.ndarray]:
    """A zone is dropped when an earlier one in the list lies within 400 m of it."""
    out: list[np.ndarray] = []
    for z in zones:
        if all(float(np.hypot(*(z - y))) >= DEDUP_ZONE_M for y in out):
            out.append(z)
    return out


def _safety_zones(m: _Model, zones: list[np.ndarray]) -> list[list[list[float]]]:
    """Outlines of the burned ground around each safe point, [longitude, latitude]. Only ground that really burned
    out counts: older detections with no fire of the last two passes within 400 m."""
    out = []
    burned_out = m.from_active > BURNED_OUT_CLEARANCE_M
    for zone in _distinct(zones):
        close = burned_out & (np.hypot(*(m.burned - zone).T) < ZONE_RADIUS_M)
        corners = [
            (lon + dx, lat + dy)
            for lon, lat in m.burned_ll[close].tolist()
            for dx in (-0.0019, 0.0019)
            for dy in (-0.0017, 0.0017)
        ]
        polygons = blob_of(corners, 0.0012, 0.0011) if corners else None
        if not polygons:
            continue
        here = Point(m.ll(zone))
        chosen = next((p for p in polygons if Polygon(p[0]).contains(here)), None) or max(polygons, key=lambda p: len(p[0]))
        out.append([[round(x, 5), round(y, 5)] for x, y in chosen[0]])
    return out


def _grid_of(land: LandSource | None, m: _Model, marks: list[PlanMark]) -> dict | None:
    """The land cover under the fire and the marks; None when it cannot be read (the plan then goes in straight lines)."""
    if land is None:
        return None
    ring = [(p[0], p[1]) for p in (m.ll(q) for q in m.ring)] + [mark.position for mark in marks]
    try:
        return land(landcover.snapped_box(ring))
    except landcover.LandError:
        return None


def make_plan(v: FireView, req: PlanRequest, land: LandSource | None = None) -> dict[str, Any]:
    """The plan of `req.crews` crews for `req.hours` hours at the pass of `v`; `land` reads land cover of a box."""
    m = _Model(v)
    hours = req.hours
    overrides = set(req.overrides)
    speed0, from0 = v.wind(0.0)
    toward = _unit(_mean_wind(v.wind, hours)[1])
    entry, flanks = _flanks(m.ring, toward)
    back = entry - toward * ZONE_BACK_M
    for f in flanks:
        f["end"] = f["line"][-1]
        f["reach"] = m.reach_h(Point(f["end"]))
        found = m.nearest_burned(f["end"])
        f["zone"], f["burned"] = (found[0], True) if found else (back, False)
    issues: list[dict[str, Any]] = []

    def issue(level: str, kind: str, **extra: Any) -> dict[str, Any]:
        issues.append({"level": level, "kind": kind, **extra})
        return issues[-1]

    grid_dict = _grid_of(land, m, req.marks)
    grid = Grid.of(grid_dict) if grid_dict else None
    if grid is None:
        issue("info", "noland")
    forecast = m.front(int(hours / STEP_H))

    def inside(q: np.ndarray) -> bool:
        return bool(m.hull.covers(Point(q)))

    def threat(q: np.ndarray) -> float | None:
        return None if inside(q) else m.reach_h(Point(q))

    area = None
    if req.area:
        area = Polygon(m.xy([p[0] for p in req.area], [p[1] for p in req.area]) - m.shift)
        if not area.is_valid:
            raise ApiError(400, "invalid_area", "The work area crosses itself.")
    near: dict[str, list[tuple[int, np.ndarray, tuple[float, float]]]] = {"entry": [], "hot": []}
    counts = {"entry": 0, "hot": 0}
    outside = 0
    for mark in req.marks:
        counts[mark.kind] += 1
        p = (m.xy(mark.position[0], mark.position[1]) - m.shift)[0]
        if Point(p).distance(m.hull) > MARK_RADIUS_M:
            outside += 1
        else:
            near[mark.kind].append((counts[mark.kind], p, mark.position))

    entries: list[tuple[np.ndarray, str, int | None, bool]] = []  # position, source, mark number, forced
    rejected: list[dict[str, Any]] = []
    for n, p, position in near["entry"]:
        reached = threat(p)
        bad = "in" if inside(p) else ("fc" if reached is not None and reached <= hours else None)
        if bad is None:
            entries.append((p, "op", n, False))
            continue
        forced = f"e{n}" in overrides
        issue("block", bad, mark=n, hours=reached, key=f"e{n}", forced=forced)
        if forced:
            entries.append((p, "op", n, True))
        else:
            rejected.append({"mark": n, "position": list(position)})

    hots: list[dict[str, Any]] = [{"n": n, "point": p, "ai": False, "frp": None} for n, p, _ in near["hot"]]
    if not hots:
        frp = v.frp if v.frp is not None else np.zeros(len(v.lon))
        in_pass = np.flatnonzero(v.pass_of == v.pass_of.max())
        pool = in_pass
        if req.area:
            pool = in_pass[np.asarray(shapely.contains_xy(Polygon(req.area), v.lon[in_pass], v.lat[in_pass]))]
        chosen = pool if len(pool) else in_pass
        for j in chosen[np.argsort(-frp[chosen], kind="stable")]:
            if len(hots) >= req.crews:
                break
            q = (m.xy(v.lon[j], v.lat[j]) - m.shift)[0]
            if all(float(np.hypot(*(h["point"] - q))) > HOT_SPACING_M for h in hots):
                hots.append({"n": len(hots) + 1, "point": q, "ai": True, "frp": round(float(frp[j]), 1)})
    offered = [
        p
        for p in (q + q / (float(np.hypot(*q)) or 1.0) * HEEL_OFFSET_M for q in m.ring)
        if not _is_head(p, toward) and not inside(p) and (threat(p) is None or threat(p) > hours)
    ]

    def ai_entry(q: np.ndarray) -> np.ndarray:
        return min(offered, key=lambda e: float(np.hypot(*(e - q)))) if offered else entry

    winds = [v.wind(float(t)) for t in range(hours + 1)]
    top = max(w[0] for w in winds)
    windy = top >= WINDY_KMH
    if windy:
        issue("block", "wind", speed_kmh=round(top, 1), key="wind", forced="wind" in overrides)
    if v.hours_behind >= STALE_H:
        issue("info", "stale", count=v.latest_pass - v.pass_index, hours=round(v.hours_behind, 1))

    crews = []
    for k in range(1, req.crews + 1):
        start, source, mark_no, forced = entries[(k - 1) % len(entries)] if entries else (entry, "planner", None, False)
        hot = hots[(k - 1) % len(hots)]
        work = hot["point"] - toward * HOT_WORK_OFFSET_M
        if not entries:
            start = ai_entry(work)
        trail: Trail | None = None
        if grid is not None:
            trail = find_trail(grid, m.frame, tuple(start), tuple(work), hull=m.hull, forecast=forecast, active=m.active)
        route = np.array(trail.points) if trail else np.array([start, work])
        found = m.nearest_burned(work)
        zone, burned = (found[0], True) if found else (start, False)
        length = _length(route)
        walk = trail.walk_min if trail else _walk_min(length)
        in_work = inside(work)
        reach = None if in_work else threat(work)
        escape = np.array([work, zone]) if burned else route[::-1]
        route_ll = m.lls(route)
        blocks: list[dict[str, Any]] = []
        if grid is not None and trail is None:
            blocks.append({"level": "block", "kind": "nopath", "crew": k, "hot_spot": hot["n"], "key": f"p{k}"})
        if reach is not None and reach * 60 < walk:
            blocks.append({"level": "block", "kind": "head", "crew": k, "hot_spot": hot["n"], "until_min": round(reach * 60),
                           "walk_min": walk, "key": f"h{k}"})
        for b in blocks:
            b["forced"] = b["key"] in overrides
            issues.append(b)
        held = [b["kind"] for b in blocks if not b["forced"]]
        if windy and "wind" not in overrides:
            held.append("wind")
        long_walk = walk > hours * 60
        if long_walk:
            issue("risk", "long", crew=k, walk_min=walk)
        zone_distance = length if not burned else float(np.hypot(*(zone - work)))
        if not burned:
            issue("risk", "nozone", crew=k, distance_m=round(zone_distance))
        soonest = None
        for a, z in itertools.pairwise(escape):
            for s in range(9):
                r = threat(a + (z - a) * s / 8)
                if r is not None and r <= hours and (soonest is None or r < soonest):
                    soonest = r
        if soonest is not None:
            issue("risk", "escfire", crew=k, hours=soonest)
        crews.append(
            {
                "number": k,
                "side": None,
                "target": {"kind": "hot", "hot_spot": hot["n"], "chosen_by_planner": hot["ai"]},
                "entry": m.ll(start),
                "entry_source": source,
                "entry_mark": mark_no,
                "entry_forced": forced,
                "hot_mark": None if hot["ai"] else hot["n"],
                "work_point": m.ll(work),
                "route": route_ll,
                "on_trail": trail is not None,
                "crosses_wet_ground": bool(trail and trail.wet),
                "length_m": round(length),
                "walk_min": walk,
                "long_walk": long_walk,
                "land": landcover.along(grid_dict, route_ll) if grid_dict and len(route_ll) > 1 else None,
                "leave_in_h": reach,
                "distance_to_active_m": (
                    round(float(np.hypot(*(m.active - work).T).min())) if in_work and len(m.active) else None
                ),
                "escape": m.lls(escape),
                "safe_point": m.ll(zone),
                "safe_distance_m": round(zone_distance),
                "safe_on_burned_ground": burned,
                "escape_threatened_in_h": soonest,
                "held": held,
                "status": "block" if held else ("forced" if blocks or windy or forced else "ok"),
                "_zone": zone,
            }
        )
    if hots and req.crews > len(hots):
        issue("info", "share", crews=req.crews, hot_spots=len(hots))
    if outside:
        issue("info", "outside", count=outside)
    issues.sort(key=lambda i: (LEVELS[i["level"]], i.get("crew") or 0, i.get("mark") or 0))
    safe_points = [c.pop("_zone") for c in crews]
    zones = _safety_zones(m, [z for z, c in zip(safe_points, crews, strict=True) if c["status"] != "block" and c["safe_on_burned_ground"]])
    leave = [c["leave_in_h"] for c in crews if c["leave_in_h"] is not None]
    dist = [round(c["safe_distance_m"] / 50) * 50 for c in crews]
    window = m.front(int(hours / STEP_H))
    by_side = {f["side"]: f for f in flanks}
    near_zone = min(flanks, key=lambda f: float(np.hypot(*(f["zone"] - entry))))
    return {
        "source": v.source,
        "fire_id": v.fire_id,
        "pass_index": v.pass_index,
        "pass_time": v.pass_time,
        "hours": hours,
        "wind": {"speed_kmh": round(speed0, 1), "from_deg": round(from0), "at": v.pass_time},
        "contours": [_contour(m, h) for h in (1, 3, 6)],
        "entry": {"position": m.ll(entry), "from_direction": compass(bearing(*entry))},
        "flanks": [
            {"side": s, "line": m.lls(by_side[s]["line"]), "length_m": round(by_side[s]["length"]), "reach_h": by_side[s]["reach"]}
            for s in (0, 1)
        ],
        "safe_zone": {
            "position": m.ll(near_zone["zone"]),
            "distance_m": round(float(np.hypot(*(near_zone["zone"] - entry)))),
            "on_burned_ground": near_zone["burned"],
        },
        "safe_zones": zones,
        "crews": crews,
        "hot_spots": [{"number": h["n"], "position": m.ll(h["point"]), "chosen_by_planner": h["ai"], "frp_mw": h["frp"]} for h in hots],
        "hot_marks": [{"number": n, "position": m.ll(p)} for n, p, _ in near["hot"]],
        "rejected_entries": rejected,
        "issues": issues,
        "report": {
            "area_ha": round(m.base_ha),
            "detections_last_pass": int((v.pass_of == v.pass_index).sum()),
            "last_pass": int(v.pass_of.max()),
            "spread_km_per_h": round(v.rate_m_per_h / 1000, 2),
            "growth_ha": round((window.area - m.hull.area) / 10_000),
            "hot_spots": sorted({c["target"]["hot_spot"] for c in crews}),
            "leave_in_h": min(leave) if leave else None,
            "safe_min_m": max(50, min(dist)),
            "safe_max_m": max(50, *dist),
            "all_on_burned_ground": all(c["safe_on_burned_ground"] for c in crews),
        },
        "nearest_place": v.place,
        "straight_line_only": grid is None,
        "attribution": v.attribution,
    }

