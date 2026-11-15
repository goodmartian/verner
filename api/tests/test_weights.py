import numpy as np
import pytest

from senda_api import areas, weights
from senda_api.errors import ApiError


def w_of(store, selector):
    return weights.cell_weights(store, areas.parse(selector, store))


def test_weights_full_and_partial(store, ids):
    idx, w = w_of(store, {"bbox": [20.0, 9.75, 20.25, 10.0]})  # exactly cell A
    assert idx.tolist() == [store.cells.row_of[ids["a"]]] and w.tolist() == [1.0]
    idx, w = w_of(store, {"bbox": [20.0, 9.75, 20.125, 10.0]})
    assert len(idx) == 1 and w[0] == pytest.approx(0.5, abs=0.02)


def test_weights_sorted_and_positive(store):
    idx, w = w_of(store, {"bbox": [20.1, 9.1, 21.9, 9.9]})
    assert np.all(np.diff(idx) > 0) and np.all((w > 0) & (w <= 1))


def test_region_covers_its_cells(store):
    idx, w = w_of(store, {"id": "XA"})
    assert len(idx) == 40 and np.all(w == 1.0)
    idx, w = w_of(store, {"id": "XA-W"})
    assert len(idx) == 20 and np.all(w == 1.0)


def test_world_area_covers_all_cells(store):
    idx, w = w_of(store, {"id": "WORLD"})
    assert idx.tolist() == list(range(40)) and np.all(w == 1.0)


def test_polygon_edge_cells_partial(store):
    idx, w = w_of(store, {"polygon": {"type": "Polygon", "coordinates": [[[20, 9], [20.5, 9], [20.5, 9.5], [20, 9.5], [20, 9]]]}})
    assert len(idx) == 4 and np.all(w == 1.0)


def test_tiny_area_keeps_partial_weight(store):
    idx, w = w_of(store, {"bbox": [20.01, 9.76, 20.02, 9.77]})
    assert len(idx) == 1 and 0 < w[0] < 0.01


def test_ocean_area_no_land(store):
    with pytest.raises(ApiError) as e:
        w_of(store, {"bbox": [0, 0, 1, 1]})
    assert (e.value.status, e.value.code) == (422, "no_land")


def test_cache_returns_same_arrays(store):
    a = areas.parse({"bbox": [20, 9, 21, 10]}, store)
    assert weights.cell_weights(store, a)[0] is weights.cell_weights(store, a)[0]


def test_weighted_sum_matches_dense(store):
    idx, w = w_of(store, {"bbox": [20.0, 9.0, 21.0, 10.0]})
    got = weights.weighted_sum(store.H, idx, w)
    want = (store.H[idx].toarray() * w[:, None]).sum(axis=0)
    assert got.shape == (store.H.shape[1],) and np.allclose(got, want)
