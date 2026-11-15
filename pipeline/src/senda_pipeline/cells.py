"""cells.parquet: the 0.25 degree land cells with country, RESOLVE zone and land fraction.

A cell is listed when at least one of its 5 x 5 inner points lies in a country polygon.
Every point test is a vectorised shapely `contains_xy` over the index window of a polygon part.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

import numpy as np
import polars as pl
import pyogrio.raw
import shapely
from shapely.geometry.base import BaseGeometry

from .config import paths

STEP = 0.25
SUB = 5  # inner points per cell side
NROWS, NCOLS = 720, 1440
POINT_STEP = STEP / SUB
COLUMNS = ["cell_id", "lat", "lon", "zone", "country", "land_frac"]
SCHEMA = {
    "cell_id": pl.Int32,
    "lat": pl.Float32,
    "lon": pl.Float32,
    "zone": pl.String,
    "country": pl.String,
    "land_frac": pl.Float32,
}


def cell_id(lat, lon):
    """`row * 1440 + col`, `row = floor((90 - lat) / 0.25)`, `col = floor((lon + 180) / 0.25)`; edges stay inside."""
    row = np.clip(np.floor((90 - np.asarray(lat, dtype=np.float64)) / STEP), 0, NROWS - 1).astype(np.int64)
    col = np.clip(np.floor((np.asarray(lon, dtype=np.float64) + 180) / STEP), 0, NCOLS - 1).astype(np.int64)
    out = row * NCOLS + col
    return int(out) if out.ndim == 0 else out


def zone_name(biome: int, lat: float) -> str:
    return f"resolve-{int(biome):02d}-{'n' if lat >= 0 else 's'}"


def country_code(iso_a2_eh: str | None, ne_id) -> str:
    """ISO_A2_EH of a Natural Earth country; `X-<ne_id>` when it is empty or -99."""
    iso = (iso_a2_eh or "").strip()
    return iso if iso and iso != "-99" else f"X-{ne_id}"


def _span(lo: float, hi: float, n: int, step: float, from_north: bool) -> tuple[int, int]:
    """Half-open index range of grid points whose centres can fall in [lo, hi] (a little generous)."""
    a, b = (90 - hi, 90 - lo) if from_north else (lo + 180, hi + 180)
    return max(0, int(np.floor(a / step - 0.5))), min(n, int(np.ceil(b / step - 0.5)) + 1)


def _window(geom: BaseGeometry, n_lat: int, n_lon: int, step: float):
    """Points of the grid inside the bounding box of `geom` as (i0, j0, mask of points inside the geometry)."""
    west, south, east, north = geom.bounds
    i0, i1 = _span(south, north, n_lat, step, True)
    j0, j1 = _span(west, east, n_lon, step, False)
    if i0 >= i1 or j0 >= j1:
        return None
    ys = 90 - (np.arange(i0, i1) + 0.5) * step
    xs = -180 + (np.arange(j0, j1) + 0.5) * step
    x, y = np.meshgrid(xs, ys)
    return i0, j0, shapely.contains_xy(geom, x, y)


def _stamp(grid: np.ndarray, items: Iterable[tuple[int, BaseGeometry]], step: float, only=None) -> None:
    """Write each item's value into the grid points inside its polygon parts that are still empty (< 0)."""
    for value, geom in items:
        for part in shapely.get_parts(geom):
            hit = _window(part, grid.shape[0], grid.shape[1], step)
            if hit is None:
                continue
            i0, j0, inside = hit
            rows, cols = slice(i0, i0 + inside.shape[0]), slice(j0, j0 + inside.shape[1])
            view = grid[rows, cols]
            ok = inside & (view < 0)
            if only is not None:
                ok &= only[rows, cols]
            view[ok] = value


def _biome_of_cells(biomes: Iterable[tuple[int, BaseGeometry]], land: np.ndarray, rows, cols) -> np.ndarray:
    """Most frequent biome among the 25 points of each listed cell (0 = none).

    A tie goes to the biome of the centre point, else to the smaller BIOME_NUM.
    """
    grid = np.full((NROWS * SUB, NCOLS * SUB), -1, dtype=np.int16)
    _stamp(grid, biomes, POINT_STEP, only=np.kron(land, np.ones((SUB, SUB), dtype=bool)))
    cube = grid.reshape(NROWS, SUB, NCOLS, SUB).transpose(0, 2, 1, 3).reshape(NROWS, NCOLS, SUB * SUB)[rows, cols]
    centre = cube[:, SUB * SUB // 2]
    top = int(cube.max())
    if top < 1:
        return np.zeros(len(rows), dtype=np.int16)
    counts = np.stack([(cube == k).sum(axis=1) + 0.5 * (centre == k) for k in range(1, top + 1)], axis=1)
    return np.where(counts.max(axis=1) > 0, counts.argmax(axis=1) + 1, 0).astype(np.int16)


def compute(
    countries: Sequence[tuple[str, BaseGeometry]],
    biomes: Iterable[tuple[int, BaseGeometry]],
) -> pl.DataFrame:
    """Cells of the given country polygons; `biomes` are (BIOME_NUM, polygon), the first polygon at a point wins."""
    codes = sorted({code for code, _ in countries})
    index = {code: k for k, code in enumerate(codes)}
    points = np.full((NROWS * SUB, NCOLS * SUB), -1, dtype=np.int16)
    _stamp(points, ((index[c], g) for c, g in countries), POINT_STEP)

    cube = points.reshape(NROWS, SUB, NCOLS, SUB).transpose(0, 2, 1, 3).reshape(NROWS, NCOLS, SUB * SUB)
    land = (cube >= 0).sum(axis=2)
    rows, cols = np.nonzero(land)
    if rows.size == 0:
        return pl.DataFrame(schema=SCHEMA)

    centre = points[SUB // 2 :: SUB, SUB // 2 :: SUB][rows, cols].astype(np.int64)
    for k in np.nonzero(centre < 0)[0]:  # centre in the sea: the country with the most points wins
        inner = cube[rows[k], cols[k]]
        centre[k] = np.bincount(inner[inner >= 0]).argmax()

    nums = _biome_of_cells(biomes, land > 0, rows, cols)

    lat = 90 - (rows + 0.5) * STEP
    lon = -180 + (cols + 0.5) * STEP
    zone = [zone_name(n, la) if n > 0 else "none" for n, la in zip(nums.tolist(), lat.tolist())]
    return pl.DataFrame(
        {
            "cell_id": (rows * NCOLS + cols).astype(np.int32),
            "lat": lat.astype(np.float32),
            "lon": lon.astype(np.float32),
            "zone": zone,
            "country": [codes[k] for k in centre.tolist()],
            "land_frac": (land[rows, cols] / (SUB * SUB)).astype(np.float32),
        },
        schema=SCHEMA,
    )


def read_layer(path: Path | str, columns: list[str], **kwargs) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Geometries and the named attribute columns of a shapefile in a zip (columns come back by name, not by order)."""
    meta, _, wkb, data = pyogrio.raw.read(f"zip://{path}", columns=columns, **kwargs)
    return shapely.from_wkb(wkb), dict(zip(meta["fields"], data))


def read_countries(geo: Path) -> list[tuple[str, BaseGeometry]]:
    geoms, col = read_layer(geo / "ne_10m_admin_0_countries.zip", ["ISO_A2_EH", "NE_ID"])
    return [(country_code(i, int(n)), g) for i, n, g in zip(col["ISO_A2_EH"], col["NE_ID"], geoms)]


def read_biomes(geo: Path, chunk: int = 40) -> Iterator[tuple[int, BaseGeometry]]:
    """Yield (BIOME_NUM, polygon) one chunk of ecoregions at a time; 'Rock and Ice' (BIOME_NAME N/A) is skipped."""
    path = geo / "Ecoregions2017.zip"
    total = pyogrio.read_info(f"zip://{path}")["features"]
    for start in range(0, total, chunk):
        geoms, col = read_layer(path, ["BIOME_NUM", "BIOME_NAME"], skip_features=start, max_features=chunk)
        for n, label, g in zip(col["BIOME_NUM"], col["BIOME_NAME"], geoms):
            if label != "N/A" and n >= 1:
                yield int(n), g


def build(geo: Path, out: Path) -> None:
    """Write `<out>/cells.parquet` from the Natural Earth and RESOLVE files in `geo`."""
    df = compute(read_countries(geo), read_biomes(geo))
    out.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out / "cells.parquet")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline cells")
    ap.add_argument("--data", required=True, help="data root (contains _work/)")
    args = ap.parse_args(argv)
    p = paths(args.data)
    build(p.geo, p.built)
    print(f"wrote {p.built / 'cells.parquet'}")
    return 0
