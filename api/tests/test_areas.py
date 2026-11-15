import math

import pytest

from senda_api import areas
from senda_api.errors import ApiError


def code(exc: pytest.ExceptionInfo) -> tuple[int, str]:
    return exc.value.status, exc.value.code


def test_area_forms(store):
    by_id = areas.parse({"id": "XA"}, store)
    assert by_id.id == "XA" and by_id.name == "Xland" and by_id.bbox == [20.0, 9.0, 22.5, 10.0]
    by_box = areas.parse({"bbox": [20, 9, 21, 10]}, store)
    assert by_box.id is None and by_box.bbox == [20.0, 9.0, 21.0, 10.0] and not by_box.approximate
    by_pt = areas.parse({"point": {"lat": 9.5, "lon": 21.0}, "radius_km": 20}, store)
    assert by_pt.id is None and math.isclose(by_pt.area_km2, math.pi * 400, rel_tol=0.03)
    by_poly = areas.parse({"polygon": {"type": "Polygon", "coordinates": [[[20, 9], [21, 9], [21, 10], [20, 9]]]}}, store)
    assert by_poly.id is None and by_poly.geometry.is_valid and by_poly.area_km2 > 0
    for a in (by_id, by_box, by_pt, by_poly):
        assert a.geometry.geom_type in ("Polygon", "MultiPolygon")


def test_two_keys_rejected(store):
    with pytest.raises(ApiError) as e:
        areas.parse({"id": "XA", "bbox": [20, 9, 21, 10]}, store)
    assert code(e) == (400, "invalid_area")
    with pytest.raises(ApiError) as e:
        areas.parse({}, store)
    assert code(e) == (400, "invalid_area")
    with pytest.raises(ApiError) as e:
        areas.parse({"point": {"lat": 1, "lon": 1}}, store)  # radius missing
    assert code(e) == (400, "invalid_area")


def test_unknown_region_is_404(store):
    with pytest.raises(ApiError) as e:
        areas.parse({"id": "ZZ"}, store)
    assert code(e) == (404, "not_found")


def test_world(store):
    w = areas.parse({"id": "WORLD"}, store)
    assert w.id == "WORLD" and math.isclose(w.area_km2, 510_065_000, rel_tol=0.001)


def test_bbox_over_dateline_rejected(store):
    with pytest.raises(ApiError) as e:
        areas.parse({"bbox": [170, 0, -170, 10]}, store)
    assert code(e) == (400, "invalid_area")
    assert "180" in e.value.message


@pytest.mark.parametrize("bbox", [[0, 0, 0, 1], [0, 5, 1, 5], [0, 6, 1, 5], [0, -91, 1, 5], [0, 0, 181, 5], [0, 0, 1], "x"])
def test_bad_bbox(store, bbox):
    with pytest.raises(ApiError) as e:
        areas.parse({"bbox": bbox}, store)
    assert code(e) == (400, "invalid_area")


def test_self_intersecting_polygon_rejected_or_fixed(store):
    bowtie = {"type": "Polygon", "coordinates": [[[20, 9], [21, 10], [21, 9], [20, 10], [20, 9]]]}
    try:
        a = areas.parse({"polygon": bowtie}, store)
    except ApiError as err:
        assert (err.status, err.code) == (400, "invalid_area")
    else:
        assert a.geometry.is_valid and a.area_km2 > 0


def test_degenerate_polygon_rejected(store):
    flat = {"type": "Polygon", "coordinates": [[[20, 9], [21, 9], [22, 9], [20, 9]]]}
    with pytest.raises(ApiError) as e:
        areas.parse({"polygon": flat}, store)
    assert code(e) == (400, "invalid_area")


def test_polygon_vertex_limit(store):
    ring = [[20 + i * 1e-4, 9 + (i % 2) * 1e-4] for i in range(600)]
    ring.append(ring[0])
    with pytest.raises(ApiError) as e:
        areas.parse({"polygon": {"type": "Polygon", "coordinates": [ring]}}, store)
    assert code(e) == (400, "invalid_area")


@pytest.mark.parametrize("bad", [{"type": "Point", "coordinates": [1, 2]}, {"type": "Polygon", "coordinates": []}, "x",
                                 {"type": "Polygon", "coordinates": [[[200, 9], [21, 9], [21, 10], [200, 9]]]}])
def test_bad_polygon_shapes(store, bad):
    with pytest.raises(ApiError) as e:
        areas.parse({"polygon": bad}, store)
    assert code(e) == (400, "invalid_area")


def test_radius_limits(store):
    for r in (0, 0.5, 1501, -3, "x", None, True):
        with pytest.raises(ApiError) as e:
            areas.parse({"point": {"lat": 10, "lon": 20}, "radius_km": r}, store)
        assert code(e) == (400, "invalid_area")
    for r in (1, 1500):
        assert areas.parse({"point": {"lat": 10, "lon": 20}, "radius_km": r}, store).area_km2 > 0
    with pytest.raises(ApiError):
        areas.parse({"point": {"lat": 91, "lon": 20}, "radius_km": 5}, store)


def test_circle_has_64_vertices(store):
    a = areas.parse({"point": {"lat": 10, "lon": 20}, "radius_km": 50}, store)
    assert len(a.geometry.exterior.coords) == 65


def test_circle_over_dateline_is_split(store):
    a = areas.parse({"point": {"lat": 0, "lon": 179.9}, "radius_km": 100}, store)
    minx, _, maxx, _ = a.geometry.bounds
    assert a.geometry.is_valid and minx >= -180 and maxx <= 180
    assert a.geometry.geom_type == "MultiPolygon"
    assert math.isclose(a.area_km2, math.pi * 100**2, rel_tol=0.03)


def test_circle_over_pole_rejected(store):
    with pytest.raises(ApiError) as e:
        areas.parse({"point": {"lat": 89, "lon": 20}, "radius_km": 500}, store)
    assert code(e) == (400, "invalid_area")


def test_tiny_area_is_approximate(store):
    tiny = areas.parse({"bbox": [20.01, 9.01, 20.02, 9.02]}, store)
    assert tiny.approximate
    assert not areas.parse({"bbox": [20, 9, 22, 10]}, store).approximate


def test_geojson_roundtrip(store):
    gj = areas.to_geojson(areas.parse({"id": "XA-W"}, store).geometry)
    assert gj["type"] == "Polygon" and gj["coordinates"][0][0] == [20.0, 9.0]
