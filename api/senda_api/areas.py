"""Parse an area selector (id, bbox, point with radius, polygon) into a validated geometry."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import shapely
from pyproj import Geod

from .errors import ApiError

if TYPE_CHECKING:
    from .store import Store

R_KM = 6371.0088
CELL_DEG = 0.25
MAX_VERTICES = 500
CIRCLE_VERTICES = 64
MIN_RADIUS_KM, MAX_RADIUS_KM = 1.0, 1500.0
WORLD_ID = "WORLD"
_GEOD = Geod(a=R_KM * 1000, f=0)
_FORMS = "Give exactly one of: id, bbox, polygon, or point with radius_km."


@dataclass(frozen=True, eq=False)
class Area:
    id: str | None
    name: str
    geometry: shapely.Geometry
    bbox: list[float]
    area_km2: float
    approximate: bool
    kind: str = "area"
    slug: str = "area"


def invalid(message: str) -> ApiError:
    return ApiError(400, "invalid_area", message)


def _project(coords: np.ndarray) -> np.ndarray:
    out = np.empty_like(coords, dtype=float)
    out[:, 0] = np.radians(coords[:, 0])
    out[:, 1] = np.sin(np.radians(coords[:, 1]))
    return out


def spherical_km2(geom: shapely.Geometry) -> float:
    """Area on the sphere: in (longitude in radians, sin latitude) planar area is proportional to true area."""
    return float(R_KM**2 * shapely.transform(geom, _project).area)


def cell_area_km2(lat: float) -> float:
    return R_KM**2 * math.radians(CELL_DEG) * (
        math.sin(math.radians(lat + CELL_DEG / 2)) - math.sin(math.radians(lat - CELL_DEG / 2))
    )


def _finish(
    id_: str | None, name: str, geom: shapely.Geometry, kind: str, slug: str, bbox: list[float] | None = None,
    area_km2: float | None = None,
) -> Area:
    km2 = spherical_km2(geom) if area_km2 is None else area_km2
    lat_c = geom.centroid.y
    approx = km2 < cell_area_km2(max(-89.8, min(89.8, lat_c)))
    return Area(
        id=id_,
        name=name,
        geometry=geom,
        bbox=[float(v) for v in (bbox if bbox is not None else geom.bounds)],
        area_km2=km2,
        approximate=bool(approx),
        kind=kind,
        slug=re.sub(r"[^a-z0-9._-]", "-", slug.lower()),
    )


def _num(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise invalid(f"{what} must be a finite number")
    return float(value)


def _polygonal(geom: shapely.Geometry) -> shapely.Geometry:
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if g.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.union_all(parts) if parts else shapely.Polygon()


def _bbox_area(raw: Any) -> Area:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise invalid("bbox must be [west, south, east, north]")
    w, s, e, n = (_num(v, "bbox values") for v in raw)
    if w > e:
        raise invalid("Boxes crossing the 180 degree line are not supported: draw two boxes or use a polygon")
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise invalid("bbox needs west < east, south < north, longitude -180..180 and latitude -90..90")
    return _finish(None, f"Box {w:g}, {s:g}, {e:g}, {n:g}", shapely.box(w, s, e, n), "bbox",
                   f"bbox-{w:g}_{s:g}_{e:g}_{n:g}")


def _ring(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, list) or len(raw) < 4:
        raise invalid("Each polygon ring needs at least 4 points")
    pts = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise invalid("Polygon points must be [longitude, latitude]")
        lon, lat = _num(p[0], "longitude"), _num(p[1], "latitude")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise invalid("Polygon coordinates must be longitude -180..180 and latitude -90..90")
        pts.append((lon, lat))
    if pts[0] != pts[-1]:
        raise invalid("Polygon rings must be closed (first point equals last)")
    if np.any(np.abs(np.diff([p[0] for p in pts])) > 180):
        raise invalid("Polygon edges crossing the 180 degree line are not supported")
    return pts


def _polygon_area(raw: Any) -> Area:
    if isinstance(raw, dict) and raw.get("type") == "MultiPolygon" and isinstance(raw.get("coordinates"), list):
        parts = [_polygon_area({"type": "Polygon", "coordinates": c}).geometry for c in raw["coordinates"]]
        if not parts:
            raise invalid("MultiPolygon has no parts")
        geom = shapely.union_all(parts)
        return _finish(None, "Drawn area", geom, "polygon", f"drawn-{hashlib.sha256(geom.wkb).hexdigest()[:8]}")
    if not isinstance(raw, dict) or raw.get("type") != "Polygon" or not isinstance(raw.get("coordinates"), list):
        raise invalid("polygon must be a GeoJSON Polygon")
    rings_raw = raw["coordinates"]
    if not rings_raw:
        raise invalid("Polygon has no rings")
    if sum(len(r) - 1 for r in rings_raw if isinstance(r, list)) > MAX_VERTICES:
        raise invalid(f"Polygon has more than {MAX_VERTICES} vertices")
    rings = [_ring(r) for r in rings_raw]
    geom = shapely.Polygon(rings[0], rings[1:])
    if not geom.is_valid:
        geom = _polygonal(shapely.make_valid(geom))
    if geom.is_empty or geom.area <= 0 or not geom.is_valid:
        raise invalid("Polygon has no area or cannot be repaired")
    digest = hashlib.sha256(geom.wkb).hexdigest()[:8]
    return _finish(None, "Drawn area", geom, "polygon", f"drawn-{digest}")


def _circle_area(point: Any, radius: Any) -> Area:
    if not isinstance(point, dict) or set(point) != {"lat", "lon"}:
        raise invalid("point must be {lat, lon}")
    lat, lon = _num(point["lat"], "lat"), _num(point["lon"], "lon")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise invalid("point needs lat -90..90 and lon -180..180")
    r = _num(radius, "radius_km")
    if not MIN_RADIUS_KM <= r <= MAX_RADIUS_KM:
        raise invalid(f"radius_km must be between {MIN_RADIUS_KM:g} and {MAX_RADIUS_KM:g}")
    if (90 - abs(lat)) * math.pi / 180 * R_KM <= r:
        raise invalid("The circle covers a pole: move the centre or reduce the radius")
    az = np.linspace(0, 360, CIRCLE_VERTICES, endpoint=False)
    lons, lats, _ = _GEOD.fwd(np.full(CIRCLE_VERTICES, lon), np.full(CIRCLE_VERTICES, lat), az,
                              np.full(CIRCLE_VERTICES, r * 1000))
    lons = lon + (np.asarray(lons) - lon + 180) % 360 - 180
    ring = shapely.Polygon(np.column_stack([lons, lats]))
    world = shapely.box(-180, -90, 180, 90)
    parts = [shapely.intersection(ring, world)]
    minx, _, maxx, _ = ring.bounds
    if minx < -180:
        parts.append(shapely.intersection(shapely.transform(ring, lambda c: c + [360, 0]), world))
    if maxx > 180:
        parts.append(shapely.intersection(shapely.transform(ring, lambda c: c - [360, 0]), world))
    geom = parts[0] if len(parts) == 1 else shapely.union_all(parts)
    return _finish(None, f"Circle {r:g} km at {lat:g}, {lon:g}", geom, "circle", f"pt-{lat:g}_{lon:g}_r{r:g}km")


def _world() -> Area:
    geom = shapely.box(-180, -90, 180, 90)
    return _finish(WORLD_ID, "World", geom, "world", "world", [-180.0, -90.0, 180.0, 90.0])


def parse(selector: Any, store: Store) -> Area:
    if not isinstance(selector, dict):
        raise invalid(_FORMS)
    keys = set(selector)
    if keys == {"id"}:
        rid = selector["id"]
        if not isinstance(rid, str) or not rid:
            raise invalid("id must be a non-empty string")
        if rid == WORLD_ID:
            return _world()
        region = store.regions.by_id.get(rid)
        if region is None:
            raise ApiError(404, "not_found", f"No data for area {rid}")
        return _finish(rid, region.name, region.geometry, "region", rid, region.bbox, region.area_km2)
    if keys == {"bbox"}:
        return _bbox_area(selector["bbox"])
    if keys == {"polygon"}:
        return _polygon_area(selector["polygon"])
    if keys == {"point", "radius_km"}:
        return _circle_area(selector["point"], selector["radius_km"])
    raise invalid(_FORMS)


def to_geojson(geom: shapely.Geometry, digits: int = 4) -> dict:
    rounded = shapely.set_precision(geom, 10.0**-digits)
    if rounded.is_empty:
        rounded = geom
    return json.loads(shapely.to_geojson(rounded))
