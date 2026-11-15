"""Cell weights of an area: the share of each 0.25 degree cell that lies inside the area."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import scipy.sparse as sp
import shapely

from .areas import CELL_DEG, WORLD_ID, Area, _project
from .errors import ApiError
from .store import GRID_COLS, GRID_ROWS, Store

THREADS = 4
PARALLEL_FROM = 2000


def _no_land() -> ApiError:
    return ApiError(422, "no_land", "The area contains no land cells with fire data")


def _partial_areas(boxes: np.ndarray, geom: shapely.Geometry) -> np.ndarray:
    """Area (in the equal-area projection) of each box clipped by the geometry; large sets run on threads."""

    def one(chunk):
        return shapely.area(shapely.transform(shapely.intersection(chunk, geom), _project))

    if len(boxes) < PARALLEL_FROM:
        return one(boxes)
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        return np.concatenate(list(pool.map(one, np.array_split(boxes, THREADS))))


def _candidates(store: Store, geom: shapely.Geometry) -> np.ndarray:
    """Rows of the cells inside the bounding box of any part of the geometry, read straight off the grid."""
    grid = store.cells.row_of.reshape(GRID_ROWS, GRID_COLS)
    found = []
    for part in getattr(geom, "geoms", [geom]):
        x0, y0, x1, y1 = part.bounds
        r0, r1 = max(0, int(np.floor((90 - y1) / CELL_DEG))), min(GRID_ROWS, int(np.ceil((90 - y0) / CELL_DEG)))
        c0, c1 = max(0, int(np.floor((x0 + 180) / CELL_DEG))), min(GRID_COLS, int(np.ceil((x1 + 180) / CELL_DEG)))
        if r0 < r1 and c0 < c1:
            block = grid[r0:r1, c0:c1]
            found.append(block[block >= 0])
    return np.unique(np.concatenate(found)).astype(np.intp) if found else np.array([], dtype=np.intp)


def _compute(store: Store, geom: shapely.Geometry) -> tuple[np.ndarray, np.ndarray]:
    c = store.cells
    pos = _candidates(store, geom)
    if len(pos) == 0:
        raise _no_land()
    boxes = shapely.box(c.west[pos], c.south[pos], c.west[pos] + CELL_DEG, c.south[pos] + CELL_DEG)
    shapely.prepare(geom)
    w = np.zeros(len(pos))
    full = shapely.covers(geom, boxes)
    w[full] = 1.0
    partial = ~full & shapely.intersects(geom, boxes)
    if partial.any():
        got = _partial_areas(boxes[partial], geom)
        sin_n = np.sin(np.radians(c.south[pos][partial] + CELL_DEG))
        sin_s = np.sin(np.radians(c.south[pos][partial]))
        full_area = np.radians(CELL_DEG) * (sin_n - sin_s)
        w[partial] = np.minimum(1.0, got / full_area)
    keep = (w > 0) & (c.land_frac[pos] > 0)
    if not keep.any():
        raise _no_land()
    return pos[keep], w[keep]


def _cached(store: Store, wkb: bytes) -> tuple[np.ndarray, np.ndarray]:
    def make() -> tuple[np.ndarray, np.ndarray]:
        idx, w = _compute(store, shapely.from_wkb(wkb))
        idx.flags.writeable = False
        w.flags.writeable = False
        return idx, w

    return store.lru("weights", wkb, make, 64)


def cell_weights(store: Store, area: Area) -> tuple[np.ndarray, np.ndarray]:
    """Row indices (ascending) of cells touching the area, and their weights in (0, 1]."""
    if area.id == WORLD_ID:
        n = len(store.cells.cell_id)
        return np.arange(n), np.ones(n)
    return _cached(store, area.geometry.wkb)


def weighted_sum(matrix: sp.csr_matrix, idx: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Calendar of an area: weights times the selected matrix rows, one value per month column."""
    sub = matrix if len(idx) == matrix.shape[0] and idx[0] == 0 and idx[-1] == len(idx) - 1 else matrix[idx]
    return np.asarray(sub.T.dot(np.asarray(w, dtype=np.float64)), dtype=np.float64)
