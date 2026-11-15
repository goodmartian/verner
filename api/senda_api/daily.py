"""Same calendar dates in every baseline year, summed from the daily series on disk."""

from __future__ import annotations

import calendar
from datetime import date

import numpy as np
import polars as pl

from .levels import ratio_level
from .months import round_int
from .store import Store

MIN_BASE_YEARS = 3
CELL_FILTER_LIMIT = 50_000  # above this many cells the parquet filter by cell costs more than it saves


def shift_to_year(d: date, year: int) -> date:
    """The same month and day in another year; 29 February falls back to 28 February."""
    if d.month == 2 and d.day == 29 and not calendar.isleap(year):
        return date(year, 2, 28)
    return date(year, d.month, d.day)


def window_in_year(start: date, end: date, year: int) -> tuple[date, date]:
    """The window as it falls in `year`; a window that crosses 31 December ends in the next year."""
    crosses = (end.month, end.day) < (start.month, start.day)
    return shift_to_year(start, year), shift_to_year(end, year + int(crosses))


def _read(store: Store, cell_ids: np.ndarray | None, start: date, end: date) -> pl.DataFrame:
    files = [store.root / "series_daily" / f"year={y}" / "part-0.parquet" for y in range(start.year, end.year + 1)]
    files = [f for f in files if f.exists()]
    if not files:
        return pl.DataFrame(schema={"cell_id": pl.Int64, "local_date": pl.Date, "sensor": pl.Utf8, "n_day": pl.Int64,
                                    "n_night": pl.Int64})
    lf = pl.scan_parquet(files).select(
        pl.col("cell_id").cast(pl.Int64),
        pl.col("local_date").cast(pl.Date),
        pl.col("sensor"),
        pl.col("n_day").cast(pl.Int64),
        pl.col("n_night").cast(pl.Int64),
    )
    lf = lf.filter((pl.col("local_date") >= start) & (pl.col("local_date") <= end))
    if cell_ids is not None:
        lf = lf.filter(pl.col("cell_id").is_in(cell_ids.tolist()))
    return lf.collect()


def by_day(store: Store, idx: np.ndarray, w: np.ndarray, start: date, end: date) -> dict:
    """Weighted harmonized fire count of the area for each local date start..end that has any."""
    n_rows = len(store.cells.cell_id)
    few = len(idx) < min(CELL_FILTER_LIMIT, n_rows)
    df = _read(store, store.cells.cell_id[idx] if few else None, start, end)
    if df.is_empty():
        return {}
    rows = store.cells.row_of[df["cell_id"].to_numpy()].astype(np.int64)
    weight = np.zeros(n_rows)
    weight[idx] = w
    keep = rows >= 0
    keep[keep] = weight[rows[keep]] > 0
    if not keep.any():
        return {}
    rows = rows[keep]
    n_day = df["n_day"].to_numpy()[keep]
    n_night = df["n_night"].to_numpy()[keep]
    sensor = df["sensor"].to_numpy()[keep]
    dates = df["local_date"]
    months = ((dates.dt.year() - 2000) * 12 + dates.dt.month() - 1).to_numpy()[keep]
    day_no = dates.cast(pl.Int32).to_numpy()[keep]  # days since 1970-01-01
    base = int(day_no.min())
    totals = np.zeros(int(day_no.max()) - base + 1)
    for name in np.unique(sensor):
        sel = sensor == name
        r, m = rows[sel], months[sel]
        k_d, _, miss_d = store.klookup.lookup(str(name), r, m, "D")
        k_n, _, miss_n = store.klookup.lookup(str(name), r, m, "N")
        store.klookup.check_missing(str(name), r, m, n_day[sel], "D", miss_d)
        store.klookup.check_missing(str(name), r, m, n_night[sel], "N", miss_n)
        totals += np.bincount(day_no[sel] - base, weights=weight[r] * (n_day[sel] * k_d + n_night[sel] * k_n),
                              minlength=len(totals))
    epoch = date(1970, 1, 1).toordinal()

    return {date.fromordinal(epoch + base + int(i)): float(v) for i, v in enumerate(totals) if v > 0}


def harmonized_total(store: Store, idx: np.ndarray, w: np.ndarray, start: date, end: date) -> float:
    """Weighted harmonized fire count of the area over local dates start..end."""
    return float(sum(by_day(store, idx, w, start, end).values()))


def same_dates(store: Store, idx: np.ndarray, w: np.ndarray, start: date, end: date) -> dict:
    """Count over start..end against the same dates in each baseline year: median, spread, rank and ratio."""
    values = []
    for year in store.base_years:
        s, e = window_in_year(start, end, year)
        if e > store.last_complete_date:
            continue
        values.append(round_int(harmonized_total(store, idx, w, s, e)))
    count = round_int(harmonized_total(store, idx, w, start, end))
    out = {"count": count, "median": None, "p10": None, "p90": None, "rank": None, "of": None, "ratio": None,
           "years": len(values)}
    if len(values) < MIN_BASE_YEARS:
        return out
    arr = np.array(values)
    out["median"] = round_int(np.median(arr))
    out["p10"] = round_int(np.percentile(arr, 10))
    out["p90"] = round_int(np.percentile(arr, 90))
    out["rank"] = 1 + int((arr > count).sum())
    out["of"] = len(values) + (0 if start.year in store.base_years else 1)
    out["ratio"], _ = ratio_level(count, out["median"])
    return out
