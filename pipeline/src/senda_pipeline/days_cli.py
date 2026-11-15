"""`senda-pipeline days`: constant-source mask and the chosen sensor per UTC date."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import polars as pl

from senda_pipeline import chain, config, mask


def _drop_masked_nrt(days_raw: pl.DataFrame, nrt_cells: pl.DataFrame, static_mask: pl.DataFrame) -> pl.DataFrame:
    """NRT rows in masked 0.01 deg cells are not counted, the same rule the build applies to rows."""
    if nrt_cells.is_empty() or static_mask.is_empty():
        return days_raw
    masked = (
        nrt_cells.join(static_mask, on=["sensor", "cell01"], how="semi")
        .group_by("utc_date", "sensor")
        .agg(pl.col("n").sum().alias("masked"))
    )
    return (
        days_raw.join(masked, on=["utc_date", "sensor"], how="left")
        .with_columns(
            pl.when(pl.col("source") == "nrt")
            .then(pl.col("rows") - pl.col("masked").fill_null(0))
            .otherwise(pl.col("rows"))
            .alias("rows")
        )
        .drop("masked")
    )


def compute(days_raw: pl.DataFrame, nrt_cells: pl.DataFrame, static_counts: pl.DataFrame):
    """Returns (days, static_mask). days: utc_date, sensor, rows:int32, ok, chosen, source."""
    static_mask = mask.build(static_counts)
    adjusted = _drop_masked_nrt(days_raw, nrt_cells, static_mask)
    days = chain.choose(chain.mark_ok(adjusted)).select(
        "utc_date", "sensor", pl.col("rows").cast(pl.Int32), "ok", "chosen", "source"
    )
    # the open tail after the last chosen date is not published: it still changes with every download
    days = days.filter(pl.col("utc_date") <= days.filter(pl.col("chosen"))["utc_date"].max())
    return days.sort("utc_date", "sensor"), static_mask


def report(days: pl.DataFrame) -> dict:
    life = {s: (a, b or date.max) for s, (a, b) in chain.LIFE.items()}
    alive = pl.concat(
        [
            days.filter((pl.col("sensor") == s) & pl.col("utc_date").is_between(a, b))
            for s, (a, b) in life.items()
        ]
    )
    per = (
        alive.group_by("sensor", pl.col("utc_date").dt.year().alias("year"))
        .agg(
            pl.len().alias("days"),
            (~pl.col("ok")).sum().alias("low"),
            pl.col("chosen").sum().alias("chosen"),
        )
        .sort("sensor", "year")
    )
    last = days["utc_date"].max()
    chosen_dates = days.filter(pl.col("chosen"))
    lows = alive.filter(~pl.col("ok")).sort("utc_date")
    return {
        "by_sensor_year": per.to_dicts(),
        "low_dates": {s: g["utc_date"].dt.to_string("%Y-%m-%d").to_list() for (s,), g in lows.group_by("sensor")},
        "gap_dates": [d.isoformat() for d in chain.gap_dates(days)],
        "incomplete_months": chain.incomplete_months(days, chain.SERIES_START, last),
        "last_data_date": last.isoformat(),
        "last_complete_date": chain.last_complete_date(days).isoformat(),
        "tail_chosen": [
            {"utc_date": r["utc_date"].isoformat(), "sensor": r["sensor"], "source": r["source"]}
            for r in chosen_dates.filter(pl.col("utc_date") >= date(2026, 10, 25)).to_dicts()
        ],
    }


def run(work: Path) -> None:
    days_raw = pl.read_parquet(work / "days_raw.parquet")
    static_counts = pl.read_parquet(work / "static_counts.parquet")
    nrt_path = work / "nrt_cells.parquet"
    nrt_cells = pl.read_parquet(nrt_path) if nrt_path.exists() else pl.DataFrame()
    days, static_mask = compute(days_raw, nrt_cells, static_counts)
    days.write_parquet(work / "days.parquet")
    static_mask.write_parquet(work / "static_mask.parquet")
    rep = report(days)
    rep["mask_cells_by_sensor"] = {
        r["sensor"]: r["n"] for r in static_mask.group_by("sensor").agg(pl.len().alias("n")).to_dicts()
    }
    (work / "days_report.json").write_text(json.dumps(rep, indent=1))
    low_total = sum(r["low"] for r in rep["by_sensor_year"])
    print(
        f"days: {days.height} rows, low days {low_total}, gaps {len(rep['gap_dates'])}, "
        f"incomplete months {len(rep['incomplete_months'])}, last complete {rep['last_complete_date']}"
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline days")
    ap.add_argument("--data", required=True, help="data root (contains _work/)")
    args = ap.parse_args(argv)
    run(config.paths(args.data).work)
    return 0
