"""CSV exports: hotspot rows from disk (only the needed years and tiles) and the monthly table of a calendar."""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow.parquet as pq
import shapely

from . import calendar
from .areas import CELL_DEG, WORLD_ID, Area
from .months import month_end, month_label, month_start
from .store import GRID_COLS, GRID_ROWS, Store

HOTSPOT_HEADER = ("latitude", "longitude", "acq_datetime_utc", "local_solar_date", "sensor", "frp_mw", "confidence",
                  "daynight", "source", "harmonized_weight")
MONTHLY_HEADER = ("month", "count", "median", "mean", "ratio", "level", "partial", "converted", "expected_error", "lo",
                  "hi", "modis_aqua", "viirs_snpp", "viirs_noaa20", "sensors")
TILE_DEG = 10
EOL = "\r\n"


def _date_range(store: Store, from_: str | None, to: str | None) -> tuple[date, date]:
    first, last = calendar.resolve_period(store, from_, to)
    return month_start(first), month_end(last)


def _tile_names(area: Area) -> list[str]:
    west, south, east, north = area.geometry.bounds
    lat0, lat1 = math.floor(south / TILE_DEG) * TILE_DEG, min(math.floor(north / TILE_DEG) * TILE_DEG, 80)
    lon0, lon1 = math.floor(west / TILE_DEG) * TILE_DEG, min(math.floor(east / TILE_DEG) * TILE_DEG, 170)
    return [f"tile={lat}_{lon}" for lat in range(lat0, lat1 + 1, TILE_DEG) for lon in range(lon0, lon1 + 1, TILE_DEG)]


def _files(store: Store, area: Area, start: date, end: date) -> list[Path]:
    out = []
    tiles = _tile_names(area)
    for year in range(start.year, end.year + 1):
        folder = store.root / "rows" / f"year={year}"
        out.extend(p for t in tiles for p in sorted((folder / t).glob("*.parquet")))
    return out


def _chunks(store: Store, area: Area, start: date, end: date, columns: list[str]) -> Iterator[pl.DataFrame]:
    """Hotspots of the area, one frame per file: local date in range and the point inside the geometry."""
    west, south, east, north = area.geometry.bounds
    world = area.id == WORLD_ID
    if not world:
        shapely.prepare(area.geometry)
    for path in _files(store, area, start, end):
        df = (
            pl.scan_parquet(path)
            .filter(
                (pl.col("local_date") >= start) & (pl.col("local_date") <= end)
                & (pl.col("lon") >= west) & (pl.col("lon") <= east) & (pl.col("lat") >= south) & (pl.col("lat") <= north)
            )
            .select(columns)
            .collect()
        )
        if df.is_empty() or world:
            yield df
            continue
        inside = shapely.covers(area.geometry, shapely.points(df["lon"].to_numpy().astype(float),
                                                              df["lat"].to_numpy().astype(float)))
        yield df.filter(pl.Series(inside))


def _world_years_over(store: Store, area: Area, start: date, end: date, stop_over: int) -> int | None:
    """The rows of the world in the years strictly inside the period, from the file footers alone, once they pass
    `stop_over`; None when they do not. A year folder holds the rows of that local year (the pipeline splits by
    `local_date`), and the world has no outline to cut by, so every row of an inner year is in the export."""
    inner = date(start.year + 1, 1, 1), date(end.year - 1, 12, 31)
    if inner[0] > inner[1]:
        return None
    total = 0
    for path in _files(store, area, *inner):
        total += pq.read_metadata(path).num_rows  # the footer only: no column is read
        if total > stop_over:
            return total
    return None


def count_rows(store: Store, area: Area, from_: str | None, to: str | None, stop_over: int | None = None) -> int:
    """Number of rows hotspots() would write; reads only latitude, longitude and date.

    With `stop_over`, the count stops at the first file that takes it past that number: the answer is then a lower
    bound, enough to refuse (the world over all years is 275 million rows, and the refusal must not take minutes).
    For the world it first sums the footers of the inner years, which refuses many years without reading any data."""
    start, end = _date_range(store, from_, to)
    if stop_over is not None and area.id == WORLD_ID:
        over = _world_years_over(store, area, start, end, stop_over)
        if over is not None:
            return over
    total = 0
    for df in _chunks(store, area, start, end, ["lat", "lon", "local_date"]):
        total += len(df)
        if stop_over is not None and total > stop_over:
            break
    return total


def _weights(store: Store, df: pl.DataFrame) -> list[str]:
    """k of each hotspot as text with four decimals; blank when the cell has no factors."""
    return ["" if math.isnan(v) else f"{v:.4f}" for v in _k(store, df)]


def _k(store: Store, df: pl.DataFrame) -> np.ndarray:
    """k of each hotspot: sensor, cell group, local month and day or night. NaN when the cell has no factors."""
    lat = df["lat"].to_numpy().astype(np.float64)
    lon = df["lon"].to_numpy().astype(np.float64)
    r = np.floor((90.0 - lat) / CELL_DEG).astype(np.int64)
    c = np.floor((lon + 180.0) / CELL_DEG).astype(np.int64)
    ok = (r >= 0) & (r < GRID_ROWS) & (c >= 0) & (c < GRID_COLS)
    rows = np.full(len(df), -1, dtype=np.int64)
    rows[ok] = store.cells.row_of[r[ok] * GRID_COLS + c[ok]]
    dates = df["local_date"]
    months = ((dates.dt.year() - 2000) * 12 + dates.dt.month() - 1).to_numpy()
    sensor = df["sensor"].to_numpy()
    daynight = df["daynight"].to_numpy()
    k = np.full(len(df), np.nan)
    for name in np.unique(sensor):
        for dn in ("D", "N"):
            sel = (sensor == name) & (daynight == dn) & (rows >= 0)
            if sel.any():
                got, _, missing = store.klookup.lookup(str(name), rows[sel], months[sel], dn)
                k[sel] = np.where(missing, np.nan, got)
    return k


def _fixed(values: pl.Series, digits: int) -> pl.Series:
    """Floats as text with `digits` decimals, written by the CSV writer (correctly rounded from the binary value, as
    Python's `f"{v:.{digits}f}"`); null for a gap or NaN, so the file has an empty field there."""
    clean = values.cast(pl.Float64).fill_nan(None)
    text = pl.DataFrame({"v": clean}).write_csv(include_header=False, float_precision=digits, line_terminator="\n",
                                                null_value="")
    parts = pl.Series(text.split("\n")[:-1], dtype=pl.String)
    return pl.select(pl.when(parts == "").then(None).otherwise(parts)).to_series()


def _lines(store: Store, df: pl.DataFrame) -> str:
    """The rows of a frame as CSV, written by polars in one go: no Python per row."""
    rows = pl.DataFrame({
        "lat": df["lat"].cast(pl.Float64),
        "lon": df["lon"].cast(pl.Float64),
        "utc": df["acq_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "local": df["local_date"].dt.strftime("%Y-%m-%d"),
        "sensor": df["sensor"].cast(pl.String),
        "frp": _fixed(df["frp_mw"], 1),
        "confidence": df["confidence"].cast(pl.String),
        "daynight": df["daynight"].cast(pl.String),
        "source": df["source"].cast(pl.String),
        "weight": _fixed(pl.Series(_k(store, df)), 4),
    })
    # the only floats left are the coordinates: five decimals; quotes only where a field needs them
    return rows.write_csv(include_header=False, float_precision=5, line_terminator=EOL, null_value="",
                          quote_style="necessary")


def hotspots(store: Store, area: Area, from_: str | None, to: str | None) -> Iterator[bytes]:
    """CSV of the hotspots of the series inside the area: header first, then one chunk per file."""
    start, end = _date_range(store, from_, to)
    yield (",".join(HOTSPOT_HEADER) + EOL).encode()
    columns = ["lat", "lon", "acq_utc", "local_date", "sensor", "frp_mw", "confidence", "daynight", "source"]
    for df in _chunks(store, area, start, end, columns):
        if len(df):
            yield _lines(store, df).encode()


def file_name(store: Store, area: Area, first: int, last: int) -> str:
    return f"verner_{area.slug}_{month_label(first)}_{month_label(last)}_{store.version[:16]}.csv"
