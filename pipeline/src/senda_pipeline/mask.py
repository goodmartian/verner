"""Mask of constant sources: 0.01 deg cells that hold type != 0 hotspots in most recent years of SP data."""

from __future__ import annotations

import polars as pl

YEARS = 3
MIN_YEARS = 2


def build(static_counts: pl.DataFrame, last_year: int | None = None) -> pl.DataFrame:
    """(sensor, cell01) in the mask: n > 0 in at least 2 of the last 3 years of SP data.

    `last_year` defaults to the newest year in `static_counts` (all sensors share the newest SP year).
    """
    if static_counts.is_empty():
        return pl.DataFrame(schema={"sensor": pl.String, "cell01": pl.Int64})
    last = last_year if last_year is not None else static_counts["year"].max()
    return (
        static_counts.filter((pl.col("n") > 0) & pl.col("year").is_between(last - YEARS + 1, last))
        .group_by("sensor", "cell01")
        .agg(pl.col("year").n_unique().alias("years"))
        .filter(pl.col("years") >= MIN_YEARS)
        .select(pl.col("sensor"), pl.col("cell01").cast(pl.Int64))
        .sort("sensor", "cell01")
    )
