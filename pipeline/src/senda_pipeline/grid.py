"""Grid and time helpers shared by the pipeline: 0.25 deg cells, 0.01 deg cells, local solar time, tiles."""

from __future__ import annotations

import polars as pl

COLS = 1440  # 360 / 0.25
ROWS = 720  # 180 / 0.25
COLS01 = 36000  # 360 / 0.01
ROWS01 = 18000  # 180 / 0.01
TILE_DEG = 10


def cell_id(lat: pl.Expr, lon: pl.Expr) -> pl.Expr:
    """cell_id = row * 1440 + col, row = floor((90 - lat) / 0.25), col = floor((lon + 180) / 0.25)."""
    row = ((90.0 - lat.cast(pl.Float64)) / 0.25).floor().clip(0, ROWS - 1)
    col = ((lon.cast(pl.Float64) + 180.0) / 0.25).floor().clip(0, COLS - 1)
    return (row * COLS + col).cast(pl.Int32).alias("cell_id")


def cell01(lat: pl.Expr, lon: pl.Expr) -> pl.Expr:
    """Cell of 0.01 deg: row01 * 36000 + col01 (Int64)."""
    row = ((90.0 - lat.cast(pl.Float64)) * 100.0).floor().clip(0, ROWS01 - 1)
    col = ((lon.cast(pl.Float64) + 180.0) * 100.0).floor().clip(0, COLS01 - 1)
    return (row * COLS01 + col).cast(pl.Int64).alias("cell01")


def month_index(year: int, month: int) -> int:
    """Months since 2000-01."""
    return (year - 2000) * 12 + month - 1


def month_expr(date: pl.Expr) -> pl.Expr:
    """month_index for a Date expression (Int16)."""
    return ((date.dt.year() - 2000) * 12 + date.dt.month() - 1).cast(pl.Int16)


def local_dt(acq_utc: pl.Expr, lon: pl.Expr) -> pl.Expr:
    """Local solar time: acq_utc + round(lon * 4) minutes."""
    minutes = (lon.cast(pl.Float64) * 4.0).round(0).cast(pl.Int64)
    return acq_utc + pl.duration(minutes=minutes, time_unit="ms")


def tile(lat: pl.Expr, lon: pl.Expr) -> pl.Expr:
    """Tile name of 10 deg x 10 deg: lower-left corner, for example -30_-60."""
    la = (lat.cast(pl.Float64) / TILE_DEG).floor().cast(pl.Int32) * TILE_DEG
    lo = (lon.cast(pl.Float64) / TILE_DEG).floor().cast(pl.Int32) * TILE_DEG
    return (la.cast(pl.String) + "_" + lo.cast(pl.String)).alias("tile")
