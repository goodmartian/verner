import math

import numpy as np
import shapely

from senda_api import fires

DX, DY = fires.AREA_CELL_DEG  # one cell, degrees
LON0, LAT0 = 20.0, 10.0
KX = fires.M_PER_DEG * math.cos(math.radians(LAT0))


def at(cells):
    """Detections at the centres of cells given as (column, row) in cell steps."""
    c = np.array(cells, dtype=float)
    return LON0 + c[:, 0] * DX, LAT0 + c[:, 1] * DY


def drawn(cells):
    lon, lat = at(cells)
    parts = fires._drawn_footprint(lon, lat)
    return [shapely.Polygon(p[0], p[1:]) for p in parts]


def ha(poly):
    m = shapely.transform(poly, lambda c: (c - [LON0, LAT0]) * [KX, fires.M_PER_DEG])
    return m.area / 1e4


def test_one_cell_stays_a_small_rounded_patch():
    (patch,) = drawn([(0, 0)])
    assert patch.is_valid and 10 < ha(patch) < 20  # about one cell, 14 ha
    assert len(patch.exterior.coords) > 5  # corners are rounded, not a four-corner square


def test_cells_closer_than_the_threshold_join_and_farther_stay_apart():
    # a gap of 0.4 cell (150 m) is closed; a gap of 2 cells (750 m) is not
    near = drawn([(0, 0), (1.4, 0)])
    far = drawn([(0, 0), (3, 0)])
    assert len(near) == 1 and len(far) == 2


def test_dense_block_with_a_small_hole_is_filled_and_a_big_hole_stays():
    block = [(x, y) for x in range(8) for y in range(8)]
    small = drawn([c for c in block if c != (3, 3)])
    assert len(small) == 1 and not small[0].interiors  # a one-cell hole is closed
    big = drawn([c for c in block if not (2 <= c[0] <= 5 and 2 <= c[1] <= 5)])
    assert len(big) == 1 and len(big[0].interiors) == 1  # a four by four hole stays


def test_rings_are_valid_few_vertices_and_five_digits():
    rng = np.random.default_rng(3)
    for _ in range(50):
        cells = {(int(x), int(y)) for x, y in rng.integers(0, 25, (int(rng.integers(1, 120)), 2))}
        lon, lat = at(sorted(cells))
        parts = fires._drawn_footprint(lon, lat)
        flat = [ring for part in parts for ring in part]
        assert all(shapely.Polygon(p[0], p[1:]).is_valid for p in parts)
        assert sum(len(r) for r in flat) < 120 * 40
        assert all(round(v, 5) == v for ring in flat for pt in ring for v in pt)


def test_no_detections_and_the_counted_area_is_untouched():
    assert fires._drawn_footprint(np.zeros(0), np.zeros(0)) is None
    lon, lat = at([(0, 0), (1.4, 0), (3, 0)])
    counted = fires._cell_union(lon, lat)
    assert len(counted.geoms) == 3  # the cells as counted keep their gaps; only the drawing closes them
    assert len(drawn([(0, 0), (1.4, 0), (3, 0)])) == 1
