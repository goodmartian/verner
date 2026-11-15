"""senda-pipeline seam: check the joins of the unified series with dates that carry no join.

A join is a moment where the source sensor changes. Ratio = count of the 12 months after / the 12 months before.
The sensor present on both sides (MODIS Aqua for 2012-02, NOAA-20 for 2026-11) shows how the activity itself changed,
so the reference is that ratio and not 1. Placebo = the same ratio on every 1 February without a join.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from . import chain, config, fit

REFERENCE = "viirs_snpp"
SEAM_MONTH = (chain.SNPP_SERIES_START.year - 2000) * 12 + chain.SNPP_SERIES_START.month - 1
RECENT_START = (2022 - 2000) * 12  # months from 2022-01 use the "recent" window of modis_aqua (api store.py)
WINDOW = 12
PLACEBO_FIRST = (2003 - 2000) * 12  # placebo windows start at 2003-01: the first full year of raw MODIS Aqua
PLACEBO_MONTH = 2  # calendar month the windows start at, the month of the real join
MIN_COUNT = 500  # hotspots a window needs on both sides, else the slice is not judged
MIN_PLACEBO = 5  # placebo years a slice needs to be judged
SHORT_BEFORE_DAYS = 30
SHORT_MIN_SHARE = 0.8  # share of the days of a short window that must have data
EXTRA_COUNTRIES = ("AR", "BR")


def month_index(year: int, month: int) -> int:
    return (year - 2000) * 12 + month - 1


def month_text(m: int) -> str:
    return f"{2000 + m // 12:04d}-{m % 12 + 1:02d}"


# ---------------------------------------------------------------- pure: monthly joins

def seam_ratios(series: dict[str, np.ndarray], m0: int, n: int = WINDOW, min_count: float = MIN_COUNT) -> dict[str, float]:
    """after / before for each series (dense arrays by absolute month); NaN when a window holds too few hotspots."""
    out = {}
    for name, x in series.items():
        before, after = float(x[m0 - n : m0].sum()), float(x[m0 : m0 + n].sum())
        out[name] = after / before if before >= min_count and after >= min_count else float("nan")
    return out


def with_gap(r: dict[str, float]) -> dict[str, float]:
    """Add `gap` = ours / modis - 1 and `as_is_gap`: how far each series is from the sensor present on both sides."""
    return {**r, "gap": r["ours"] / r["modis"] - 1, "as_is_gap": r["as_is"] / r["modis"] - 1}


def placebo_years(first: int, last: int, seam: int = SEAM_MONTH, n: int = WINDOW) -> dict[str, list[int]]:
    """Years whose windows [m0 - n, m0 + n) lie inside [first, last] and do not cross the join, by sensor era."""
    out: dict[str, list[int]] = {"modis_era": [], "viirs_era": []}
    for y in range(2000, 2100):
        m0 = month_index(y, PLACEBO_MONTH)
        if m0 - n < first or m0 + n - 1 > last or m0 == seam:
            continue
        if m0 + n - 1 < seam:
            out["modis_era"].append(y)
        elif m0 - n >= seam:
            out["viirs_era"].append(y)
    return out


def placebo(series: dict[str, np.ndarray], years: list[int]) -> list[dict]:
    return [{"year": y, **with_gap(seam_ratios(series, month_index(y, PLACEBO_MONTH)))} for y in years]


def _finite(values) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    return v[np.isfinite(v)]


def percentile_of(x: float, sample) -> float | None:
    """Share of the sample at or below x, in percent (ties count half)."""
    s = _finite(sample)
    if not np.isfinite(x) or len(s) == 0:
        return None
    return float(100 * ((s < x).sum() + 0.5 * (s == x).sum()) / len(s))


def z_log(x: float, sample) -> float | None:
    s = np.log(_finite(sample)[_finite(sample) > 0])
    if not np.isfinite(x) or x <= 0 or len(s) < 3 or s.std(ddof=1) == 0:
        return None
    return float((np.log(x) - s.mean()) / s.std(ddof=1))


def summary(values) -> dict:
    v = _finite(values)
    if len(v) == 0:
        return {"n": 0, "median": None, "p10": None, "p90": None, "std": None, "min": None, "max": None}
    return {
        "n": len(v),
        "median": float(np.median(v)),
        "p10": float(np.percentile(v, 10)),
        "p90": float(np.percentile(v, 90)),
        "std": float(v.std(ddof=1)) if len(v) > 1 else None,
        "min": float(v.min()),
        "max": float(v.max()),
    }


def judge(gap: float, placebo_gaps) -> dict:
    """Pass when |gap| of the join is not above the 90th percentile of |gap| on joins without a sensor change.

    Only the VIIRS era is used: there our series and MODIS are two independent sensors, so the placebo gap is the
    ordinary disagreement of their year to year changes. In the MODIS era the gap is the conversion itself.
    """
    g = _finite(placebo_gaps)
    if not np.isfinite(gap) or len(g) < MIN_PLACEBO:
        return {"status": "insufficient", "placebo_gap_p90_abs": None}
    limit = float(np.percentile(np.abs(g), 90))
    return {"status": "pass" if abs(gap) <= limit else "fail", "placebo_gap_p90_abs": limit}


def evaluate(series: dict[str, np.ndarray], years: dict[str, list[int]], seam: int = SEAM_MONTH) -> dict:
    """Join ratios, placebo rows and the verdict of one slice."""
    real = with_gap(seam_ratios(series, seam))
    plc = {era: placebo(series, ys) for era, ys in years.items()}
    pooled = [r["ours"] for rows in plc.values() for r in rows]
    verdict = judge(real["gap"], [r["gap"] for r in plc["viirs_era"]])
    return {
        "seam": real,
        "ours_percentile": percentile_of(real["ours"], pooled),
        "ours_z": z_log(real["ours"], pooled),
        "as_is_percentile": percentile_of(real["as_is"], pooled),
        "as_is_z": z_log(real["as_is"], pooled),
        "placebo": plc,
        "placebo_ratio": {era: summary([r["ours"] for r in rows]) for era, rows in plc.items()}
        | {"all": summary(pooled)},
        "placebo_gap": {era: summary([r["gap"] for r in rows]) for era, rows in plc.items()},
        "placebo_change_median_abs": None if not _finite(pooled).size else float(np.median(np.abs(_finite(pooled) - 1))),
        **verdict,
    }


def headline(world: dict) -> dict:
    """The one sentence of the check as numbers."""
    r = world["seam"]
    ratio = world["placebo_ratio"]["all"]
    out = {
        "naive_jump": r["as_is"],
        "naive_jump_vs_modis": r["as_is"] / r["modis"],
        "modis_ratio": r["modis"],
        "ours_ratio": r["ours"],
        "ours_gap_pct": 100 * r["gap"],
        "ours_percentile": world["ours_percentile"],
        "ours_z": world["ours_z"],
        "naive_percentile": world["as_is_percentile"],
        "naive_z": world["as_is_z"],
        "placebo_median": ratio["median"],
        "placebo_p10": ratio["p10"],
        "placebo_p90": ratio["p90"],
        "placebo_typical_change_pct": None
        if world["placebo_change_median_abs"] is None
        else 100 * world["placebo_change_median_abs"],
        "placebo_gap_p90_abs_pct": None if world["placebo_gap_p90_abs"] is None else 100 * world["placebo_gap_p90_abs"],
        "status": world["status"],
    }
    change = out["placebo_typical_change_pct"]
    typical = "not known (too few years to compare)" if change is None else f"{change:.1f}%"
    out["text"] = (
        f"Spliced as is, the series jumps {out['naive_jump']:.2f} times at 2012-02 "
        f"({out['naive_jump_vs_modis']:.2f} times what MODIS alone shows); "
        f"ours differs from MODIS alone by {out['ours_gap_pct']:+.1f}%; "
        f"the usual year to year change without a sensor change is {typical}."
    )
    return out


# ---------------------------------------------------------------- pure: short join of 2026-11

def day_mean(counts: dict[date, float], start: date, end: date, min_share: float = SHORT_MIN_SHARE) -> float:
    """Mean per day over the dates of [start, end] that have a count; NaN when too few days have one."""
    days = (end - start).days + 1
    vals = [counts[d] for i in range(days) if (d := start + timedelta(days=i)) in counts]
    return float(np.mean(vals)) if days > 0 and len(vals) >= min_share * days else float("nan")


def short_ratio(counts: dict[date, float], seam: date, last: date, before_days: int = SHORT_BEFORE_DAYS) -> float:
    """Mean per day from the join to `last` over the mean per day of the `before_days` days before it."""
    before = day_mean(counts, seam - timedelta(days=before_days), seam - timedelta(days=1))
    after = day_mean(counts, seam, last)
    return after / before if before > 0 else float("nan")


def short_seam(
    ours: dict[date, float],
    as_is: dict[date, float],
    ref: dict[date, float],
    snpp: dict[date, float],
    noaa: dict[date, float],
    seam: date,
    last: date,
    first_year: int,
) -> dict:
    """The short join. `ours`, `as_is` come from the series, `ref` is the sensor on both sides (NOAA-20), `snpp` and
    `noaa` are the raw daily counts used for the placebo of the same calendar dates in earlier years."""
    r = with_gap(
        {
            "as_is": short_ratio(as_is, seam, last),
            "ours": short_ratio(ours, seam, last),
            "modis": short_ratio(ref, seam, last),  # key `modis` is the reference sensor of this join
        }
    )
    rows = []
    for y in range(first_year, seam.year):
        s, e = seam.replace(year=y), last.replace(year=y)
        a, b = short_ratio(snpp, s, e), short_ratio(noaa, s, e)
        rows.append({"year": y, "ours": a, "ref": b, "gap": a / b - 1 if b > 0 else float("nan")})
    ratios = [x["ours"] for x in rows]
    verdict = judge(r["gap"], [x["gap"] for x in rows])
    return {
        "seam": r,
        "before_days": SHORT_BEFORE_DAYS,
        "after_days": (last - seam).days + 1,
        "ours_percentile": percentile_of(r["ours"], ratios),
        "ours_z": z_log(r["ours"], ratios),
        "as_is_percentile": percentile_of(r["as_is"], ratios),
        "placebo": rows,
        "placebo_ratio": summary(ratios),
        "placebo_gap": summary([x["gap"] for x in rows]),
        **verdict,
    }


# ---------------------------------------------------------------- data: cubes of counts and factors

def _cell_table(built: Path) -> pl.DataFrame:
    """cell_id, zone, country, kgroup with the same fallbacks as harmonize.cell_groups."""
    cells = pl.read_parquet(built / "cells.parquet", columns=["cell_id", "zone", "country"])
    zone = pl.col("zone").fill_null("none")
    return cells.join(pl.read_parquet(built / "cell_groups.parquet"), on="cell_id").select(
        "cell_id",
        pl.when(zone == "none").then(pl.lit("global")).otherwise(zone).alias("zone"),
        pl.col("country").fill_null("ZZ"),
        "kgroup",
    )


def apply_k(df: pl.DataFrame, factors: pl.DataFrame) -> pl.DataFrame:
    """Add `raw` and `conv` (count on the VIIRS S-NPP scale). Needs kgroup, sensor, calmonth, recent, n_day, n_night."""
    f = factors.with_columns((pl.col("window") == "recent").alias("recent"))
    keys = ["kgroup", "sensor", "calmonth", "recent"]
    day = f.filter(pl.col("dn") == "D").select(*keys, pl.col("k").alias("k_d"))
    night = f.filter(pl.col("dn") == "N").select(*keys, pl.col("k").alias("k_n"))
    df = df.join(day, on=keys, how="left").join(night, on=keys, how="left")
    ref = pl.col("sensor") == REFERENCE
    lost = df.filter(~ref & (pl.col("k_d").is_null() | pl.col("k_n").is_null()) & ((pl.col("n_day") + pl.col("n_night")) > 0))
    if len(lost):
        raise ValueError(f"no conversion factor for {lost.height} count rows, e.g. {lost.head(3).to_dicts()}")
    d, n = pl.col("n_day").cast(pl.Float64), pl.col("n_night").cast(pl.Float64)
    return df.with_columns(
        (d + n).alias("raw"),
        pl.when(ref).then(d + n).otherwise(d * pl.col("k_d") + n * pl.col("k_n")).alias("conv"),
    ).drop("k_d", "k_n")


def _cube(path: Path, cells: pl.DataFrame, factors: pl.DataFrame) -> pl.DataFrame:
    """Counts per (zone, country, kgroup, month, sensor): raw and converted."""
    df = (
        pl.scan_parquet(path)
        .join(cells.lazy(), on="cell_id")
        .group_by("zone", "country", "kgroup", "month", "sensor")
        .agg(pl.col("n_day").sum(), pl.col("n_night").sum())
        .collect(engine="streaming")
    )
    df = df.with_columns(
        (pl.col("month") % 12 + 1).cast(pl.Int8).alias("calmonth"),
        ((pl.col("sensor") == "modis_aqua") & (pl.col("month") >= RECENT_START)).alias("recent"),
    )
    return apply_k(df, factors)


def _dense(frame: pl.DataFrame, col: str, size: int) -> np.ndarray:
    out = np.zeros(size)
    if len(frame):
        out[frame["month"].to_numpy().astype(np.int64)] = frame[col].to_numpy()
    return out


def slice_series(chain_cube: pl.DataFrame, all_cube: pl.DataFrame, kind: str, name: str, size: int) -> dict[str, np.ndarray]:
    """as_is (series counts), ours (series counts converted) and modis (raw Aqua) of one slice."""
    def pick(cube: pl.DataFrame) -> pl.DataFrame:
        return cube if kind == "world" else cube.filter(pl.col(kind) == name)

    s = pick(chain_cube).group_by("month").agg(pl.col("raw").sum(), pl.col("conv").sum())
    m = pick(all_cube).filter(pl.col("sensor") == "modis_aqua").group_by("month").agg(pl.col("raw").sum())
    return {"as_is": _dense(s, "raw", size), "ours": _dense(s, "conv", size), "modis": _dense(m, "raw", size)}


def bridge_years(all_cube: pl.DataFrame, incomplete: set[str]) -> list[dict]:
    """NOAA-20 converted to the S-NPP scale against S-NPP, per year, over the complete months both sensors have."""
    w = (
        all_cube.filter(pl.col("sensor").is_in(["viirs_noaa20", REFERENCE]))
        .group_by("month", "sensor")
        .agg(pl.col("raw").sum(), pl.col("conv").sum())
    )
    noaa = {int(m): (r, c) for m, r, c in w.filter(pl.col("sensor") == "viirs_noaa20").select("month", "raw", "conv").iter_rows()}
    snpp = {int(m): r for m, r in w.filter(pl.col("sensor") == REFERENCE).select("month", "raw").iter_rows()}
    out = []
    for y in range(2018, 2027):
        ms = [m for m in range(month_index(y, 1), month_index(y, 12) + 1) if m in noaa and m in snpp and month_text(m) not in incomplete]
        a, c, b = sum(noaa[m][0] for m in ms), sum(noaa[m][1] for m in ms), sum(snpp[m] for m in ms)
        if b >= MIN_COUNT:
            out.append({"year": y, "months": len(ms), "noaa_raw_over_snpp": a / b, "noaa_converted_over_snpp": c / b})
    return out


def bridge_validation(harm: dict) -> dict:
    """The bridge check of validate.py, read from harmonization.json: WAPE of NOAA-20 converted to S-NPP, held out."""
    out = {}
    for scenario in ("bridge_loyo", "bridge_forward"):
        rows = [r for r in harm["validation"] if r["scenario"] == scenario]
        zone = [r["wape"] for r in rows if r["level"] == "zone" and r["wape"] is not None]
        block = next((r for r in rows if r["level"] == "block"), None)
        out[scenario] = {
            "zone_wape_median": float(np.median(zone)) if zone else None,
            "zones": len(zone),
            "block_wape": None if block is None else block["wape"],
            "block_bias": None if block is None else block["bias"],
        }
    out["window"] = harm["selection"].get("bridge_window")
    return out


# ---------------------------------------------------------------- data: daily counts of 2026-11

def _days_counts(days: pl.DataFrame, sensor: str) -> dict[date, float]:
    d = days.filter((pl.col("sensor") == sensor) & pl.col("ok") & (pl.col("rows") > 0))
    return dict(zip(d["utc_date"].to_list(), d["rows"].cast(pl.Float64).to_list(), strict=True))


def _noaa_k(built: Path, cells: pl.DataFrame, factors: pl.DataFrame, seam: date, last: date) -> float | None:
    """Mean factor of NOAA-20 counts on [seam, last] (converted / raw), from series_daily by local date; None before the join."""
    path = built / "series_daily" / f"year={seam.year}" / "part-0.parquet"
    if not path.exists():
        return None
    df = (
        pl.scan_parquet(path)
        .filter((pl.col("sensor") == "viirs_noaa20") & pl.col("local_date").is_between(seam, last))
        .join(cells.lazy().select("cell_id", "kgroup"), on="cell_id")
        .group_by("kgroup", "local_date", "sensor")
        .agg(pl.col("n_day").sum(), pl.col("n_night").sum())
        .collect()
        .with_columns(
            pl.col("local_date").dt.month().cast(pl.Int8).alias("calmonth"),
            pl.lit(False).alias("recent"),
        )
    )
    if df.is_empty():
        return None
    k = apply_k(df, factors)
    return float(k["conv"].sum() / k["raw"].sum())


# ---------------------------------------------------------------- run

def run(work: Path) -> dict:
    """Compute everything from `work/built` and `work/days.parquet`; write `work/built/seam.json`."""
    built = work / "built"
    cells = _cell_table(built)
    factors = pl.read_parquet(built / "factors.parquet")
    harm = json.loads((built / "harmonization.json").read_text())
    days = pl.read_parquet(work / "days.parquet")

    chain_cube = _cube(built / "series_monthly.parquet", cells, factors)
    all_cube = _cube(built / "monthly.parquet", cells, factors)

    last_complete = chain.last_complete_date(days)
    incomplete = set(chain.incomplete_months(days, chain.SERIES_START, last_complete + timedelta(days=1)))
    last_full = month_index(last_complete.year, last_complete.month)
    while month_text(last_full) in incomplete:
        last_full -= 1
    first = PLACEBO_FIRST
    years = placebo_years(first, last_full)
    size = last_full + WINDOW + 2

    countries = sorted({g["country"] for g in harm["kgroups"] if g["country"]} | set(EXTRA_COUNTRIES))
    zones = sorted(chain_cube["zone"].unique().to_list())
    specs = [("world", "world"), *(("zone", z) for z in zones), *(("country", c) for c in countries)]
    slices, world = [], None
    for kind, name in specs:
        res = evaluate(slice_series(chain_cube, all_cube, kind, name, size), years)
        if kind == "world":
            world = res
        slices.append({"kind": kind, "name": name, **{k: v for k, v in res.items() if k != "placebo"}})
    assert world is not None

    seam26 = chain.SNPP_RETIRED
    snpp_d, noaa_d = _days_counts(days, REFERENCE), _days_counts(days, "viirs_noaa20")
    k_noaa = _noaa_k(built, cells, factors, seam26, last_complete)
    short = None
    if k_noaa is not None:
        as_is_d = {d: v for d, v in snpp_d.items() if d < seam26} | {
            d: v for d, v in noaa_d.items() if seam26 <= d <= last_complete
        }
        ours_d = {d: (v if d < seam26 else v * k_noaa) for d, v in as_is_d.items()}
        short = short_seam(ours_d, as_is_d, noaa_d, snpp_d, noaa_d, seam26, last_complete, first_year=2018)
        short["noaa_mean_factor"] = k_noaa
        short["placebo_snpp_only"] = summary(
            [short_ratio(snpp_d, seam26.replace(year=y), last_complete.replace(year=y)) for y in range(2013, seam26.year)]
        )

    out = {
        "version": "",
        "parameters": {
            "seam_2012": month_text(SEAM_MONTH),
            "seam_2026": seam26.isoformat(),
            "window_months": WINDOW,
            "placebo_month": PLACEBO_MONTH,
            "placebo_years": years,
            "last_complete_date": last_complete.isoformat(),
            "last_complete_month": month_text(last_full),
            "min_window_count": MIN_COUNT,
            "min_placebo_years": MIN_PLACEBO,
            "incomplete_months_kept": sorted(m for m in incomplete if m <= month_text(last_full)),
            "gap_dates": len(chain.gap_dates(days)),
            "series": {
                "modis": "modis_aqua raw monthly counts",
                "as_is": "series_monthly counts without factors",
                "ours": "series_monthly counts with the factors of factors.parquet",
            },
            "verdict": "pass when |ours / modis - 1| of the join is not above the 90th percentile of the same gap "
            "on the placebo years of the VIIRS era",
            "short_join_sources": "daily counts: days.parquet rows by UTC date (S-NPP before the join, NOAA-20 after it); "
            "ours multiplies the NOAA-20 days by their mean factor from series_daily",
        },
        "headline": headline(world),
        "slices": slices,
        "placebo_world": world["placebo"],
        "failed": [f"{s['kind']}:{s['name']}" for s in slices if s["status"] == "fail"],
        "insufficient": [f"{s['kind']}:{s['name']}" for s in slices if s["status"] == "insufficient"],
        "seam_2026": short,
        "bridge": {"validation": bridge_validation(harm), "years": bridge_years(all_cube, incomplete)},
    }
    fit.write_json(built / "seam.json", out)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline seam")
    ap.add_argument("--data", required=True, help="data root")
    args = ap.parse_args(argv)
    out = run(config.paths(args.data).work)
    print(out["headline"]["text"])
    return 0
