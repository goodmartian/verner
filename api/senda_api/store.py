"""The data version in memory: sparse matrices cells x months, factor tables, and small reference tables.

Files `series_daily/` and `rows/` stay on disk and are read per request.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import scipy.sparse as sp

from . import forecasts, seam
from . import regions as regions_mod
from .months import BASE_FIRST_YEAR, month_of, parse_month_label

REFERENCE = "viirs_snpp"
SENSORS = ("modis_terra", "modis_aqua", "viirs_snpp", "viirs_noaa20")
MODIS_SENSORS = ("modis_terra", "modis_aqua")  # their counts are converted to the VIIRS scale
RECENT_WINDOW_SENSORS = {"modis_aqua"}
RECENT_START = (2022 - 2000) * 12  # months from 2022-01 use the "recent" window for modis_aqua
GRID_COLS, GRID_ROWS = 1440, 720
CELL_DEG = 0.25
SENSOR_NAMES = {"modis_terra": "MODIS Terra", "modis_aqua": "MODIS Aqua","viirs_snpp": "VIIRS S-NPP", "viirs_noaa20": "VIIRS NOAA-20"}
BASIS_CODES = {"country": 0, "zone_month": 1, "zone": 2, "global": 3}
FALLBACK_CODES = (BASIS_CODES["zone"], BASIS_CODES["global"])
FACTOR_COLUMNS = ("kgroup", "sensor", "calmonth", "dn", "window", "k", "basis")


@dataclass(eq=False)
class Cells:
    cell_id: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    land_frac: np.ndarray
    zone: np.ndarray
    country: np.ndarray
    west: np.ndarray
    south: np.ndarray
    row_of: np.ndarray  # cell_id -> row, -1 for cells without data


class Factors:
    """Conversion factors k as dense tables [kgroup index, calendar month - 1] per (sensor, window, dn)."""

    def __init__(self, df: pl.DataFrame):
        missing = [c for c in FACTOR_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"factors.parquet lacks columns {missing}")
        kgroup = df["kgroup"].cast(pl.Int64).to_numpy()
        cal = df["calmonth"].cast(pl.Int64).to_numpy()
        k = df["k"].cast(pl.Float64).to_numpy()
        if len(df) == 0 or not (np.isfinite(k).all() and (k > 0).all()):
            raise ValueError("factor table must hold finite k greater than zero")
        if cal.min() < 1 or cal.max() > 12:
            raise ValueError("factor calmonth must be 1..12")
        basis = np.array([BASIS_CODES.get(b, -1) for b in df["basis"].to_list()], dtype=np.int8)
        if (basis < 0).any():
            raise ValueError("factor basis must be country, zone_month, zone or global")
        self.kg_ids = np.unique(kgroup)
        gi = np.searchsorted(self.kg_ids, kgroup)
        self.k: dict[tuple[str, str, str], np.ndarray] = {}
        self.basis: dict[tuple[str, str, str], np.ndarray] = {}
        keys = list(zip(df["sensor"].to_list(), df["window"].to_list(), df["dn"].to_list(), strict=True))
        for key in set(keys):
            if key[1] not in ("era", "recent") or key[2] not in ("D", "N"):
                raise ValueError(f"factor window and dn must be era|recent and D|N, got {key}")
            sel = np.array([kk == key for kk in keys])
            tab = np.full((len(self.kg_ids), 12), np.nan, dtype=np.float32)
            btab = np.full((len(self.kg_ids), 12), -1, dtype=np.int8)
            tab[gi[sel], cal[sel] - 1] = k[sel]
            btab[gi[sel], cal[sel] - 1] = basis[sel]
            self.k[key] = tab
            self.basis[key] = btab


@dataclass(eq=False)
class KLookup:
    """One vectorized lookup of the conversion factor, shared by the matrices, the daily window and the export."""

    kgroup: np.ndarray  # per row, -1 if the cell has no group
    kg_index: np.ndarray  # per row, index into factors.kg_ids, -1 if none
    factors: Factors

    def lookup(self, sensor: str, rows: np.ndarray, months: np.ndarray, dn: str):
        """k for each (cell row, absolute month) of one sensor and day/night part.

        Returns (k, fallback, missing). Missing entries carry k = 0 so they never add to a sum.
        """
        n = len(rows)
        if sensor == REFERENCE:
            return np.ones(n, dtype=np.float32), np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
        months = np.asarray(months)
        gi = self.kg_index[rows]
        cal = months % 12
        recent = (months >= RECENT_START) if sensor in RECENT_WINDOW_SENSORS else np.zeros(n, dtype=bool)
        k = np.full(n, np.nan, dtype=np.float32)
        basis = np.full(n, -1, dtype=np.int8)
        for window, mask in (("era", ~recent), ("recent", recent)):
            tab = self.factors.k.get((sensor, window, dn))
            if tab is None:
                continue
            sel = mask & (gi >= 0)
            k[sel] = tab[gi[sel], cal[sel]]
            basis[sel] = self.factors.basis[(sensor, window, dn)][gi[sel], cal[sel]]
        missing = ~np.isfinite(k)
        fallback = np.isin(basis, FALLBACK_CODES)
        k[missing] = 0.0
        return k, fallback, missing

    def check_missing(self, sensor: str, rows, months, counts, dn: str, missing: np.ndarray) -> None:
        bad = missing & (np.asarray(counts) > 0)
        if bad.any():
            first = np.nonzero(bad)[0][:5]
            where = [
                f"(kgroup {int(self.kgroup[rows[i]])}, calmonth {int(months[i]) % 12 + 1}, {dn}, {sensor})" for i in first
            ]
            raise ValueError(f"missing conversion factor for {int(bad.sum())} series rows, e.g. {', '.join(where)}")



@dataclass(eq=False)
class Store:
    root: Path
    cells: Cells
    klookup: KLookup
    H: sp.csr_matrix
    CONV: sp.csr_matrix
    FALLBACK: sp.csr_matrix
    FRP: sp.csr_matrix
    RAW: dict[str, sp.csr_matrix]
    SER: dict[str, sp.csr_matrix]
    months: list[int]
    manifest: dict
    harmonization: dict
    events: list
    days: pl.DataFrame
    regions: regions_mod.RegionIndex
    first_month: int
    cur_month: int
    last_complete_date: date
    incomplete: set[int]
    base_years: list[int]
    month_sensors: dict[int, list[str]] = field(default_factory=dict)
    month_source: dict[int, str] = field(default_factory=dict)
    forecast: forecasts.ModelForecast | None = None  # the model forecast of the version, when it has one
    seam: dict | None = None  # the check of the seam between the sensors, when the version has it
    # What is worked out from this version (areas, weights, the live fires, name index) lives here, so it goes away
    # with the version when the server loads a newer one.
    memo: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _memo_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _making: dict[str, threading.Lock] = field(default_factory=dict, init=False, repr=False)

    def once(self, key: str, make: Callable[[], Any]) -> Any:
        """The thing of this version under `key`, made on the first ask; a slow maker holds back only its own key."""
        found = self.memo.get(key)
        if found is None:
            with self._making.setdefault(key, threading.Lock()):
                found = self.memo.get(key)
                if found is None:
                    found = self.memo[key] = make()
        return found

    def lru(self, name: str, key: Any, make: Callable[[], Any], limit: int) -> Any:
        """Like `once` for many keys under `name`, the least recently used leaving beyond `limit`; made outside the lock."""
        with self._memo_lock:
            cache = self.memo.setdefault(name, OrderedDict())
            if key in cache:
                cache.move_to_end(key)
                return cache[key]
        made = make()
        with self._memo_lock:
            cache[key] = made
            while len(cache) > limit:
                cache.popitem(last=False)
        return made

    @property
    def kgroup(self) -> np.ndarray:
        return self.klookup.kgroup

    @property
    def factors(self) -> Factors:
        return self.klookup.factors

    @property
    def version(self) -> str:
        return str(self.manifest["version"])

    @property
    def n_months(self) -> int:
        return self.H.shape[1]

    def k_lookup(self, sensor: str, rows: np.ndarray, months: np.ndarray, dn: str):
        return self.klookup.lookup(sensor, rows, months, dn)

    @classmethod
    def load(cls, path: Path) -> Store:
        return _load(Path(path).resolve())  # the version folder itself, not a link to it that may move


def _read(root: Path, name: str, cols: dict[str, pl.DataType]) -> pl.DataFrame:
    df = pl.read_parquet(root / name)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} lacks columns {missing}")
    return df.select([pl.col(c).cast(t) for c, t in cols.items()])


def _month_arg(value) -> int:
    return int(value) if isinstance(value, int) else parse_month_label(str(value))


SERIES_COLUMNS = {"cell_id": pl.Int32, "month": pl.Int16, "sensor": pl.Utf8, "n_day": pl.Int32, "n_night": pl.Int32,
                  "frp_day": pl.Float32, "frp_night": pl.Float32}
MONTHLY_COLUMNS = {"cell_id": pl.Int32, "month": pl.Int16, "sensor": pl.Utf8, "n_day": pl.Int32, "n_night": pl.Int32}


def _scan(root: Path, name: str, cols: dict[str, pl.DataType]) -> pl.LazyFrame:
    """Lazy read of the needed columns in narrow types, so a large table never sits in memory whole."""
    lf = pl.scan_parquet(root / name)
    missing = [c for c in cols if c not in lf.collect_schema().names()]
    if missing:
        raise ValueError(f"{name} lacks columns {missing}")
    return lf.select([pl.col(c).cast(t) for c, t in cols.items()])


CHUNK_ROWS = 500_000


def _chunk_values(k: KLookup, sensor: str, rows, months, n_d, n_n, frp_d, frp_n):
    """Harmonized count, converted part, fallback part and FRP for a slice of series rows."""
    kd, fd, md = k.lookup(sensor, rows, months, "D")
    kn, fn, mn = k.lookup(sensor, rows, months, "N")
    k.check_missing(sensor, rows, months, n_d, "D", md)
    k.check_missing(sensor, rows, months, n_n, "N", mn)
    conv_d, conv_n = kd != 1.0, kn != 1.0
    return (
        n_d * kd + n_n * kn,
        n_d * kd * conv_d + n_n * kn * conv_n,
        n_d * kd * (conv_d & fd) + n_n * kn * (conv_n & fn),
        frp_d * kd + frp_n * kn,
        n_d + n_n,
    )


def _build_matrices(cells: Cells, k: KLookup, series: pl.LazyFrame, monthly: pl.LazyFrame, n_cols: int):
    """Returns H, CONV, FALLBACK, FRP, RAW and SER as float32 CSR matrices.

    One sensor is in memory at a time and its rows are processed in slices.
    """
    row_of = cells.row_of
    shape = (len(cells.cell_id), n_cols)

    def csr(r, c, v, positive_only=False):
        if positive_only:
            keep = v > 0
            r, c, v = r[keep], c[keep], v[keep]
        return sp.coo_matrix((np.asarray(v, dtype=np.float32), (r, c)), shape=shape).tocsr()

    total: dict[str, sp.csr_matrix] = {}
    ser: dict[str, sp.csr_matrix] = {}
    names = ("h", "conv", "fb", "frp")
    sensors = sorted(series.select("sensor").unique().collect()["sensor"].to_list())
    for sensor in sensors:
        part = series.filter(pl.col("sensor") == sensor).drop("sensor").collect()
        out = {n: [] for n in (*names, "n", "r", "c")}
        for start in range(0, len(part), CHUNK_ROWS):
            piece = part.slice(start, CHUNK_ROWS)
            rows = row_of[piece["cell_id"].to_numpy()]
            keep = rows >= 0
            cols = {c: piece[c].to_numpy() for c in ("month", "n_day", "n_night", "frp_day", "frp_night")}
            if not keep.all():
                rows, cols = rows[keep], {c: v[keep] for c, v in cols.items()}
            months = cols["month"].astype(np.int32)
            f32 = {c: cols[c].astype(np.float32) for c in ("n_day", "n_night", "frp_day", "frp_night")}
            values = _chunk_values(k, sensor, rows, months, f32["n_day"], f32["n_night"], f32["frp_day"], f32["frp_night"])
            for key, v in zip((*names, "n"), values, strict=True):
                out[key].append(v)
            out["r"].append(rows)
            out["c"].append(months)
        del part
        r, c = np.concatenate(out["r"]), np.concatenate(out["c"])
        for key, positive in (("h", False), ("conv", True), ("fb", True), ("frp", False)):
            m = csr(r, c, np.concatenate(out[key]), positive)
            out[key].clear()
            total[key] = m if key not in total else total[key] + m
        ser[sensor] = csr(r, c, np.concatenate(out["n"]))
        del r, c, out
    if not total:
        raise ValueError("series_monthly.parquet is empty")
    raw: dict[str, sp.csr_matrix] = {}
    for sensor in sorted(monthly.select("sensor").unique().collect()["sensor"].to_list()):
        part = monthly.filter(pl.col("sensor") == sensor).drop("sensor").collect()
        rows = row_of[part["cell_id"].to_numpy()]
        keep = rows >= 0
        count = (part["n_day"].to_numpy() + part["n_night"].to_numpy())[keep]
        raw[sensor] = csr(rows[keep], part["month"].to_numpy()[keep].astype(np.int32), count)
        del part
    for name in SENSORS:
        raw.setdefault(name, sp.csr_matrix(shape, dtype=np.float32))
        ser.setdefault(name, sp.csr_matrix(shape, dtype=np.float32))
    return total["h"], total["conv"], total["fb"], total["frp"], raw, ser


def _load(root: Path) -> Store:
    manifest = json.loads((root / "manifest.json").read_text())
    harmonization = json.loads((root / "harmonization.json").read_text())
    events_path = root / "events.json"
    events = json.loads(events_path.read_text()) if events_path.exists() else []

    cdf = _read(root, "cells.parquet", {"cell_id": pl.Int64, "lat": pl.Float32, "lon": pl.Float32, "zone": pl.Utf8,
                                        "country": pl.Utf8, "land_frac": pl.Float32}).sort("cell_id")
    cell_id = cdf["cell_id"].to_numpy()
    cell_row, cell_col = cell_id // GRID_COLS, cell_id % GRID_COLS
    row_of = np.full(GRID_COLS * GRID_ROWS, -1, dtype=np.int32)
    row_of[cell_id] = np.arange(len(cell_id), dtype=np.int32)
    cells = Cells(
        cell_id=cell_id.astype(np.int32),
        lat=cdf["lat"].to_numpy(),
        lon=cdf["lon"].to_numpy(),
        land_frac=cdf["land_frac"].to_numpy(),
        zone=cdf["zone"].to_numpy(),
        country=cdf["country"].to_numpy(),
        west=-180.0 + cell_col * CELL_DEG,
        south=90.0 - (cell_row + 1) * CELL_DEG,
        row_of=row_of,
    )

    groups = _read(root, "cell_groups.parquet", {"cell_id": pl.Int64, "kgroup": pl.Int64})
    kgroup = np.full(len(cell_id), -1, dtype=np.int64)
    pos = row_of[groups["cell_id"].to_numpy()]
    kgroup[pos[pos >= 0]] = groups["kgroup"].to_numpy()[pos >= 0]
    factors = Factors(pl.read_parquet(root / "factors.parquet"))
    found = np.clip(np.searchsorted(factors.kg_ids, kgroup), 0, len(factors.kg_ids) - 1)
    kg_index = np.where(factors.kg_ids[found] == kgroup, found, -1)
    klookup = KLookup(kgroup=kgroup, kg_index=kg_index, factors=factors)

    series = _scan(root, "series_monthly.parquet", SERIES_COLUMNS)
    monthly = _scan(root, "monthly.parquet", MONTHLY_COLUMNS)
    first_month = _month_arg(manifest["first_month"])
    last_complete = date.fromisoformat(manifest["last_complete_date"])
    cur_month = month_of(last_complete)
    last_data_month = max(series.select(pl.col("month").max()).collect().item(),
                          monthly.select(pl.col("month").max()).collect().item())
    n_cols = max(int(last_data_month), cur_month) + 1
    H, CONV, FALLBACK, FRP, raw, ser = _build_matrices(cells, klookup, series, monthly, n_cols)

    days = _read(root, "days.parquet", {"utc_date": pl.Date, "sensor": pl.Utf8, "rows": pl.Int64, "ok": pl.Boolean,
                                         "chosen": pl.Boolean, "source": pl.Utf8})
    chosen = days.filter(pl.col("chosen")).sort("utc_date").with_columns(
        m=(pl.col("utc_date").dt.year() - 2000) * 12 + pl.col("utc_date").dt.month() - 1)
    month_sensors: dict[int, list[str]] = {}
    month_source: dict[int, str] = {}
    for m, sensor, source in zip(chosen["m"].to_list(), chosen["sensor"].to_list(), chosen["source"].to_list(),
                                 strict=True):
        order = month_sensors.setdefault(m, [])
        if sensor not in order:
            order.append(sensor)
        if source == "nrt" or m not in month_source:
            month_source[m] = source

    incomplete = {_month_arg(m) for m in manifest.get("incomplete_months", [])}
    cur_year = cur_month // 12 + 2000
    base_years = [y for y in range(max(first_month // 12 + 2000, BASE_FIRST_YEAR), cur_year)
                  if (y - 2000) * 12 >= first_month]

    return Store(
        root=root, cells=cells, klookup=klookup,
        H=H, CONV=CONV, FALLBACK=FALLBACK, FRP=FRP, RAW=raw, SER=ser,
        months=list(range(first_month, cur_month + 1)),
        manifest=manifest, harmonization=harmonization, events=events, days=days,
        regions=regions_mod.build_index(pl.read_parquet(root / "regions.parquet")),
        first_month=first_month, cur_month=cur_month, last_complete_date=last_complete,
        incomplete=incomplete, base_years=base_years, month_sensors=month_sensors, month_source=month_source,
        forecast=forecasts.load(root), seam=seam.load(root),
    )
