"""Synthetic inputs with a known answer for the harmonization, publish and verify tests."""

from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path

import numpy as np
import polars as pl

from senda_pipeline import fit

FIRST_MONTH = (2012 - 2000) * 12 + 1  # 2012-02
LAST_MONTH = (2025 - 2000) * 12 + 11  # 2025-12
NOAA_FIRST = (2018 - 2000) * 12 + 3  # 2018-04
TERRA_CHECK_FIRST = (2003 - 2000) * 12  # 2003-01


# ------------------------------------------------------------ arrays for unit tests

def make_pair(
    k=4.0,
    zones=("z0", "z1", "z2"),
    countries=("c0", "c1"),
    first=FIRST_MONTH,
    last=(2021 - 2000) * 12 + 11,
    rate=50.0,
    seed=0,
    k_fn=None,
    noise=False,
) -> fit.PairData:
    """Groups are zone x country x 2 blocks, plus one group of zone none. V = k * M exactly unless noise.

    `k_fn(zone, country, calmonth, dn) -> float` overrides the constant `k`.
    """
    rng = np.random.default_rng(seed)
    month = np.arange(first, last + 1)
    cm = month % 12 + 1
    zl = [*zones, "global"]
    spec = [(zi, ci, b) for zi in range(len(zones)) for ci in range(len(countries)) for b in range(2)]
    spec.append((len(zones), 0, 0))
    g_zone = np.array([s[0] for s in spec])
    g_country = np.array([s[1] for s in spec])
    g_block = np.arange(len(spec))
    m = rng.poisson(rate, size=(len(spec), len(month), 2)).astype(float)
    kk = np.empty_like(m)
    for g, (zi, ci, _) in enumerate(spec):
        for dn in range(2):
            kk[g, :, dn] = [
                (k_fn(zl[zi], countries[ci], int(c), "DN"[dn]) if k_fn else k) for c in cm
            ]
    v = rng.poisson(m * kk).astype(float) if noise else np.rint(m * kk)
    return fit.PairData(
        src="modis_aqua",
        dst="viirs_snpp",
        M=m,
        V=v,
        month=month,
        valid=np.ones(len(month), bool),
        g_zone=g_zone,
        g_country=g_country,
        g_block=g_block,
        zones=zl,
        countries=list(countries),
    )


def clone(d: fit.PairData, M=None, V=None) -> fit.PairData:
    """Same layout with other counts and an empty cache."""
    return fit.PairData(
        src=d.src, dst=d.dst, M=d.M if M is None else M, V=d.V if V is None else V, month=d.month, valid=d.valid,
        g_zone=d.g_zone, g_country=d.g_country, g_block=d.g_block, zones=d.zones, countries=d.countries,
    )


# ------------------------------------------------------------ files

def cell_id(row: int, col: int) -> int:
    return row * 1440 + col


def make_cells() -> pl.DataFrame:
    """Four regions of 8 x 8 cells: AA and BB in zone resolve-01-n, CC in resolve-02-n, DD without a zone."""
    regions = [("AA", "resolve-01-n", 100, 100), ("BB", "resolve-01-n", 100, 120), ("CC", "resolve-02-n", 120, 100), ("DD", "none", 120, 120)]
    rows = []
    for country, zone, r0, c0 in regions:
        for r in range(r0, r0 + 8):
            for c in range(c0, c0 + 8):
                rows.append((cell_id(r, c), 90 - (r + 0.5) * 0.25, -180 + (c + 0.5) * 0.25, zone, country, 1.0))
    return pl.DataFrame(
        rows, schema={"cell_id": pl.Int32, "lat": pl.Float32, "lon": pl.Float32, "zone": pl.String, "country": pl.String, "land_frac": pl.Float32}, orient="row"
    )


def _pair_frame(cells: pl.DataFrame, m_arr: np.ndarray, v_arr: np.ndarray, months: np.ndarray) -> pl.DataFrame:
    n, t, _ = m_arr.shape
    return pl.DataFrame(
        {
            "cell_id": np.repeat(cells["cell_id"].to_numpy(), t * 2).astype(np.int32),
            "month": np.tile(np.repeat(months, 2), n).astype(np.int16),
            "dn": np.tile(np.array(["D", "N"]), n * t),
            "n_src": m_arr.reshape(-1).astype(np.int32),
            "n_dst": v_arr.reshape(-1).astype(np.int32),
        }
    )


def make_days() -> pl.DataFrame:
    """Terra from 2000-11-01, Aqua from 2002-07-04, S-NPP from 2012-01-20, NOAA-20 from 2018-04-01, all to 2025-12-31; no gaps."""
    parts = []
    for sensor, start in (("modis_terra", date(2000, 11, 1)), ("modis_aqua", date(2002, 7, 4)), ("viirs_snpp", date(2012, 1, 20)), ("viirs_noaa20", date(2018, 4, 1))):
        dates = pl.date_range(start, date(2025, 12, 31), "1d", eager=True)
        parts.append(pl.DataFrame({"utc_date": dates, "sensor": sensor, "rows": 1000, "ok": True}))
    days = pl.concat(parts).with_columns(pl.col("rows").cast(pl.Int32), source=pl.lit("sp"))
    chosen = ((pl.col("sensor") == "modis_terra") & (pl.col("utc_date") < date(2002, 7, 4))) | (
        (pl.col("sensor") == "modis_aqua") & (pl.col("utc_date") < date(2012, 2, 1))
    ) | (
        (pl.col("sensor") == "viirs_snpp") & (pl.col("utc_date") >= date(2012, 2, 1))
    )
    return days.with_columns(chosen.alias("chosen")).sort("utc_date", "sensor")


def write_work(
    root: Path,
    seed: int = 0,
    k_fn=None,
    bridge_k: float = 1.0,
    rate: float = 20.0,
    noise: bool = False,
    work_name: str = "work",
) -> Path:
    """Write a complete synthetic `work` folder (days, built/ with pairs, cells, series, monthly) and return it.

    The truth: V = k_fn(zone, country, calmonth, dn) * M for modis_aqua (default 4, 3 and 2 by zone) and
    V = bridge_k * M for viirs_noaa20.
    """
    rng = np.random.default_rng(seed)
    work = root / work_name
    built = work / "built"
    (built / "pairs").mkdir(parents=True)
    cells = make_cells()
    cells.write_parquet(built / "cells.parquet")
    days = make_days()
    days.write_parquet(work / "days.parquet")

    zone_k = {"resolve-01-n": 4.0, "resolve-02-n": 3.0, "none": 2.0}
    cm_of = lambda months: months % 12 + 1

    def truth(months: np.ndarray, base_k: float | None) -> np.ndarray:
        out = np.empty((cells.height, len(months), 2))
        zones, countries = cells["zone"].to_list(), cells["country"].to_list()
        for i, (z, c) in enumerate(zip(zones, countries, strict=True)):
            for dn in range(2):
                out[i, :, dn] = [
                    base_k if base_k is not None else (k_fn(z, c, int(cm), "DN"[dn]) if k_fn else zone_k[z])
                    for cm in cm_of(months)
                ]
        return out

    for name, first, bk in (("modis_aqua__viirs_snpp", FIRST_MONTH, None), ("viirs_noaa20__viirs_snpp", NOAA_FIRST, bridge_k)):
        months = np.arange(first, LAST_MONTH + 1)
        m = rng.poisson(rate, size=(cells.height, len(months), 2)).astype(float)
        k = truth(months, bk)
        v = rng.poisson(m * k).astype(float) if noise else np.rint(m * k)
        _pair_frame(cells, m, v, months).write_parquet(built / "pairs" / f"{name}.parquet")
        n_days = np.full(len(months), 28)
        if bk is not None:
            n_days[0] = 10  # the first NOAA-20 month is partial
        pl.DataFrame({"month": months.astype(np.int16), "n_days": n_days.astype(np.int16)}).write_parquet(built / "pairs" / f"{name}__days.parquet")
        if bk is None:
            snpp = _pair_frame(cells, m, v, months)
            # modis_terra sees what modis_aqua sees: the same pair and the same truth
            snpp.write_parquet(built / "pairs" / "modis_terra__viirs_snpp.parquet")
            shutil.copyfile(built / "pairs" / f"{name}__days.parquet", built / "pairs" / "modis_terra__viirs_snpp__days.parquet")

    # Terra against Aqua on 2003-01 to 2011-12: equal counts
    months = np.arange(TERRA_CHECK_FIRST, FIRST_MONTH)
    m = rng.poisson(rate, size=(cells.height, len(months), 2)).astype(float)
    _pair_frame(cells, m, m, months).write_parquet(built / "pairs" / "modis_terra__modis_aqua.parquet")

    # monthly: raw counts of both sensors of the aqua pair
    mon = []
    for sensor, col in (("modis_aqua", "n_src"), ("viirs_snpp", "n_dst")):
        wide = snpp.pivot(on="dn", index=["cell_id", "month"], values=col).rename({"D": "n_day", "N": "n_night"})
        mon.append(wide.with_columns(sensor=pl.lit(sensor)))
    monthly = pl.concat(mon).select(
        pl.col("cell_id").cast(pl.Int32),
        pl.col("month").cast(pl.Int16),
        "sensor",
        pl.col("n_day").cast(pl.Int32),
        pl.col("n_night").cast(pl.Int32),
        ((pl.col("n_day") + pl.col("n_night")) * 1.5).cast(pl.Float32).alias("frp_mw"),
    )
    monthly.write_parquet(built / "monthly.parquet")

    # series: S-NPP in 2020 for four cells, consistent between daily and monthly
    ids = cells["cell_id"].to_numpy()[:4]
    dates = pl.date_range(date(2020, 1, 1), date(2020, 12, 31), "1d", eager=True)
    daily = pl.DataFrame(
        {
            "cell_id": np.repeat(ids, len(dates)).astype(np.int32),
            "local_date": np.tile(dates.to_numpy(), len(ids)),
            "sensor": "viirs_snpp",
            "n_day": rng.integers(0, 5, len(ids) * len(dates)).astype(np.int32),
            "n_night": rng.integers(0, 5, len(ids) * len(dates)).astype(np.int32),
        }
    )
    (built / "series_daily" / "year=2020").mkdir(parents=True)
    daily.write_parquet(built / "series_daily" / "year=2020" / "part-0.parquet")
    sm = (
        daily.with_columns(((pl.col("local_date").dt.year() - 2000) * 12 + pl.col("local_date").dt.month() - 1).cast(pl.Int16).alias("month"))
        .group_by("cell_id", "month", "sensor")
        .agg(pl.col("n_day").sum(), pl.col("n_night").sum())
        .with_columns(
            (pl.col("n_day") * 1.0).cast(pl.Float32).alias("frp_day"), (pl.col("n_night") * 1.0).cast(pl.Float32).alias("frp_night")
        )
        .select("cell_id", "month", "sensor", "n_day", "n_night", "frp_day", "frp_night")
        .sort("cell_id", "month")
    )
    sm.write_parquet(built / "series_monthly.parquet")
    (built / "rows" / "year=2020" / "tile=30_-60").mkdir(parents=True)
    pl.DataFrame(
        {
            "lat": [1.0],
            "lon": [2.0],
            "acq_utc": [datetime(2020, 1, 1, 12)],
            "local_date": [date(2020, 1, 1)],
            "sensor": ["viirs_snpp"],
            "frp_mw": [3.0],
            "confidence": ["n"],
            "daynight": ["D"],
            "source": ["sp"],
        },
        schema={
            "lat": pl.Float32,
            "lon": pl.Float32,
            "acq_utc": pl.Datetime("ms", "UTC"),
            "local_date": pl.Date,
            "sensor": pl.String,
            "frp_mw": pl.Float32,
            "confidence": pl.String,
            "daynight": pl.String,
            "source": pl.String,
        },
    ).write_parquet(built / "rows" / "year=2020" / "tile=30_-60" / "part-0.parquet")
    pl.DataFrame(
        {"id": ["AA"], "kind": ["country"], "country_id": [None], "names_json": ['{"en":"AA"}'], "bbox": ["0,0,1,1"], "area_km2": [1.0], "geometry_wkb": [b""]},
        schema_overrides={"country_id": pl.String},
    ).write_parquet(built / "regions.parquet")
    # a leftover that publish must not copy
    (built / "build_report.json").write_text("{}")
    return work
