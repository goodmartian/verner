"""Foot trail over land cover: the search of the planner (`find_trail`), on the grid of `landcover.py`.

A* over the cells of a WorldCover grid (about 80 m) from a start to a goal, eight neighbours, the cost of a step is its
length times the mean of the two cell costs. A cell costs by its class (water never, marsh and built-up dear), forty
times more where the forecast front will be during the work (and the fire is not yet), eight times more within 200 m of
fire of the last two passes. The search runs in a window around the straight way first and over the whole grid only
when the window has no way: the cost of a plan stays in seconds on the largest fires.
"""

from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass

import numpy as np
import shapely
from numpy.typing import NDArray
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Polygon

LAND_COST = np.array([3, 2.5, 1.5, 1, 1.2, 1, 1, 3, np.inf, 6, 2], dtype=np.float64)
UNKNOWN_CLASS_COST = 3.0
FIRE_AHEAD_FACTOR = 40.0
HOT_FACTOR = 8.0
HOT_RADIUS_M = 200.0
SIMPLIFY_M = 35.0
WINDOW_PAD_M = 3000.0
WINDOW_PAD_SHARE = 0.5
WATER = (8, 9)
SPEEDS_KMH = [3, 2, 2.5, 4, 3.5, 4.5, 4, 2, 1, 1.2, 2.5]
"""Walking speed over each land class (no data, trees, shrub, grass, crops, built-up, bare, ice, water, marsh, moss)."""


@dataclass(frozen=True)
class Frame:
    """Plane of the planner: metres east and north of (lon0, lat0), moved by `shift`."""

    lon0: float
    lat0: float
    kx: float
    ky: float
    shift: tuple[float, float]

    def x(self, lon: NDArray[np.float64]) -> NDArray[np.float64]:
        return (lon - self.lon0) * self.kx - self.shift[0]

    def y(self, lat: NDArray[np.float64]) -> NDArray[np.float64]:
        return (lat - self.lat0) * self.ky - self.shift[1]

    def lonlat(self, x: float, y: float) -> tuple[float, float]:
        return self.lon0 + (x + self.shift[0]) / self.kx, self.lat0 + (y + self.shift[1]) / self.ky


@dataclass(frozen=True)
class Grid:
    """A land cover grid as `landcover.LandCover.read` answers it, with its cells in the metres of a frame."""

    width: int
    height: int
    bbox: tuple[float, float, float, float]
    classes: NDArray[np.uint8]
    """Class number of each cell, row by row from the north-west corner."""

    @classmethod
    def of(cls, grid: dict) -> Grid:
        cells = np.frombuffer(grid["classes"].encode("ascii"), dtype=np.uint8) - 48
        return cls(int(grid["width"]), int(grid["height"]), tuple(grid["bbox"]), cells)

    def cell_of(self, lon: float, lat: float) -> int:
        west, south, east, north = self.bbox
        c = math.floor((lon - west) / ((east - west) / self.width))
        r = math.floor((north - lat) / ((north - south) / self.height))
        return -1 if c < 0 or r < 0 or c >= self.width or r >= self.height else r * self.width + c

    def class_at(self, lon: float, lat: float) -> int:
        j = self.cell_of(lon, lat)
        return int(self.classes[j]) if j >= 0 else -1


@dataclass(frozen=True)
class Trail:
    points: list[tuple[float, float]]
    length: float
    wet: bool
    """The straight way would cross more water or marsh than the trail does."""
    walk_min: int


def _search(
    cost: list[float], width: int, height: int, start: int, goal: int, col_x: list[float], row_y: list[float],
    mx: float, my: float,
) -> list[int]:
    """The cheapest way over `cost` (row-major cells, inf where it cannot be walked): cell indices, or []."""
    steps = [(dr, dc, math.hypot(dr * my, dc * mx)) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dr or dc]
    gx, gy = col_x[goal % width], row_y[goal // width]
    best = {start: 0.0}
    parent = {start: -1}
    done: set[int] = set()
    heap = [(math.hypot(col_x[start % width] - gx, row_y[start // width] - gy), start)]
    while heap:
        _, j = heapq.heappop(heap)
        if j in done:
            continue
        done.add(j)
        if j == goal:
            break
        r0, c0 = divmod(j, width)
        cj, bj = cost[j], best[j]
        for dr, dc, length in steps:
            r, c = r0 + dr, c0 + dc
            if r < 0 or c < 0 or r >= height or c >= width:
                continue
            v = r * width + c
            if v in done:
                continue
            cv = cj if v == goal else cost[v]  # the goal is priced with the cell it is reached from
            if cv == math.inf:
                continue
            nd = bj + length * (cj + cv) / 2
            if nd < best.get(v, math.inf):
                best[v] = nd
                parent[v] = j
                heapq.heappush(heap, (nd + math.hypot(col_x[c] - gx, row_y[r] - gy), v))
    if goal not in done:
        return []
    path, j = [], goal
    while j >= 0:
        path.append(j)
        j = parent[j]
    return path[::-1]


def find_trail(
    grid: Grid,
    frame: Frame,
    start: tuple[float, float],
    goal: tuple[float, float],
    *,
    hull: Polygon,
    forecast: Polygon,
    active: NDArray[np.float64],
) -> Trail | None:
    """Foot trail from `start` to `goal` (planner metres) avoiding water, fire of the last two passes (`active`) and the
    ground the front will cross (`forecast` outside `hull`). None when a point is off the grid or there is no way."""
    west, south, east, north = grid.bbox
    cx, cy = (east - west) / grid.width, (north - south) / grid.height
    mx, my = cx * frame.kx, cy * frame.ky
    col_x = frame.x(west + (np.arange(grid.width) + 0.5) * cx)
    row_y = frame.y(north - (np.arange(grid.height) + 0.5) * cy)

    def cell(p: tuple[float, float]) -> int:
        lon, lat = frame.lonlat(*p)
        return grid.cell_of(lon, lat)

    sc, gc = cell(start), cell(goal)
    if sc < 0 or gc < 0:
        return None
    distance = math.hypot(goal[0] - start[0], goal[1] - start[1])
    pad = max(WINDOW_PAD_M, WINDOW_PAD_SHARE * distance)
    for window in (True, False):
        r0, r1, c0, c1 = 0, grid.height, 0, grid.width
        if window:
            c_lo, c_hi = sorted((sc % grid.width, gc % grid.width))
            r_lo, r_hi = sorted((sc // grid.width, gc // grid.width))
            c0, c1 = max(0, c_lo - math.ceil(pad / mx)), min(grid.width, c_hi + math.ceil(pad / mx) + 1)
            r0, r1 = max(0, r_lo - math.ceil(pad / my)), min(grid.height, r_hi + math.ceil(pad / my) + 1)
            if (r1 - r0, c1 - c0) == (grid.height, grid.width):
                window = False
        path = _search_window(grid, col_x, row_y, (r0, r1, c0, c1), sc, gc, mx, my, hull, forecast, active)
        if path or not window:
            break
    if not path:
        return None
    width = grid.width
    raw = [(float(col_x[j % width]), float(row_y[j // width])) for j in path]
    raw[0], raw[-1] = start, goal
    points = [tuple(p) for p in LineString(raw).simplify(SIMPLIFY_M, preserve_topology=False).coords]
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in itertools.pairwise(points))
    classes = grid.classes
    on_foot = sum(
        math.hypot(col_x[a % width] - col_x[b % width], row_y[a // width] - row_y[b // width]) / 1000
        / SPEEDS_KMH[min(int(classes[b]), len(SPEEDS_KMH) - 1)]
        for a, b in itertools.pairwise(path)
    )
    wet_path = sum(1 for j in path if classes[j] in WATER) / max(1, len(path)) * 40
    wet_straight = sum(
        1 for m in range(41)
        if grid.class_at(*frame.lonlat(start[0] + (goal[0] - start[0]) * m / 40, start[1] + (goal[1] - start[1]) * m / 40))
        in WATER
    )
    return Trail(points, length, wet_straight > wet_path + 2, max(5, math.floor(on_foot * 60 / 5 + 0.5) * 5))


def _search_window(
    grid: Grid, col_x: NDArray[np.float64], row_y: NDArray[np.float64], box: tuple[int, int, int, int], sc: int,
    gc: int, mx: float, my: float, hull: Polygon, forecast: Polygon, active: NDArray[np.float64],
) -> list[int]:
    """Search inside rows r0..r1 and columns c0..c1; the result is in indices of the whole grid."""
    r0, r1, c0, c1 = box
    h, w = r1 - r0, c1 - c0
    cells = grid.classes.reshape(grid.height, grid.width)[r0:r1, c0:c1]
    base = np.where(cells < len(LAND_COST), LAND_COST[np.minimum(cells, len(LAND_COST) - 1)], UNKNOWN_CLASS_COST)
    xs, ys = np.meshgrid(col_x[c0:c1], row_y[r0:r1])
    minx, miny, maxx, maxy = forecast.bounds
    near = (xs >= minx) & (xs <= maxx) & (ys >= miny) & (ys <= maxy)
    ahead = np.zeros((h, w), dtype=bool)
    if near.any():
        ahead[near] = shapely.contains_xy(forecast, xs[near], ys[near]) & ~shapely.contains_xy(hull, xs[near], ys[near])
    cost = base * np.where(ahead, FIRE_AHEAD_FACTOR, 1.0)
    if len(active):
        d, _ = cKDTree(active).query(np.column_stack([xs.ravel(), ys.ravel()]), distance_upper_bound=HOT_RADIUS_M)
        cost = cost * np.where((d <= HOT_RADIUS_M).reshape(h, w), HOT_FACTOR, 1.0)
    s_r, s_c = divmod(sc, grid.width)
    g_r, g_c = divmod(gc, grid.width)
    found = _search(
        cost.ravel().tolist(), w, h, (s_r - r0) * w + s_c - c0, (g_r - r0) * w + g_c - c0,
        col_x[c0:c1].tolist(), row_y[r0:r1].tolist(), mx, my,
    )
    return [(r0 + j // w) * grid.width + c0 + j % w for j in found]
