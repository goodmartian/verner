"""Choose one sensor per UTC date and find gaps and incomplete months."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import numpy as np
import polars as pl
from numpy.lib.stride_tricks import sliding_window_view

LOW_RATIO = 0.4
HALF_WINDOW = 15
MIN_NEIGHBOURS = 10
SNPP_SERIES_START = date(2012, 2, 1)
SNPP_RETIRED = date(2026, 11, 2)
SERIES_START = date(2000, 11, 1)  # the first month of MODIS Terra in the archive
AQUA_START = date(2002, 7, 4)  # modis_terra is in the chain only before this date

# first and last day of work (inclusive); None means open end
LIFE: dict[str, tuple[date, date | None]] = {
    "modis_terra": (SERIES_START, None),
    "modis_aqua": (AQUA_START, None),
    "viirs_snpp": (date(2012, 1, 20), date(2026, 11, 1)),
    "viirs_noaa20": (date(2018, 4, 1), None),
}


def _source_col(df: pl.DataFrame) -> pl.DataFrame:
    return df if "source" in df.columns else df.with_columns(pl.lit("sp").alias("source"))


def _ok_flags(rows: np.ndarray) -> np.ndarray:
    """ok for a dense daily array of rows: not below LOW_RATIO of the median of 15 days either side, self excluded."""
    n = len(rows)
    pad = np.full(n + 2 * HALF_WINDOW, np.nan)
    pad[HALF_WINDOW : HALF_WINDOW + n] = rows
    win = sliding_window_view(pad, 2 * HALF_WINDOW + 1).copy()
    win[:, HALF_WINDOW] = np.nan
    count = (~np.isnan(win)).sum(axis=1)
    med = np.full(n, np.nan)
    enough = count >= MIN_NEIGHBOURS
    if enough.any():
        med[enough] = np.nanmedian(win[enough], axis=1)
    return (rows > 0) & (~enough | (rows >= LOW_RATIO * np.nan_to_num(med)))


def mark_ok(days_raw: pl.DataFrame) -> pl.DataFrame:
    """Add `ok`. Dates inside a sensor's life without a row get rows = 0. Outside the life, ok is False."""
    df = _source_col(days_raw).group_by("utc_date", "sensor", "source").agg(pl.col("rows").sum())
    if df.is_empty():
        return df.with_columns(pl.lit(False).alias("ok"))
    last = df["utc_date"].max()
    last_sp = df.filter(pl.col("source") == "sp")["utc_date"].max()
    parts = []
    for sensor, sdf in df.group_by("sensor", maintain_order=True):
        sensor = sensor[0]
        start, end = LIFE.get(sensor, (sdf["utc_date"].min(), None))
        end = min(end, last) if end else last
        if end < start:  # all rows of this sensor are before its life
            parts.append(sdf.with_columns(pl.lit(False).alias("ok")))
            continue
        full = pl.DataFrame({"utc_date": pl.date_range(start, end, "1d", eager=True)}).with_columns(
            pl.lit(sensor).alias("sensor")
        )
        inside = sdf.filter(pl.col("utc_date").is_between(start, end))
        outside = sdf.filter(~pl.col("utc_date").is_between(start, end)).with_columns(pl.lit(False).alias("ok"))
        j = full.join(inside, on=["utc_date", "sensor"], how="left").with_columns(
            pl.col("rows").fill_null(0),
            pl.col("source").fill_null(
                pl.when(pl.col("utc_date") <= last_sp).then(pl.lit("sp")).otherwise(pl.lit("nrt"))
            ),
        )
        ok = _ok_flags(j["rows"].cast(pl.Float64).to_numpy())
        parts.append(j.with_columns(pl.Series("ok", ok)))
        parts.append(outside)
    out = pl.concat([p.select("utc_date", "sensor", "rows", "source", "ok") for p in parts])
    return out.sort("utc_date", "sensor")


def _priority(date_col: pl.Expr, sensor: pl.Expr) -> pl.Expr:
    """Position of the sensor in the chain of the date; null if the sensor is not in the chain."""
    before = date_col < SNPP_SERIES_START
    after = date_col >= SNPP_RETIRED
    return (
        pl.when(sensor == "modis_terra")
        .then(pl.when(date_col < AQUA_START).then(0).otherwise(None))
        .when(sensor == "modis_aqua")
        .then(pl.when(before).then(0).when(after).then(1).otherwise(2))
        .when(sensor == "viirs_snpp")
        .then(pl.when(before | after).then(None).otherwise(0))
        .when(sensor == "viirs_noaa20")
        .then(pl.when(before).then(None).when(after).then(0).otherwise(1))
        .otherwise(None)
    )


def choose(days: pl.DataFrame) -> pl.DataFrame:
    """Add `chosen`: first ok sensor of the chain per date. The last NRT date is partial and is not chosen."""
    days = _source_col(days).drop("chosen", strict=False)
    if days.is_empty():
        return days.with_columns(pl.lit(False).alias("chosen"))
    last = days["utc_date"].max()
    partial = days.filter((pl.col("utc_date") == last) & (pl.col("source") == "nrt")).height > 0
    pri = _priority(pl.col("utc_date"), pl.col("sensor")).alias("pri")
    elig = days.filter(pl.col("ok")).with_columns(pri).filter(pl.col("pri").is_not_null())
    if partial:
        elig = elig.filter(pl.col("utc_date") != last)
    picked = (
        elig.sort("utc_date", "pri")
        .group_by("utc_date", maintain_order=True)
        .first()
        .select("utc_date", "sensor", pl.lit(True).alias("chosen"))
    )
    return days.join(picked, on=["utc_date", "sensor"], how="left").with_columns(pl.col("chosen").fill_null(False))


def _chosen_dates(days: pl.DataFrame) -> set[date]:
    return set(days.filter(pl.col("chosen"))["utc_date"].to_list())


def last_complete_date(days: pl.DataFrame) -> date:
    """Last chosen UTC date minus one day: the local date after it still needs the next UTC date."""
    return days.filter(pl.col("chosen"))["utc_date"].max() - timedelta(days=1)


def gap_dates(days: pl.DataFrame) -> list[date]:
    """Dates from SERIES_START to the last chosen date that have no chosen sensor."""
    chosen = _chosen_dates(days)
    if not chosen:
        return []
    d, end, out = max(SERIES_START, min(chosen)), max(chosen), []
    while d <= end:
        if d not in chosen:
            out.append(d)
        d += timedelta(days=1)
    return out


def incomplete_months(days: pl.DataFrame, first: date, last: date) -> list[str]:
    """Months (YYYY-MM) touching [first, last] with a non-chosen UTC date from (first day - 1) to (last day + 1)."""
    chosen = _chosen_dates(days)
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        a = date(y, m, 1) - timedelta(days=1)
        b = date(y, m, calendar.monthrange(y, m)[1]) + timedelta(days=1)
        d = a
        while d <= b:
            if d not in chosen:
                out.append(f"{y:04d}-{m:02d}")
                break
            d += timedelta(days=1)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out
