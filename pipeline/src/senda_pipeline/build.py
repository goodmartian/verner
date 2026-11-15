"""Second pass: monthly and daily tables, hotspots of the series, and paired counts for the fits.

Every input file is reduced to small grouped chunks that go to disk (`_spill`). The final step folds the chunks
of each output and writes it, so memory holds one file of the archive plus one output at a time.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import polars as pl

from senda_pipeline import chain, config, grid, normalize
from senda_pipeline.scan import peak_rss_mb

# (source, reference): counts on UTC dates where both passed the day check; modis_terra__modis_aqua checks Terra
PAIRS = [
    ("modis_aqua", "viirs_snpp"),
    ("viirs_noaa20", "viirs_snpp"),
    ("modis_terra", "viirs_snpp"),
    ("modis_terra", "modis_aqua"),
]
FLUSH_ROWS = 4_000_000

ROW_COLS = ["lat", "lon", "acq_utc", "local_date", "sensor", "frp_mw", "confidence", "daynight", "source"]


class Spill:
    """Buffers small tables per name and writes them as numbered parquet chunks; sums rows with equal keys."""

    def __init__(self, root: Path, keys: dict[str, list[str] | None]):
        self.root, self.keys, self.buf, self.count, self.rows = root, keys, {}, {}, 0

    def _keys(self, name: str):
        return self.keys[name.split("/")[0]]

    def add(self, name: str, df: pl.DataFrame) -> None:
        if df.is_empty():
            return
        self.buf.setdefault(name, []).append(df)
        self.rows += df.height
        if self.rows > FLUSH_ROWS:
            self.flush()

    def flush(self) -> None:
        for name, parts in self.buf.items():
            df = pl.concat(parts)
            keys = self._keys(name)
            if keys:
                df = df.group_by(keys).agg(pl.exclude(keys).sum())
            folder = self.root / name
            folder.mkdir(parents=True, exist_ok=True)
            n = self.count.get(name, 0)
            df.write_parquet(folder / f"{n:06d}.parquet")
            self.count[name] = n + 1
        self.buf, self.rows = {}, 0

    def names(self, prefix: str) -> list[str]:
        return sorted(n for n in self.count if n == prefix or n.startswith(prefix + "/"))

    def scan(self, name: str) -> pl.LazyFrame:
        return pl.scan_parquet(self.root / name / "*.parquet")


def _prepare(df: pl.DataFrame, source: str, days: pl.DataFrame, mask: pl.DataFrame) -> pl.DataFrame:
    """Vegetation fire rows only, with the day flags of their (UTC date, sensor). Source must match the days table."""
    if source == "sp":
        df = df.filter(pl.col("type").is_null() | (pl.col("type") == 0))
    else:
        df = df.join(mask, on=["sensor", "cell01"], how="anti")
    return (
        df.join(days, on=["utc_date", "sensor"], how="inner")
        .filter(pl.col("source") == pl.col("day_source"))
        .with_columns((pl.col("daynight") == "D").alias("day"))
    )


def _counts(day: pl.Expr) -> list[pl.Expr]:
    return [day.sum().cast(pl.Int64).alias("n_day"), (~day).sum().cast(pl.Int64).alias("n_night")]


def _pair_dates(days: pl.DataFrame) -> dict[tuple[str, str], pl.DataFrame]:
    ok = days.filter(pl.col("ok")).select("utc_date", "sensor")
    out = {}
    for src, dst in PAIRS:
        both = ok.filter(pl.col("sensor") == src).join(ok.filter(pl.col("sensor") == dst), on="utc_date", how="semi")
        out[(src, dst)] = both.select("utc_date")
    return out


def _consume(df: pl.DataFrame, spill: Spill, pair_dates: dict, series_end) -> None:
    # the one cut for every table: rows of local dates after the last complete date are not published
    df = df.filter(pl.col("local_date") <= series_end)
    day, frp = pl.col("day"), pl.col("frp_mw").fill_null(0).cast(pl.Float64)
    key = ["cell_id", "month", "sensor"]
    spill.add(
        "monthly",
        df.group_by(key).agg(*_counts(day), frp.sum().alias("frp_mw")),
    )
    # the series starts at SERIES_START; monthly (fits) also keeps the years before it
    c = df.filter(pl.col("chosen") & pl.col("local_date").is_between(chain.SERIES_START, series_end))
    if not c.is_empty():
        spill.add(
            "smonthly",
            c.group_by(key).agg(
                *_counts(day),
                pl.when(day).then(frp).otherwise(0.0).sum().alias("frp_day"),
                pl.when(~day).then(frp).otherwise(0.0).sum().alias("frp_night"),
            ),
        )
        sd = c.group_by("cell_id", "local_date", "sensor").agg(*_counts(day))
        for (year,), g in sd.group_by(pl.col("local_date").dt.year().alias("year")):
            spill.add(f"sdaily/{year}", g.drop("year", strict=False))
        rows = c.select(
            pl.col("lat").cast(pl.Float32),
            pl.col("lon").cast(pl.Float32),
            *ROW_COLS[2:],
            pl.col("local_date").dt.year().alias("year"),
            grid.tile(pl.col("lat"), pl.col("lon")),
        )
        for (year, tile), g in rows.partition_by("year", "tile", as_dict=True).items():
            spill.add(f"rows/{year}/{tile}", g.drop("year", "tile"))
    dn = pl.when(day).then(pl.lit("D")).otherwise(pl.lit("N")).alias("dn")
    for (src, dst), pdates in pair_dates.items():
        sub = df.filter(pl.col("sensor").is_in([src, dst])).join(pdates, on="utc_date", how="semi")
        if not sub.is_empty():
            spill.add(
                f"pairs/{src}__{dst}",
                sub.group_by("cell_id", "month", dn, "sensor").agg(pl.len().cast(pl.Int64).alias("n")),
            )


def _year_of_month(month: pl.Expr) -> pl.Expr:
    return (2000 + month.cast(pl.Int32) // 12).alias("year")


def _finish_monthly(spill: Spill, out: Path, name: str, file: str) -> dict:
    df = spill.scan(name).group_by("cell_id", "month", "sensor").agg(pl.all().exclude("cell_id", "month", "sensor").sum()).collect()
    cast = {"cell_id": pl.Int32, "month": pl.Int16, "n_day": pl.Int32, "n_night": pl.Int32}
    cast |= {c: pl.Float32 for c in df.columns if c.startswith("frp")}
    df = df.cast(cast).sort("month", "cell_id", "sensor")
    df.write_parquet(out / file)
    sums = df.group_by(_year_of_month(pl.col("month")), "sensor").agg((pl.col("n_day") + pl.col("n_night")).sum().alias("n"))
    return {(r["year"], r["sensor"]): r["n"] for r in sums.to_dicts()}


def _finish_daily(spill: Spill, out: Path) -> dict:
    sums = {}
    for name in spill.names("sdaily"):
        year = int(name.split("/")[1])
        df = (
            spill.scan(name)
            .group_by("cell_id", "local_date", "sensor")
            .agg(pl.col("n_day").sum(), pl.col("n_night").sum())
            .collect()
            .cast({"cell_id": pl.Int32, "n_day": pl.Int32, "n_night": pl.Int32})
            .sort("local_date", "cell_id", "sensor")
        )
        folder = out / "series_daily" / f"year={year}"
        folder.mkdir(parents=True, exist_ok=True)
        df.select("cell_id", "local_date", "sensor", "n_day", "n_night").write_parquet(
            folder / "part-0.parquet", row_group_size=100_000
        )
        for r in df.group_by("sensor").agg((pl.col("n_day") + pl.col("n_night")).sum().alias("n")).to_dicts():
            sums[(year, r["sensor"])] = r["n"]
    return sums


def _finish_rows(spill: Spill, out: Path) -> dict:
    counts = {}
    for name in spill.names("rows"):
        _, year, tile = name.split("/")
        df = spill.scan(name).collect().sort("acq_utc", "lat", "lon").select(ROW_COLS)
        folder = out / "rows" / f"year={year}" / f"tile={tile}"
        folder.mkdir(parents=True, exist_ok=True)
        df.write_parquet(folder / "part-0.parquet")
        for r in df.group_by("sensor").len().to_dicts():
            counts[(int(year), r["sensor"])] = counts.get((int(year), r["sensor"]), 0) + r["len"]
    return counts


def _finish_pairs(spill: Spill, out: Path, pair_dates: dict) -> None:
    folder = out / "pairs"
    folder.mkdir(parents=True, exist_ok=True)
    schema = {"cell_id": pl.Int32, "month": pl.Int16, "dn": pl.String, "n_src": pl.Int32, "n_dst": pl.Int32}
    for (src, dst), pdates in pair_dates.items():
        name = f"pairs/{src}__{dst}"
        if name in spill.count:
            g = spill.scan(name).group_by("cell_id", "month", "dn", "sensor").agg(pl.col("n").sum()).collect()
            a = g.filter(pl.col("sensor") == src).select("cell_id", "month", "dn", pl.col("n").alias("n_src"))
            b = g.filter(pl.col("sensor") == dst).select("cell_id", "month", "dn", pl.col("n").alias("n_dst"))
            res = a.join(b, on=["cell_id", "month", "dn"], how="full", coalesce=True).with_columns(
                pl.col("n_src").fill_null(0), pl.col("n_dst").fill_null(0)
            )
            res = res.cast(schema).sort("month", "cell_id", "dn")
        else:
            res = pl.DataFrame(schema=schema)
        res.write_parquet(folder / f"{src}__{dst}.parquet")
        nd = (
            pdates.group_by(grid.month_expr(pl.col("utc_date")).alias("month"))
            .agg(pl.len().cast(pl.Int16).alias("n_days"))
            .sort("month")
        )
        nd.write_parquet(folder / f"{src}__{dst}__days.parquet")


def run(zips: Path, api_dir: Path, work: Path) -> None:
    """Needs work/days.parquet and work/static_mask.parquet (from `days`). Writes work/built/."""
    t0 = time.time()
    days_all = pl.read_parquet(work / "days.parquet")
    days = days_all.select("utc_date", "sensor", "ok", "chosen", pl.col("source").alias("day_source"))
    mask = pl.read_parquet(work / "static_mask.parquet")
    pair_dates = _pair_dates(days_all)
    series_end = chain.last_complete_date(days_all)
    out = work / "built"
    # only this command's outputs are replaced: cells, regions and factors live in the same folder
    for name in ("monthly.parquet", "series_monthly.parquet", "series_daily", "rows", "pairs", "_spill", "build_report.json"):
        target = out / name
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    spill = Spill(
        out / "_spill",
        {
            "monthly": ["cell_id", "month", "sensor"],
            "smonthly": ["cell_id", "month", "sensor"],
            "sdaily": ["cell_id", "local_date", "sensor"],
            "rows": None,
            "pairs": ["cell_id", "month", "dn", "sensor"],
        },
    )
    last_group, kept = "", 0
    for group, source, df in normalize.iter_normalized(zips, api_dir):
        if group != last_group:
            print(f"[{time.time() - t0:7.1f}s] {group}  peak {peak_rss_mb():.0f} MB", flush=True)
            last_group = group
        prepared = _prepare(df, source, days, mask)
        kept += prepared.height
        _consume(prepared, spill, pair_dates, series_end)
    spill.flush()

    m_sum = _finish_monthly(spill, out, "monthly", "monthly.parquet")
    sm_sum = _finish_monthly(spill, out, "smonthly", "series_monthly.parquet")
    sd_sum = _finish_daily(spill, out)
    row_cnt = _finish_rows(spill, out)
    _finish_pairs(spill, out, pair_dates)
    shutil.rmtree(out / "_spill")

    keys = sorted(set(sm_sum) | set(sd_sum) | set(row_cnt))
    table = [
        {
            "year": y,
            "sensor": s,
            "monthly": m_sum.get((y, s), 0),
            "series_monthly": sm_sum.get((y, s), 0),
            "series_daily": sd_sum.get((y, s), 0),
            "rows": row_cnt.get((y, s), 0),
            "agree": sm_sum.get((y, s), 0) == sd_sum.get((y, s), 0) == row_cnt.get((y, s), 0),
        }
        for y, s in keys
    ]
    report = {
        "seconds": round(time.time() - t0, 1),
        "peak_rss_mb": round(peak_rss_mb()),
        "rows_kept": kept,
        "all_agree": all(r["agree"] for r in table),
        "by_year_sensor": table,
        "monthly_rows_by_sensor": {
            s: sum(v for (_, k), v in m_sum.items() if k == s) for s in sorted({k for _, k in m_sum})
        },
    }
    (out / "build_report.json").write_text(json.dumps(report, indent=1))
    print(f"build done in {report['seconds']} s, peak {report['peak_rss_mb']} MB, sums agree: {report['all_agree']}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline build")
    ap.add_argument("--data", required=True, help="data root (contains _work/)")
    args = ap.parse_args(argv)
    p = config.paths(args.data)
    normalize.require_archives(p.zips)
    run(p.zips, p.api, p.work)
    return 0
