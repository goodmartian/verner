"""Independent re-computation of fixture totals straight from series_daily, used as test oracle."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

K = {
    ("modis_aqua", "era", 1): 4.0,
    ("modis_aqua", "era", 2): 5.0,
    ("modis_aqua", "recent", 1): 3.0,
    ("modis_aqua", "recent", 2): 3.5,
    ("viirs_noaa20", "era", 1): 0.875,
    ("viirs_noaa20", "era", 2): 1.125,
    ("modis_terra", "era", 1): 4.5,  # only in the version built with terra=True
    ("modis_terra", "era", 2): 6.0,
}


def kgroup(cell_id: int) -> int:
    return 1 if cell_id % 1440 - 800 < 5 else 2


def k(sensor: str, cell_id: int, d: date) -> float:
    if sensor == "viirs_snpp":
        return 1.0
    window = "recent" if sensor == "modis_aqua" and d.year >= 2022 else "era"
    return K[(sensor, window, kgroup(cell_id))]


def load_daily(root: Path) -> list[tuple[int, date, str, int, int]]:
    df = pl.read_parquet(root / "series_daily" / "year=*" / "part-0.parquet")
    return list(df.select("cell_id", "local_date", "sensor", "n_day", "n_night").iter_rows())


def harmonized(daily, weights: dict[int, float]):
    """Yield (local_date, harmonized weighted count) for each daily row of the given cells."""
    for cell_id, d, sensor, n_d, n_n in daily:
        w = weights.get(cell_id)
        if w:
            yield d, w * (n_d + n_n) * k(sensor, cell_id, d)


def month_totals(daily, weights: dict[int, float]) -> dict[tuple[int, int], float]:
    out: dict[tuple[int, int], float] = {}
    for d, v in harmonized(daily, weights):
        out[(d.year, d.month)] = out.get((d.year, d.month), 0.0) + v
    return out


def window_total(daily, weights: dict[int, float], start: date, end: date) -> float:
    return sum(v for d, v in harmonized(daily, weights) if start <= d <= end)


def rint(x: float) -> int:
    return int(np.rint(x))
