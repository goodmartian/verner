"""regions.parquet: countries (Natural Earth admin-0) and regions (admin-1) with simplified, repaired geometry."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import polars as pl
import shapely
from pyproj import Geod
from shapely.geometry.base import BaseGeometry

from .cells import country_code, read_layer
from .config import paths

MAX_VERTICES = 500
GEOD = Geod(ellps="WGS84")
SCHEMA = {
    "id": pl.String,
    "kind": pl.String,
    "country_id": pl.String,
    "names_json": pl.String,
    "bbox": pl.List(pl.Float32),
    "area_km2": pl.Float32,
    "geometry_wkb": pl.Binary,
}


def _polygons(geom: BaseGeometry) -> list[BaseGeometry]:
    """The non-empty polygons inside any geometry (make_valid may return collections with lines)."""
    if geom.geom_type == "Polygon":
        return [] if geom.is_empty else [geom]
    return [p for g in getattr(geom, "geoms", []) for p in _polygons(g)]


def _cap(poly: BaseGeometry, limit: int, tol: float = 0.001) -> list[BaseGeometry]:
    """Simplify one polygon with a growing tolerance until it has at most `limit` vertices; keep it valid."""
    while shapely.get_num_coordinates(poly) > limit:
        poly = shapely.simplify(poly, tol, preserve_topology=True)
        tol *= 1.6
    if poly.is_valid:
        return [poly]
    return [q for p in _polygons(shapely.make_valid(poly)) for q in _cap(p, limit, tol)]


def simplify(geom: BaseGeometry, limit: int = MAX_VERTICES) -> BaseGeometry:
    """MultiPolygon of the repaired geometry, every part (holes included) within `limit` vertices."""
    parts = [q for p in _polygons(shapely.make_valid(geom)) for q in _cap(p, limit)]
    multi = shapely.multipolygons(parts)
    for _ in range(10):  # simplified neighbouring parts can touch or overlap: merge them, then cap again
        if multi.is_valid:
            break
        parts = [q for p in _polygons(shapely.make_valid(multi)) for q in _cap(p, limit)]
        multi = shapely.multipolygons(parts)
    return multi


def area_km2(geom: BaseGeometry) -> float:
    """Geodesic area on WGS84; holes are subtracted."""
    total = 0.0
    for poly in _polygons(geom):
        outer = abs(GEOD.geometry_area_perimeter(shapely.Polygon(poly.exterior))[0])
        holes = sum(abs(GEOD.geometry_area_perimeter(shapely.Polygon(r))[0]) for r in poly.interiors)
        total += outer - holes
    return total / 1e6


def assemble(countries: Sequence[dict], admin1: Sequence[dict]) -> pl.DataFrame:
    """Rows from records `{id, ne_id, name, geometry, country_id}`.

    A missing or repeated region id becomes `X-<ne_id>`; a missing name becomes the id.
    """
    rows, seen = [], set()
    for kind, records in (("country", countries), ("region", admin1)):
        for rec in records:
            rid = rec["id"] if rec["id"] and rec["id"] != "-99" and rec["id"] not in seen else f"X-{rec['ne_id']}"
            if rid in seen:
                continue  # even the fallback is taken: the same Natural Earth feature twice
            seen.add(rid)
            valid = shapely.make_valid(rec["geometry"])
            if not _polygons(valid):
                continue
            west, south, east, north = valid.bounds
            rows.append(
                {
                    "id": rid,
                    "kind": kind,
                    "country_id": rid if kind == "country" else rec["country_id"],
                    "names_json": json.dumps({"en": rec["name"] or rid}, ensure_ascii=False),
                    "bbox": [west, south, east, north],
                    "area_km2": area_km2(valid),
                    "geometry_wkb": shapely.to_wkb(simplify(valid)),
                }
            )
    return pl.DataFrame(rows, schema=SCHEMA)


def build(geo: Path, out: Path) -> None:
    """Write `<out>/regions.parquet` from Natural Earth admin-0 and admin-1 in `geo`."""
    geoms, col = read_layer(geo / "ne_10m_admin_0_countries.zip", ["ISO_A2_EH", "NE_ID", "NAME_EN", "ADM0_A3"])
    countries = [
        {"id": country_code(i, int(n)), "ne_id": int(n), "name": nm, "geometry": g}
        for i, n, nm, g in zip(col["ISO_A2_EH"], col["NE_ID"], col["NAME_EN"], geoms)
    ]
    by_a3 = {a: c["id"] for a, c in zip(col["ADM0_A3"], countries)}

    geoms, col = read_layer(
        geo / "ne_10m_admin_1_states_provinces.zip", ["iso_3166_2", "iso_a2", "adm0_a3", "ne_id", "name_en"]
    )
    admin1 = [
        {
            "id": c,
            "ne_id": int(n),
            "name": nm,
            "geometry": g,
            "country_id": by_a3.get(a) or country_code(i, a),
        }
        for c, i, a, n, nm, g in zip(col["iso_3166_2"], col["iso_a2"], col["adm0_a3"], col["ne_id"], col["name_en"], geoms)
    ]
    out.mkdir(parents=True, exist_ok=True)
    assemble(countries, admin1).write_parquet(out / "regions.parquet")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline regions")
    ap.add_argument("--data", required=True, help="data root (contains _work/)")
    args = ap.parse_args(argv)
    p = paths(args.data)
    build(p.geo, p.built)
    print(f"wrote {p.built / 'regions.parquet'}")
    return 0
