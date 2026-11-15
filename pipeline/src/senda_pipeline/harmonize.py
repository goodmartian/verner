"""senda-pipeline harmonize: fit the factors, validate them, write factors, cell_groups and harmonization.json."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import polars as pl

from . import config, fit, ladder, seam, validate

PAIR_AQUA = "modis_aqua__viirs_snpp"
PAIR_NOAA = "viirs_noaa20__viirs_snpp"
PAIR_TERRA = "modis_terra__viirs_snpp"
PAIR_TERRA_AQUA = "modis_terra__modis_aqua"
TERRA_CHECK_MONTHS = (seam.month_index(2003, 1), seam.month_index(2011, 12))
TERRA_LIMITS = {"loyo_zone_wape": 0.15, "vs_aqua_world_bias_pct": 10.0, "vs_aqua_zone_wape": 0.20}
TERRA_RULE = (
    "modis_terra enters the series (dates before the first modis_aqua date) if (a) its leave-one-year-out "
    "median zone WAPE on 2012 to 2019 is at most 0.15 and (b) on 2003-01 to 2011-12, on UTC dates where both "
    "MODIS sensors passed the day check, converted Terra against converted Aqua has a world bias within "
    "10 percent and a median zone WAPE of at most 0.20. The rule was set before the check was computed."
)
TERRA_FIT_RULE = (
    "modis_terra to viirs_snpp: the same ladder, windows and rules as modis_aqua (fit on 2012 to 2019); "
    "its factors use the kgroups of modis_aqua; a country kgroup takes the Terra country factors if Terra's own "
    "country decision uses that country, else the Terra zone factors."
)
THRESHOLDS = {"high_wape": 0.15, "medium_wape": 0.35, "high_unharmonized_share": 0.05, "medium_unharmonized_share": 0.20}
BRIDGE_RULE = (
    "Bridge viirs_noaa20 to viirs_snpp: L3 fitted on all years or on the last 3 full years up to 2022 and tested "
    "from 2023; the lower mean zone WAPE wins, chosen {window}. This forward test picks the window, so "
    "bridge_forward is not a clean holdout."
)
RECENT_RULE = (
    "modis_aqua window recent: L3 fitted on paired days of 2023 to 2025; checked by fitting 2022 to 2024 and "
    "testing 2025."
)
NRT_RULE = "Months made of near real time data are used when their dates passed the day check."


# ---------------------------------------------------------------- factors and groups

def build_kgroups(d: fit.PairData, use_country: np.ndarray) -> tuple[list[dict], np.ndarray]:
    """kgroup ids: zones 0..zg (the last is global), then every (country, zone) pair of a country with `use`."""
    kgroups = [{"id": i, "zone": z, "country": None} for i, z in enumerate(d.zones)]
    pairs = np.flatnonzero(use_country[d.pair_country] & (d.pair_zone < d.zg))
    kgroups += [
        {"id": d.zg + 1 + j, "zone": d.zones[d.pair_zone[p]], "country": d.countries[d.pair_country[p]]}
        for j, p in enumerate(pairs)
    ]
    return kgroups, pairs


def factor_frame(d, kz, basis, sensor, window, pairs, F=None, use=None) -> pl.DataFrame:
    """One row per kgroup, calendar month and dn. Pair kgroups copy their zone unless pair factors F are given.

    `use[country]`, when given, limits F to the countries of this sensor's own decision; the other pairs copy their zone.
    """
    names = np.array(fit.BASIS)[basis]
    if len(pairs) and F is not None:
        k_p, b_p = F[pairs], np.full((len(pairs), 12), "country")
        if use is not None:
            zone_of = d.pair_zone[pairs]
            own = use[d.pair_country[pairs]]
            k_p = np.where(own[:, None, None], k_p, kz[zone_of])
            b_p = np.where(own[:, None], b_p, names[zone_of])
    elif len(pairs):
        k_p, b_p = kz[d.pair_zone[pairs]], names[d.pair_zone[pairs]]
    else:
        k_p, b_p = kz[:0], names[:0]
    k_all, b_all = np.concatenate([kz, k_p]), np.concatenate([names, b_p])
    nk = len(k_all)
    return pl.DataFrame(
        {
            "kgroup": np.repeat(np.arange(nk), 24).astype(np.int32),
            "sensor": np.full(nk * 24, sensor),
            "calmonth": np.tile(np.repeat(np.arange(1, 13), 2), nk).astype(np.int8),
            "dn": np.tile(np.array(["D", "N"] * 12), nk),
            "window": np.full(nk * 24, window),
            "k": k_all.reshape(-1).astype(np.float32),
            "basis": np.repeat(b_all.reshape(-1), 2),
        }
    )


def cell_groups(cells: pl.DataFrame, kgroups: list[dict]) -> pl.DataFrame:
    """kgroup of every cell: its (country, zone) pair if that has own factors, else its zone, else global."""
    zone_rows = [g for g in kgroups if g["country"] is None]
    pair_rows = [g for g in kgroups if g["country"] is not None]
    zone_map = pl.DataFrame(
        {"zone2": [g["zone"] for g in zone_rows], "k_zone": [g["id"] for g in zone_rows]},
        schema={"zone2": pl.String, "k_zone": pl.Int32},
    )
    pair_map = pl.DataFrame(
        {
            "country": [g["country"] for g in pair_rows],
            "zone2": [g["zone"] for g in pair_rows],
            "k_pair": [g["id"] for g in pair_rows],
        },
        schema={"country": pl.String, "zone2": pl.String, "k_pair": pl.Int32},
    )
    zone = pl.col("zone").fill_null("none")
    c = cells.select(
        "cell_id",
        pl.col("country").fill_null("ZZ"),
        pl.when(zone == "none").then(pl.lit("global")).otherwise(zone).alias("zone2"),
    )
    glob = next(g["id"] for g in zone_rows if g["zone"] == "global")
    return (
        c.join(pair_map, on=["country", "zone2"], how="left")
        .join(zone_map, on="zone2", how="left")
        .select(
            pl.col("cell_id").cast(pl.Int32),
            pl.coalesce("k_pair", "k_zone", pl.lit(glob)).cast(pl.Int32).alias("kgroup"),
        )
    )


# ---------------------------------------------------------------- modis_terra check

def _median_of(rows: list[dict], level: str) -> float | None:
    w = [r["wape"] for r in rows if r["level"] == level and r["wape"] is not None]
    return float(np.median(w)) if w else None


def terra_vs_aqua(pairs_path: Path, cells: pl.DataFrame, factors: pl.DataFrame, zones: list[str]) -> dict:
    """Converted Terra against converted Aqua by month on TERRA_CHECK_MONTHS, counts of dates both passed."""
    lo, hi = TERRA_CHECK_MONTHS
    p = (
        pl.read_parquet(pairs_path)
        .filter(pl.col("month").is_between(lo, hi))
        .join(cells, on="cell_id")
        .with_columns((pl.col("month") % 12 + 1).cast(pl.Int8).alias("calmonth"))
    )
    f = factors.filter(pl.col("window") == "era").select("kgroup", "sensor", "calmonth", "dn", "k")
    for sensor, col in (("modis_terra", "n_src"), ("modis_aqua", "n_dst")):
        k = f.filter(pl.col("sensor") == sensor).drop("sensor")
        p = p.join(k, on=["kgroup", "calmonth", "dn"], how="left")
        if p.filter(pl.col("k").is_null() & (pl.col(col) > 0)).height:
            raise ValueError(f"no factor for some {sensor} counts of {pairs_path.name}")
        p = p.with_columns((pl.col(col).cast(pl.Float64) * pl.col("k").cast(pl.Float64)).alias(sensor)).drop("k")
    z = p.group_by("zone", "month").agg(pl.col("modis_terra").sum(), pl.col("modis_aqua").sum())
    zw = (
        z.group_by("zone")
        .agg(
            (pl.col("modis_terra") - pl.col("modis_aqua")).abs().sum().alias("err"),
            pl.col("modis_aqua").sum().alias("act"),
        )
        .filter(pl.col("zone").is_in(zones) & (pl.col("act") > 0))
        .with_columns((pl.col("err") / pl.col("act")).alias("wape"))
        .sort("zone")
    )
    w = p.group_by("month").agg(pl.col("modis_terra").sum(), pl.col("modis_aqua").sum())
    t, a = w["modis_terra"].to_numpy(), w["modis_aqua"].to_numpy()
    return {
        "months": [seam.month_text(lo), seam.month_text(hi)],
        "n_months": int(w.height),
        "zone_wape_median": float(zw["wape"].median()) if zw.height else None,
        "zones": int(zw.height),
        "zone_wape": {r["zone"]: r["wape"] for r in zw.select("zone", "wape").to_dicts()},
        "world_wape": float(np.abs(t - a).sum() / a.sum()) if a.sum() > 0 else None,
        "world_bias_pct": float(100 * (t.sum() - a.sum()) / a.sum()) if a.sum() > 0 else None,
        "terra_converted": float(t.sum()),
        "aqua_converted": float(a.sum()),
    }


def terra_accepted(loyo_zone: float | None, vs: dict) -> bool:
    """TERRA_RULE; a missing metric fails it."""
    lim = TERRA_LIMITS
    b, zw = vs.get("world_bias_pct"), vs.get("zone_wape_median")
    if loyo_zone is None or b is None or zw is None:
        return False
    return loyo_zone <= lim["loyo_zone_wape"] and abs(b) <= lim["vs_aqua_world_bias_pct"] and zw <= lim["vs_aqua_zone_wape"]


# ---------------------------------------------------------------- run

def run(work: Path) -> None:
    """Fit and validate everything from `work/built/pairs`, `work/built/cells.parquet`, `work/days.parquet`."""
    built, days_path = work / "built", work / "days.parquet"
    cells = pl.read_parquet(built / "cells.parquet")
    aqua = fit.load_pair(built / "pairs" / f"{PAIR_AQUA}.parquet", days_path, cells)
    noaa = fit.load_pair(built / "pairs" / f"{PAIR_NOAA}.parquet", days_path, cells)
    terra = fit.load_pair(built / "pairs" / f"{PAIR_TERRA}.parquet", days_path, cells)
    if (built / "monthly.parquet").exists():
        for d in (aqua, noaa, terra):
            fit.attach_counts(d, built / "monthly.parquet", days_path)

    for other in (noaa, terra):
        if not (np.array_equal(aqua.pair_zone, other.pair_zone) and np.array_equal(aqua.pair_country, other.pair_country)):
            raise RuntimeError("the pair files do not share one group layout")
    lad = ladder.run(aqua)
    final = lad["final"]
    window, bridge_scores = ladder.bridge_choose(noaa)
    zb = ladder.fit_l3(noaa, ladder.bridge_final_sel(noaa, window))
    zr = ladder.fit_l3(aqua, ladder.recent_final_sel(aqua))

    pool: list[dict] = []
    validation = validate.scenarios(aqua, noaa, aqua, pool)

    kgroups, pairs = build_kgroups(aqua, final.country.use)
    factors = pl.concat(
        [
            factor_frame(aqua, final.zone.k, final.zone.basis, "modis_aqua", "era", pairs, final.country.F),
            factor_frame(aqua, zr.k, zr.basis, "modis_aqua", "recent", pairs),
            factor_frame(noaa, zb.k, zb.basis, "viirs_noaa20", "era", pairs),
        ]
    )

    # modis_terra: the modis_aqua ladder on its own pair; it never changes anything of the pairs above
    lad_t = ladder.run(terra)
    final_t = lad_t["final"]
    factors = pl.concat(
        [factors, factor_frame(terra, final_t.zone.k, final_t.zone.basis, "modis_terra", "era", pairs, final_t.country.F, final_t.country.use)]
    )
    factors.write_parquet(built / "factors.parquet")
    cell_groups(cells, kgroups).write_parquet(built / "cell_groups.parquet")

    ent_t = ladder.entities(terra, ladder.era_sel(terra))
    terra_rows = validate._rows(terra, "terra_loyo", "L5", ladder.aqua_folds(terra)["loyo"], ent_t, None)
    validation += terra_rows
    cell_zone = seam._cell_table(built).select("cell_id", "zone", "kgroup")
    vs = terra_vs_aqua(
        built / "pairs" / f"{PAIR_TERRA_AQUA}.parquet", cell_zone, factors, [terra.zones[i] for i in ent_t["zone"]]
    )
    loyo_t = {"zone_wape_median": _median_of(terra_rows, "zone"), "country_wape_median": _median_of(terra_rows, "country")}
    terra_out = {
        "rule": TERRA_RULE,
        "limits": TERRA_LIMITS,
        "terra_loyo": {**loyo_t, "zones": len(ent_t["zone"]), "countries": len(ent_t["country"])},
        "terra_vs_aqua": vs,
        "accepted": terra_accepted(loyo_t["zone_wape_median"], vs),
        "ladder": lad_t["ladder"],
        "selection": {**lad_t["selection"], "rules": [*lad_t["selection"]["rules"], TERRA_FIT_RULE]},
        "country_decisions": lad_t["country_decisions"],
    }

    l5 = next(r for r in lad["ladder"] if r["level"] == "L5")
    l0 = next(r for r in lad["ladder"] if r["level"] == "L0")
    selection = dict(lad["selection"])
    selection.update(
        {
            "bridge_window": window,
            "bridge_scores": bridge_scores,
            "lambda_bridge": zb.lam,
            "lambda_recent": zr.lam,
            "rules": [*selection["rules"], BRIDGE_RULE.format(window=window), RECENT_RULE, NRT_RULE],
        }
    )
    out = {
        "version": "",
        "reference": "viirs_snpp",
        "ladder": lad["ladder"],
        "selection": selection,
        "validation": validation,
        "country_decisions": lad["country_decisions"],
        "error_curve": validate.error_curve(pool),
        "confidence_thresholds": THRESHOLDS,
        "summary": {
            "loyo_zone_wape_median": l5["loyo_zone_wape"],
            "forward_zone_wape_median": l5["forward_zone_wape"],
            "naive_zone_wape_median": l0["loyo_zone_wape"],
            "zones_supported": len(lad["entities"]["zone"]),
        },
        "kgroups": kgroups,
        "terra": terra_out,
        "diagnostics": {
            "pair_rows_outside_cells": {PAIR_AQUA: aqua.dropped, PAIR_NOAA: noaa.dropped, PAIR_TERRA: terra.dropped}
        },
    }
    fit.write_json(built / "harmonization.json", out)


def apply_only(work: Path, current: Path) -> None:
    """Keep factors and harmonization.json of the current version; rewrite cell_groups for the new cells."""
    built = work / "built"
    for name in ("factors.parquet", "harmonization.json"):
        if not (current / name).exists():
            raise SystemExit(f"--apply-only needs {current / name}; run harmonize without it first")
    for name in ("factors.parquet", "harmonization.json"):
        shutil.copyfile(current / name, built / name)
    kgroups = json.loads((built / "harmonization.json").read_text())["kgroups"]
    cell_groups(pl.read_parquet(built / "cells.parquet"), kgroups).write_parquet(built / "cell_groups.parquet")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline harmonize")
    ap.add_argument("--data", required=True, help="data root")
    ap.add_argument("--apply-only", action="store_true", help="reuse current factors, rewrite cell_groups only")
    args = ap.parse_args(argv)
    p = config.paths(args.data)
    if args.apply_only:
        apply_only(p.work, p.current.resolve())
    else:
        run(p.work)
    return 0
