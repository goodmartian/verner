"""Outline of a cloud of detections as drawn on the map (`blob_of`).

Every outline returned is a valid polygon of at least one grid cell: degenerate loops are repaired or dropped.

The points go on a grid of `gx` by `gy` degrees, the grid is closed (grown, then shrunk) so that neighbouring pixels
merge, the outer edges are traced, simplified and smoothed by corner cutting.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import LineString, MultiPolygon, Polygon

Ring = list[tuple[float, float]]


def chaikin(ring: Ring, steps: int) -> Ring:
    """Corner cutting of a closed ring."""
    current = ring
    for _ in range(steps):
        cut: Ring = []
        for j, p in enumerate(current):
            q = current[(j + 1) % len(current)]
            cut.append((p[0] * 0.75 + q[0] * 0.25, p[1] * 0.75 + q[1] * 0.25))
            cut.append((p[0] * 0.25 + q[0] * 0.75, p[1] * 0.25 + q[1] * 0.75))
        current = cut
    return current


def _simplify(points: Ring, tolerance: float) -> Ring:
    if len(points) < 3:
        return points
    return [tuple(p) for p in LineString(points).simplify(tolerance, preserve_topology=False).coords]


def _morph(grid: NDArray[np.bool_], grow: bool) -> NDArray[np.bool_]:
    """Dilate (grow) or erode a mask with a 3 by 3 square; outside the grid counts as empty."""
    height, width = grid.shape
    padded = np.pad(grid, 1, constant_values=False)
    shifts = [padded[1 + dr : 1 + dr + height, 1 + dc : 1 + dc + width] for dr in (-1, 0, 1) for dc in (-1, 0, 1)]
    return np.logical_or.reduce(shifts) if grow else np.logical_and.reduce(shifts)


def _edges(grid: NDArray[np.bool_]) -> dict[tuple[int, int], list[tuple[int, int]]]:
    """Directed edges around every lit cell wherever its neighbour is dark (outer edges only)."""
    padded = np.pad(grid, 1, constant_values=False)
    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for r, c in zip(*np.nonzero(grid), strict=True):
        r, c = int(r), int(c)
        if not padded[r, c + 1]:  # north
            edges.setdefault((c, r), []).append((c + 1, r))
        if not padded[r + 1, c + 2]:  # east
            edges.setdefault((c + 1, r), []).append((c + 1, r + 1))
        if not padded[r + 2, c + 1]:  # south
            edges.setdefault((c + 1, r + 1), []).append((c, r + 1))
        if not padded[r + 1, c]:  # west
            edges.setdefault((c, r + 1), []).append((c, r))
    return edges


def _smooth_loop(loop: list[tuple[int, int]], x0: float, y0: float, gx: float, gy: float) -> Ring:
    """Simplify a traced loop from its two far ends, smooth it and put it back on the map."""
    loop_f = [(float(p[0]), float(p[1])) for p in loop]
    far, farthest = 0, 0.0
    for j, corner in enumerate(loop_f):
        d = math.hypot(corner[0] - loop_f[0][0], corner[1] - loop_f[0][1])
        if d > farthest:
            farthest, far = d, j
    ring = _simplify(loop_f[: far + 1], 0.9) + _simplify([*loop_f[far:], loop_f[0]], 0.9)[1:-1]
    smooth = [(x0 + p[0] * gx, y0 + p[1] * gy) for p in chaikin(ring, 4)]
    return [*smooth, smooth[0]]


def _valid(ring: Ring, min_area: float) -> Ring | None:
    """The ring as a valid polygon of at least `min_area` (a grid cell): a self-crossing one is repaired, keeping its
    biggest part; None when nothing of that size is left."""
    poly = Polygon(ring)
    if not poly.is_valid:
        poly = poly.buffer(0)
        if isinstance(poly, MultiPolygon):
            poly = max(poly.geoms, key=lambda g: g.area)
    if poly.is_empty or not isinstance(poly, Polygon) or not poly.is_valid or poly.area < min_area:
        return None
    return [(float(x), float(y)) for x, y in poly.exterior.coords]


def blob_of(points: list[tuple[float, float]], gx: float = 0.0045, gy: float = 0.004) -> list[list[Ring]] | None:
    """Polygons (a list of rings each, GeoJSON order) around a cloud of [longitude, latitude] points; None for none."""
    if not points:
        return None
    margin = 3
    x0 = min(p[0] for p in points) - margin * gx
    y0 = min(p[1] for p in points) - margin * gy
    cells = [(math.floor((p[0] - x0) / gx), math.floor((p[1] - y0) / gy)) for p in points]
    grid = np.zeros((max(c[1] for c in cells) + margin + 1, max(c[0] for c in cells) + margin + 1), dtype=bool)
    for c, r in cells:
        grid[r, c] = True
    edges = _edges(_morph(_morph(grid, True), False))
    polygons: list[list[Ring]] = []
    for start in list(edges):
        if not edges[start]:
            continue
        loop: list[tuple[int, int]] = []
        current = start
        while True:
            ends = edges.get(current)
            if not ends:
                break
            loop.append(current)
            current = ends.pop()
            if current == start:
                break
        area = sum(p[0] * loop[(j + 1) % len(loop)][1] - loop[(j + 1) % len(loop)][0] * p[1] for j, p in enumerate(loop))
        if area > 0 and len(loop) >= 4 and (ring := _valid(_smooth_loop(loop, x0, y0, gx, gy), gx * gy)):
            polygons.append([ring])
    return polygons or None
