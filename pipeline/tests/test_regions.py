from __future__ import annotations

import json

import numpy as np
import shapely
from shapely.geometry import Polygon, box

from senda_pipeline import regions


def _circle(n: int, r: float = 1.0) -> Polygon:
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return Polygon(np.c_[r * np.cos(t), r * np.sin(t)])


def _rec(id, geom, name="x", ne_id=1, country_id=None):
    return {"id": id, "ne_id": ne_id, "name": name, "geometry": geom, "country_id": country_id}


def test_region_ids_unique_and_named():
    countries = [_rec("AA", box(0, 0, 1, 1), name="Aland"), _rec("BB", box(2, 0, 3, 1), name="")]
    admin1 = [
        _rec("AA-1", box(0, 0, 0.5, 1), name="North", country_id="AA"),
        _rec("AA-1", box(0.5, 0, 1, 1), name="South", ne_id=7, country_id="AA"),  # duplicate id
        _rec("", box(2, 0, 2.5, 1), name="", ne_id=9, country_id="BB"),  # no id, no name
    ]
    df = regions.assemble(countries, admin1)
    assert df["id"].is_unique().all()
    assert df.height == 5
    names = {r["id"]: json.loads(r["names_json"])["en"] for r in df.iter_rows(named=True)}
    assert names["BB"] == "BB"  # empty name becomes the id
    assert names["AA"] == "Aland"
    assert names["X-9"] == "X-9"
    assert set(df["kind"].to_list()) == {"country", "region"}
    assert df.filter(df["kind"] == "region")["country_id"].to_list() == ["AA", "AA", "BB"]
    assert df.filter(df["kind"] == "country")["country_id"].to_list() == ["AA", "BB"]  # a country is its own country


def test_region_vertices_capped():
    df = regions.assemble([_rec("AA", _circle(20000), name="Round")], [])
    geom = shapely.from_wkb(df["geometry_wkb"][0])
    parts = list(shapely.get_parts(geom))
    assert parts and all(shapely.get_num_coordinates(p) <= 500 for p in parts)
    assert all(shapely.is_valid(p) for p in parts)
    assert geom.area > 0.99 * np.pi * 0.99  # still a circle of radius 1


def test_touching_parts_stay_a_valid_multipolygon():
    two = shapely.multipolygons([box(0, 0, 1, 1), box(1, 0, 2, 1)])  # share an edge: an invalid MultiPolygon
    df = regions.assemble([_rec("AA", two)], [])
    geom = shapely.from_wkb(df["geometry_wkb"][0])
    assert shapely.is_valid(geom) and abs(geom.area - 2) < 1e-9


def test_invalid_polygon_is_repaired():
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
    df = regions.assemble([_rec("AA", bowtie)], [])
    assert shapely.is_valid(shapely.from_wkb(df["geometry_wkb"][0]))


def test_area_is_geodesic_and_bbox_is_wsen():
    df = regions.assemble([_rec("AA", box(0, 0, 1, 1))], [])
    assert 12000 < df["area_km2"][0] < 12700  # 1 x 1 degree at the equator
    assert df["bbox"][0].to_list() == [0.0, 0.0, 1.0, 1.0]


def test_area_subtracts_holes():
    ring = Polygon(box(0, 0, 2, 2).exterior.coords, [box(0.5, 0.5, 1.5, 1.5).exterior.coords])
    full = regions.assemble([_rec("AA", box(0, 0, 2, 2))], [])["area_km2"][0]
    holed = regions.assemble([_rec("AA", ring)], [])["area_km2"][0]
    assert 0.7 * full < holed < 0.8 * full
