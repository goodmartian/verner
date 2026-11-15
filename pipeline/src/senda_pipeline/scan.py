"""First pass over the archive: rows per (UTC date, sensor) after filters, and constant-source rows per cell."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

import polars as pl

from senda_pipeline import config, normalize

FLUSH_ROWS = 5_000_000


def peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


class _Acc:
    """Keeps partial group sums and folds them when too many rows are buffered."""

    def __init__(self, keys: list[str]):
        self.keys, self.parts, self.rows = keys, [], 0

    def add(self, df: pl.DataFrame) -> None:
        self.parts.append(df)
        self.rows += df.height
        if self.rows > FLUSH_ROWS:
            self.fold()

    def fold(self) -> None:
        if self.parts:
            merged = pl.concat(self.parts).group_by(self.keys).agg(pl.col("n").sum())
            self.parts, self.rows = [merged], merged.height

    def result(self, schema: dict[str, pl.DataType]) -> pl.DataFrame:
        self.fold()
        return self.parts[0] if self.parts else pl.DataFrame(schema=schema)


def run(zips: Path, api_dir: Path, work: Path) -> None:
    """Write work/days_raw.parquet, work/static_counts.parquet, work/nrt_cells.parquet, work/scan_report.json."""
    t0 = time.time()
    work.mkdir(parents=True, exist_ok=True)
    days = _Acc(["utc_date", "sensor", "source"])
    static = _Acc(["sensor", "year", "cell01"])
    nrt_cells = _Acc(["utc_date", "sensor", "cell01"])
    last_group, files = "", 0
    for group, source, df in normalize.iter_normalized(zips, api_dir):
        if group != last_group:
            print(f"[{time.time() - t0:7.1f}s] {group}  peak {peak_rss_mb():.0f} MB", flush=True)
            last_group = group
        files += 1
        veg = df.filter(pl.col("type").is_null() | (pl.col("type") == 0))
        days.add(veg.group_by("utc_date", "sensor", "source").agg(pl.len().alias("n")))
        if source == "sp":
            st = df.filter(pl.col("type").is_not_null() & (pl.col("type") != 0))
            static.add(
                st.group_by("sensor", pl.col("utc_date").dt.year().alias("year"), "cell01").agg(pl.len().alias("n"))
            )
        else:
            nrt_cells.add(veg.group_by("utc_date", "sensor", "cell01").agg(pl.len().alias("n")))

    d = days.result({"utc_date": pl.Date, "sensor": pl.String, "source": pl.String, "n": pl.UInt32})
    sp_keys = d.filter(pl.col("source") == "sp").select("utc_date", "sensor")
    d = d.join(sp_keys, on=["utc_date", "sensor"], how="anti").vstack(d.filter(pl.col("source") == "sp"))
    days_raw = d.select("utc_date", "sensor", "source", pl.col("n").cast(pl.Int64).alias("rows")).sort(
        "utc_date", "sensor"
    )
    days_raw.write_parquet(work / "days_raw.parquet")

    sc = static.result({"sensor": pl.String, "year": pl.Int32, "cell01": pl.Int64, "n": pl.UInt32})
    sc.select("sensor", pl.col("year").cast(pl.Int32), "cell01", pl.col("n").cast(pl.Int64)).sort(
        "sensor", "year", "cell01"
    ).write_parquet(work / "static_counts.parquet")

    nc = nrt_cells.result({"utc_date": pl.Date, "sensor": pl.String, "cell01": pl.Int64, "n": pl.UInt32})
    nc = nc.join(sp_keys, on=["utc_date", "sensor"], how="anti")  # SP wins on dates that have both
    nc.select("utc_date", "sensor", "cell01", pl.col("n").cast(pl.Int64)).write_parquet(work / "nrt_cells.parquet")

    by = (
        days_raw.group_by("sensor", "source", pl.col("utc_date").dt.year().alias("year"))
        .agg(pl.col("rows").sum())
        .sort("sensor", "source", "year")
    )
    stat = sc.group_by("sensor", "year").agg(pl.col("n").sum()).sort("sensor", "year")
    report = {
        "files": files,
        "seconds": round(time.time() - t0, 1),
        "peak_rss_mb": round(peak_rss_mb()),
        "rows_by_sensor": {r["sensor"]: r["rows"] for r in days_raw.group_by("sensor").agg(pl.col("rows").sum()).to_dicts()},
        "rows_by_sensor_source_year": by.to_dicts(),
        "static_rows_by_sensor_year": stat.to_dicts(),
    }
    (work / "scan_report.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report["rows_by_sensor"]), f"in {report['seconds']} s, peak {report['peak_rss_mb']} MB")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline scan")
    ap.add_argument("--data", required=True, help="data root (contains _work/)")
    args = ap.parse_args(argv)
    p = config.paths(args.data)
    normalize.require_archives(p.zips)
    run(p.zips, p.api, p.work)
    return 0
