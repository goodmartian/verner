"""Small synthetic data version laid out exactly as the files of a published version.

40 cells (4 rows x 10 columns, lat 9..10, lon 20..22.5), months 2003-01 to 2026-11 (last complete date 2026-11-12),
three sensors, two regions. Daily data is generated first; monthly series are aggregated from it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import shapely

ROW0, COL0 = 320, 800
NROWS, NCOLS = 4, 10
LAST_COMPLETE = date(2026, 11, 12)
OUTAGE = (date(2022, 3, 8), date(2022, 3, 12))
SENSORS = ("modis_aqua", "viirs_snpp", "viirs_noaa20")

CELL_A = (ROW0 + 0) * 1440 + (COL0 + 0)
CELL_B = (ROW0 + 0) * 1440 + (COL0 + 5)
CELL_NEVER = (ROW0 + 3) * 1440 + (COL0 + 9)
POLY_IN_CELL_A = [[20.0, 9.75], [20.1, 9.75], [20.1, 9.85], [20.0, 9.85], [20.0, 9.75]]
HOTSPOT_INSIDE = (9.80, 20.05)
HOTSPOT_OUTSIDE = (9.95, 20.20)


def mi(year: int, month: int) -> int:
    return (year - 2000) * 12 + month - 1


def _d(s: str) -> np.datetime64:
    return np.datetime64(s, "D")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spherical_km2(w: float, s: float, e: float, n: float) -> float:
    r = 6371.0088
    return r * r * np.radians(e - w) * (np.sin(np.radians(n)) - np.sin(np.radians(s)))


TERRA_FIRST = date(2000, 11, 1)
AQUA_FIRST = date(2002, 7, 4)
TERRA_K = {1: 4.5, 2: 6.0}  # era factors of modis_terra by kgroup


def _factors(terra: bool = False) -> pl.DataFrame:
    recs = []
    spec = {
        # sensor, window: (k kgroup 1, basis, k kgroup 2, basis)
        ("modis_aqua", "era"): (4.0, "zone_month", 5.0, "zone"),
        ("modis_aqua", "recent"): (3.0, "zone_month", 3.5, "zone"),
        ("viirs_noaa20", "era"): (0.875, "zone_month", 1.125, "zone_month"),
    }
    if terra:
        spec[("modis_terra", "era")] = (TERRA_K[1], "zone_month", TERRA_K[2], "zone")
    for (sensor, window), (k1, b1, k2, b2) in spec.items():
        for kgroup, k, basis in ((1, k1, b1), (2, k2, b2)):
            for cal in range(1, 13):
                for dn in ("D", "N"):
                    recs.append((kgroup, sensor, cal, dn, window, k, basis))
    return pl.DataFrame(
        recs,
        schema={
            "kgroup": pl.Int32,
            "sensor": pl.Utf8,
            "calmonth": pl.Int8,
            "dn": pl.Utf8,
            "window": pl.Utf8,
            "k": pl.Float32,
            "basis": pl.Utf8,
        },
        orient="row",
    )


def _terra_daily(cell_id: np.ndarray, scale: np.ndarray) -> pl.DataFrame:
    """Daily counts of 2000-11-01..2002-12-31: modis_terra before AQUA_FIRST, modis_aqua from it. A random stream of
    its own, so the months from 2003 on are the same as in the version without them."""
    rng = np.random.default_rng(2000)
    dates = np.arange(np.datetime64(TERRA_FIRST, "D"), _d("2003-01-01"))
    sensor = np.where(dates < np.datetime64(AQUA_FIRST, "D"), "modis_terra", "modis_aqua")
    moy = dates.astype("datetime64[M]").astype(int) % 12
    lam = 0.04 * scale[:, None] * ((1 + 4 * np.exp(-((moy - 7) ** 2) / 4)) * 0.25)[None, :]
    n_day, n_night = rng.poisson(lam), rng.poisson(lam * 0.3)
    ci, di = np.nonzero((n_day + n_night) > 0)
    return pl.DataFrame({
        "cell_id": cell_id[ci].astype(np.int32),
        "local_date": pl.Series(dates[di]),
        "sensor": sensor[di],
        "n_day": n_day[ci, di].astype(np.int32),
        "n_night": n_night[ci, di].astype(np.int32),
    })


def build(root: Path, terra: bool = False) -> dict:
    """The version; `terra` also gives it the months 2000-11..2002-12 (modis_terra until AQUA_FIRST) and their
    factors, with every month from 2003 on unchanged."""
    rng = np.random.default_rng(20261114)
    root.mkdir(parents=True, exist_ok=True)

    # cells
    rr, cc = np.meshgrid(np.arange(NROWS), np.arange(NCOLS), indexing="ij")
    rows_ = (ROW0 + rr).ravel()
    cols_ = (COL0 + cc).ravel()
    cell_id = (rows_ * 1440 + cols_).astype(np.int32)
    n_cells = len(cell_id)
    lat = (90 - (rows_ + 0.5) * 0.25).astype(np.float32)
    lon = (-180 + (cols_ + 0.5) * 0.25).astype(np.float32)
    west = cc.ravel() < 5
    pl.DataFrame(
        {
            "cell_id": cell_id,
            "lat": lat,
            "lon": lon,
            "zone": np.where(west, "z1", "z2"),
            "country": np.full(n_cells, "XA"),
            "land_frac": np.where(cell_id == CELL_NEVER, 0.5, 1.0).astype(np.float32),
        }
    ).write_parquet(root / "cells.parquet")
    pl.DataFrame({"cell_id": cell_id, "kgroup": np.where(west, 1, 2).astype(np.int32)}).write_parquet(
        root / "cell_groups.parquet"
    )
    _factors(terra).write_parquet(root / "factors.parquet")

    # regions
    regions = [
        ("XA", "country", "XA", {"en": "Xland"}, [20.0, 9.0, 22.5, 10.0], shapely.box(20.0, 9.0, 22.5, 10.0)),
        ("XA-W", "region", "XA", {"en": "West Xland"}, [20.0, 9.0, 21.25, 10.0], shapely.box(20.0, 9.0, 21.25, 10.0)),
    ]
    pl.DataFrame(
        {
            "id": [r[0] for r in regions],
            "kind": [r[1] for r in regions],
            "country_id": [r[2] for r in regions],
            "names_json": [json.dumps(r[3]) for r in regions],
            "bbox": [r[4] for r in regions],
            "area_km2": [_spherical_km2(*r[4]) for r in regions],
            "geometry_wkb": [shapely.to_wkb(r[5]) for r in regions],
        }
    ).write_parquet(root / "regions.parquet")

    # daily dates and the sensor chosen on each
    dates = np.arange(_d("2003-01-01"), np.datetime64(LAST_COMPLETE + timedelta(days=1), "D"))
    n_d = len(dates)
    month_of_date = dates.astype("datetime64[M]").astype(int) - 360
    chosen = np.full(n_d, "viirs_snpp", dtype="U12")
    chosen[dates < _d("2012-02-01")] = "modis_aqua"
    chosen[dates >= _d("2026-11-02")] = "viirs_noaa20"
    chosen[(dates >= np.datetime64(OUTAGE[0], "D")) & (dates <= np.datetime64(OUTAGE[1], "D"))] = "modis_aqua"
    mult = {"modis_aqua": 0.25, "viirs_snpp": 1.0, "viirs_noaa20": 1.0}
    season = 1 + 4 * np.exp(-((month_of_date % 12 - 7) ** 2) / 4)
    scale = rng.uniform(0.3, 1.5, n_cells)
    scale[cell_id == CELL_NEVER] = 0.0
    sens_mult = np.array([mult[s] for s in chosen])
    lam = 0.04 * scale[:, None] * (season * sens_mult)[None, :]
    n_day = rng.poisson(lam)
    n_night = rng.poisson(lam * 0.3)
    ci, di = np.nonzero((n_day + n_night) > 0)
    daily = {
        "cell_id": cell_id[ci],
        "di": di,
        "n_day": n_day[ci, di].astype(np.int32),
        "n_night": n_night[ci, di].astype(np.int32),
        "sensor": chosen[di].astype("U12"),
    }

    # special entries with hand-set values
    specials = [
        (CELL_A, date(2005, 7, 15), "modis_aqua", 10, 5),
        (CELL_B, date(2005, 7, 20), "modis_aqua", 6, 0),
        (CELL_A, date(2015, 7, 10), "viirs_snpp", 4, 3),
        (CELL_A, date(2022, 3, 10), "modis_aqua", 8, 2),
    ]
    drop = np.zeros(len(daily["cell_id"]), dtype=bool)
    for cid, d, _s, _a, _b in specials:
        drop |= (daily["cell_id"] == cid) & (month_of_date[daily["di"]] == mi(d.year, d.month))
    for key in daily:
        daily[key] = daily[key][~drop]
    for cid, d, s, a, b in specials:
        di_s = int((np.datetime64(d, "D") - dates[0]).astype(int))
        daily["cell_id"] = np.append(daily["cell_id"], np.int32(cid))
        daily["di"] = np.append(daily["di"], di_s)
        daily["n_day"] = np.append(daily["n_day"], np.int32(a))
        daily["n_night"] = np.append(daily["n_night"], np.int32(b))
        daily["sensor"] = np.append(daily["sensor"], s)
    daily_df = pl.DataFrame(
        {
            "cell_id": daily["cell_id"].astype(np.int32),
            "local_date": pl.Series(dates[daily["di"]]),
            "sensor": daily["sensor"],
            "n_day": daily["n_day"].astype(np.int32),
            "n_night": daily["n_night"].astype(np.int32),
        }
    ).sort(["local_date", "cell_id"])
    if terra:
        early = _terra_daily(cell_id, scale).sort(["local_date", "cell_id"])
        daily_df = pl.concat([early, daily_df])  # every early date comes before 2003

    for year, part in daily_df.with_columns(y=pl.col("local_date").dt.year()).partition_by("y", as_dict=True).items():
        folder = root / "series_daily" / f"year={year[0]}"
        folder.mkdir(parents=True, exist_ok=True)
        part.drop("y").write_parquet(folder / "part-0.parquet")

    # monthly series aggregated from daily
    month_expr = (pl.col("local_date").dt.year() - 2000) * 12 + pl.col("local_date").dt.month() - 1
    series = (
        daily_df.with_columns(month=month_expr.cast(pl.Int16))
        .group_by(["cell_id", "month", "sensor"])
        .agg(pl.col("n_day").sum(), pl.col("n_night").sum())
        .with_columns(
            n_day=pl.col("n_day").cast(pl.Int32),
            n_night=pl.col("n_night").cast(pl.Int32),
            frp_day=(pl.col("n_day") * 12.5).cast(pl.Float32),
            frp_night=(pl.col("n_night") * 8.0).cast(pl.Float32),
        )
        .sort(["month", "cell_id", "sensor"])
        .select("cell_id", "month", "sensor", "n_day", "n_night", "frp_day", "frp_night")
    )
    series.write_parquet(root / "series_monthly.parquet")

    # monthly raw: series rows plus the other sensors that were alive that month
    alive = {
        "modis_aqua": (mi(2003, 1), mi(2026, 11)),
        "viirs_snpp": (mi(2012, 2), mi(2026, 11)),
        "viirs_noaa20": (mi(2018, 4), mi(2026, 11)),
    }
    chosen_by_month: dict[int, set[str]] = {}
    for m, s in zip(month_of_date, chosen, strict=True):
        chosen_by_month.setdefault(int(m), set()).add(str(s))
    # months where a sensor is chosen but only for part of the month still hold its series rows
    pieces = [
        series.select("cell_id", "month", "sensor", "n_day", "n_night").with_columns(
            frp_mw=((pl.col("n_day") + pl.col("n_night")) * 10.0).cast(pl.Float32)
        )
    ]
    for sensor, (m0, m1) in alive.items():
        for m in range(m0, m1 + 1):
            if sensor in chosen_by_month.get(m, set()):
                continue
            lam_m = 0.04 * 30 * scale * (1 + 4 * np.exp(-((m % 12 - 7) ** 2) / 4)) * mult[sensor]
            a = rng.poisson(lam_m)
            b = rng.poisson(lam_m * 0.3)
            keep = (a + b) > 0
            if keep.any():
                pieces.append(
                    pl.DataFrame(
                        {
                            "cell_id": cell_id[keep],
                            "month": np.full(keep.sum(), m, dtype=np.int16),
                            "sensor": np.full(keep.sum(), sensor),
                            "n_day": a[keep].astype(np.int32),
                            "n_night": b[keep].astype(np.int32),
                            "frp_mw": ((a[keep] + b[keep]) * 10.0).astype(np.float32),
                        }
                    )
                )
    pl.concat(pieces).sort(["month", "cell_id", "sensor"]).write_parquet(root / "monthly.parquet")

    # days
    day_rows = []
    for i in range(n_d):
        d = dates[i].astype(object)
        outage = OUTAGE[0] <= d <= OUTAGE[1]
        source = "nrt" if d >= date(2026, 9, 1) else "sp"
        for s, first, last, base in (
            ("modis_aqua", date(2002, 7, 4), date(2099, 1, 1), 5000),
            ("viirs_snpp", date(2012, 1, 20), date(2026, 11, 1), 8000),
            ("viirs_noaa20", date(2018, 4, 1), date(2099, 1, 1), 7000),
        ):
            if not first <= d <= last:
                continue
            ok = not (outage and s != "modis_aqua")
            day_rows.append((d, s, base if ok else 10, ok, s == str(chosen[i]), source))
    if terra:
        early_days = [TERRA_FIRST + timedelta(days=i) for i in range((date(2003, 1, 1) - TERRA_FIRST).days)]
        day_rows[:0] = [(d, s, 5000, True, (s == "modis_terra") == (d < AQUA_FIRST), "sp")
                        for d in early_days for s in ("modis_terra", "modis_aqua") if s == "modis_terra" or d >= AQUA_FIRST]
    pl.DataFrame(
        day_rows,
        schema={
            "utc_date": pl.Date,
            "sensor": pl.Utf8,
            "rows": pl.Int32,
            "ok": pl.Boolean,
            "chosen": pl.Boolean,
            "source": pl.Utf8,
        },
        orient="row",
    ).write_parquet(root / "days.parquet")

    # hotspot rows
    ex_n_d = daily_df["n_day"].to_numpy()
    ex_n_n = daily_df["n_night"].to_numpy()
    cell_pos = {int(c): i for i, c in enumerate(cell_id)}
    base_idx = np.repeat(np.arange(len(daily_df)), ex_n_d + ex_n_n)
    is_night = np.concatenate([np.r_[np.zeros(a, bool), np.ones(b, bool)] for a, b in zip(ex_n_d, ex_n_n, strict=True)])
    r_cell = daily_df["cell_id"].to_numpy()[base_idx]
    r_date = daily_df["local_date"].to_numpy()[base_idx]
    r_sensor = daily_df["sensor"].to_numpy()[base_idx]
    pos = np.array([cell_pos[int(c)] for c in r_cell]) if len(r_cell) else np.array([], dtype=int)
    south = 90 - (rows_[pos] + 1) * 0.25
    west_edge = -180 + cols_[pos] * 0.25
    r_lat = south + rng.uniform(0.01, 0.24, len(pos))
    r_lon = west_edge + rng.uniform(0.01, 0.24, len(pos))
    special_mask = (r_cell == CELL_A) & (r_date == np.datetime64("2005-07-15"))
    sp_idx = np.nonzero(special_mask)[0]
    for j, ix in enumerate(sp_idx):
        r_lat[ix], r_lon[ix] = HOTSPOT_INSIDE if j < 3 else HOTSPOT_OUTSIDE
    offset_min = np.round(r_lon * 4).astype(int)
    local_dt = r_date.astype("datetime64[m]") + np.where(is_night, 90, 13 * 60 + 30).astype("timedelta64[m]")
    acq = (local_dt - offset_min.astype("timedelta64[m]")).astype("datetime64[ms]")
    rows_df = pl.DataFrame(
        {
            "lat": r_lat.astype(np.float32),
            "lon": r_lon.astype(np.float32),
            "acq_utc": pl.Series(acq).dt.replace_time_zone("UTC"),
            "local_date": pl.Series(r_date),
            "sensor": r_sensor,
            "frp_mw": (10.0 + rng.uniform(0, 5, len(pos))).astype(np.float32),
            "confidence": np.where(np.char.startswith(r_sensor.astype(str), "modis"), "80", "n"),
            "daynight": np.where(is_night, "N", "D"),
            "source": np.where(r_date >= np.datetime64("2026-09-01"), "nrt", "sp"),
        }
    ).sort("acq_utc")
    rows_df = rows_df.with_columns(
        y=pl.col("local_date").dt.year(),
        tile_lat=(pl.col("lat") / 10).floor().cast(pl.Int32) * 10,
        tile_lon=(pl.col("lon") / 10).floor().cast(pl.Int32) * 10,
    )
    for key, part in rows_df.partition_by(["y", "tile_lat", "tile_lon"], as_dict=True).items():
        folder = root / "rows" / f"year={key[0]}" / f"tile={key[1]}_{key[2]}"
        folder.mkdir(parents=True, exist_ok=True)
        part.drop("y", "tile_lat", "tile_lon").write_parquet(folder / "part-0.parquet")

    # json files
    harmonization = {
        "version": "test-1",
        "reference": "viirs_snpp",
        "ladder": [
            {"level": "L0", "loyo_zone_wape": 0.8, "loyo_country_wape": 0.8, "forward_zone_wape": 0.8,
             "forward_country_wape": 0.8, "chosen": False},
            {"level": "L3", "loyo_zone_wape": 0.2, "loyo_country_wape": 0.2, "forward_zone_wape": 0.25,
             "forward_country_wape": 0.25, "chosen": True},
        ],
        "selection": {"lambda": 0.1, "lambda_scores": [], "daynight": False, "bridge_window": "last3",
                      "countries_used": 0, "rules": ["rule one"]},
        "validation": [
            {"scenario": "loyo", "level": "zone", "entity": "z1", "wape": 0.1, "bias": 0.0, "spearman": 0.9,
             "sign": 0.8, "n_months": 96, "actual": 1000, "mean_monthly_count": 10.0},
            {"scenario": "forward", "level": "zone", "entity": "z1", "wape": 0.2, "bias": 0.0, "spearman": 0.9,
             "sign": 0.8, "n_months": 24, "actual": 300, "mean_monthly_count": 10.0},
            {"scenario": "loyo", "level": "country", "entity": "XA", "wape": 0.2, "bias": 0.0, "spearman": 0.9,
             "sign": 0.8, "n_months": 96, "actual": 2000, "mean_monthly_count": 20.0},
            {"scenario": "forward", "level": "country", "entity": "XA", "wape": 0.45, "bias": 0.0, "spearman": 0.9,
             "sign": 0.8, "n_months": 24, "actual": 600, "mean_monthly_count": 20.0},
            {"scenario": "loyo", "level": "block", "entity": "b1", "wape": 0.5, "bias": 0.0, "spearman": 0.9,
             "sign": 0.8, "n_months": 96, "actual": 20, "mean_monthly_count": 0.2},
        ],
        "country_decisions": [{"country": "XA", "use": False, "gain": 0.0}],
        "error_curve": [
            {"mean_monthly_count": 1.0, "wape": 0.6, "samples": 40},
            {"mean_monthly_count": 10.0, "wape": 0.3, "samples": 100},
            {"mean_monthly_count": 100.0, "wape": 0.15, "samples": 100},
            {"mean_monthly_count": 1000.0, "wape": 0.08, "samples": 50},
        ],
        "confidence_thresholds": {"high_wape": 0.15, "medium_wape": 0.35, "high_unharmonized_share": 0.05,
                                  "medium_unharmonized_share": 0.20},
        "summary": {"loyo_zone_wape_median": 0.1, "forward_zone_wape_median": 0.2, "naive_zone_wape_median": 0.7,
                    "zones_supported": 2},
    }
    events = [
        {"id": "xa-2010-08", "region_id": "XA", "region_name": "Xland", "month": "2010-08", "era": "MODIS",
         "count": 100, "median": 40, "ratio": 2.5, "rank": 1, "of": 8, "found": True,
         "source_url": "https://example.org/xa-2010-08"},
        {"id": "xa-2019-12", "region_id": "XA-W", "region_name": "West Xland", "month": "2019-12", "era": "VIIRS",
         "count": 5, "median": 4, "ratio": 1.25, "rank": 5, "of": 8, "found": False,
         "source_url": "https://example.org/xa-2019-12"},
    ]
    if terra:
        harmonization["validation"] += [
            {"scenario": s, "level": "zone", "entity": "z1", "wape": 0.3, "bias": 0.0, "spearman": 0.8, "sign": 0.7,
             "n_months": 24, "actual": 500, "mean_monthly_count": 10.0} for s in ("terra_loyo", "terra_vs_aqua")]
        harmonization["terra_acceptance"] = {"passed": True}
    (root / "harmonization.json").write_text(json.dumps(harmonization))
    (root / "events.json").write_text(json.dumps(events))
    manifest = {
        "version": "test-1",
        "built_at": "2026-11-13T00:00:00Z",
        "last_complete_date": LAST_COMPLETE.isoformat(),
        "first_month": "2000-11" if terra else "2003-01",
        "sensors": {
            **({"modis_terra": {"first": TERRA_FIRST.isoformat(), "last": "2002-07-03", "retired_at": None}}
               if terra else {}),
            "modis_aqua": {"first": "2002-07-04", "last": "2026-11-12", "retired_at": None},
            "viirs_snpp": {"first": "2012-01-20", "last": "2026-11-02", "retired_at": "2026-11-02T13:00:00Z"},
            "viirs_noaa20": {"first": "2018-04-01", "last": "2026-11-12", "retired_at": None},
        },
        "incomplete_months": ["2008-03"],
        "gap_dates": [],
        "stats": {"low_days": 5},
        "files": {
            p.name: _sha(p)
            for p in sorted(root.iterdir())
            if p.is_file() and p.name != "manifest.json"
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest))

    return {
        "root": root,
        "cell_a": CELL_A,
        "cell_b": CELL_B,
        "cell_never": CELL_NEVER,
        "n_cells": n_cells,
        "last_complete": LAST_COMPLETE,
        "built_at": datetime(2026, 11, 13).isoformat(),
    }
