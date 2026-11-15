"""Fire forecast of the board: a model of the harmonized monthly counts, checked against the calendar median.

Months are absolute numbers (month 0 = 2000-01). The series of a version starts at 2000-11; the forecast reads,
fits and checks only the months from ARCHIVE_START (2003-01), the first full year of MODIS Aqua. Counts are the harmonized
detections of a published data version: `H[cell, month]` is built here the way the API builds it (series rows
times the conversion factor k of `factors.parquet`).

The model works on boxes of `BOX_DEG` degrees (many 0.25 degree cells together, which are too sparse), predicts
the log of (count + 1) over (median of the calendar month + 1) for the months T+2..T+7 from what is known at the
end of month T (T+1 is the month that runs when the data come out, part known and left out), and an area is the sum of its cells, each taking its share of the box.

Nothing of a checked year is used to fit anything that checks it: medians, shares of the model and the fit come
from the other years only (forward: the years before; leave-one-year-out: all the others).
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import scipy.sparse as sp
import shapely

from . import config

GRID_COLS, GRID_ROWS, CELL_DEG = 1440, 720, 0.25
ARCHIVE_START = 36  # 2003-01: the first month the forecast reads; earlier months of the series are left out
REFERENCE = "viirs_snpp"
RECENT_START = (2022 - 2000) * 12  # months from 2022-01 use the "recent" window for modis_aqua
RECENT_SENSORS = {"modis_aqua"}
# The month that is running when the data are published is part known (12 days of it are in), so it is not
# forecast: the forecast starts with the month after it, 2 months after the last complete one, and runs six months.
HORIZONS = (2, 3, 4, 5, 6, 7)
BOX_DEG = 1.0
MIN_BOX_TOTAL = 50  # a box with fewer harmonized detections in all years is left to the median
FIRST_TEST_YEAR, LAST_TEST_YEAR = 2015, 2025


# ---------------------------------------------------------------- data


@dataclass
class Data:
    """Harmonized counts of a version: cells x months (from ARCHIVE_START) and the cell table."""

    cells: pl.DataFrame  # cell_id, lat, lon, zone, country, land_frac, in the order of the rows of H
    H: sp.csr_matrix  # [cells, months], float32
    last_seen: int  # absolute number of the last complete month
    base_years: list[int]  # complete years, the baseline of the board
    partial: np.ndarray | None = None  # [cells] harmonized counts of the running month so far (not complete)

    @property
    def n_months(self) -> int:
        return self.H.shape[1]

    def col(self, month: int) -> int:
        return month - ARCHIVE_START


def _k_tables(factors: pl.DataFrame, kg_ids: np.ndarray) -> dict[tuple[str, str, str], np.ndarray]:
    tables = {}
    for (sensor, window, dn), part in factors.group_by(["sensor", "window", "dn"]):
        tab = np.full((len(kg_ids), 12), np.nan, dtype=np.float32)
        gi = np.searchsorted(kg_ids, part["kgroup"].to_numpy())
        tab[gi, part["calmonth"].to_numpy() - 1] = part["k"].to_numpy()
        tables[(sensor, window, dn)] = tab
    return tables


def _k(tables, kg_index: np.ndarray, sensor: str, rows: np.ndarray, months: np.ndarray, dn: str) -> np.ndarray:
    """Conversion factor of each (cell row, absolute month); nan where the table has none."""
    if sensor == REFERENCE:
        return np.ones(len(rows), np.float32)
    gi, cal = kg_index[rows], months % 12
    recent = (months >= RECENT_START) if sensor in RECENT_SENSORS else np.zeros(len(rows), bool)
    k = np.full(len(rows), np.nan, np.float32)
    for window, mask in (("era", ~recent), ("recent", recent)):
        tab = tables.get((sensor, window, dn))
        sel = mask & (gi >= 0)
        if tab is not None and sel.any():
            k[sel] = tab[gi[sel], cal[sel]]
    return k


def load(version: Path) -> Data:
    """Read a published version and build the harmonized cell x month matrix."""
    from datetime import date

    manifest = json.loads((version / "manifest.json").read_text())
    cells = pl.read_parquet(version / "cells.parquet").sort("cell_id")
    cell_id = cells["cell_id"].to_numpy().astype(np.int64)
    row_of = np.full(GRID_COLS * GRID_ROWS, -1, np.int32)
    row_of[cell_id] = np.arange(len(cell_id), dtype=np.int32)
    groups = pl.read_parquet(version / "cell_groups.parquet")
    kgroup = np.full(len(cell_id), -1, np.int64)
    pos = row_of[groups["cell_id"].to_numpy()]
    kgroup[pos[pos >= 0]] = groups["kgroup"].to_numpy()[pos >= 0]
    factors = pl.read_parquet(version / "factors.parquet")
    kg_ids = np.unique(factors["kgroup"].to_numpy())
    found = np.clip(np.searchsorted(kg_ids, kgroup), 0, len(kg_ids) - 1)
    kg_index = np.where(kg_ids[found] == kgroup, found, -1)
    tables = _k_tables(factors, kg_ids)

    last_date = date.fromisoformat(manifest["last_complete_date"])
    cur_month = (last_date.year - 2000) * 12 + last_date.month - 1  # running month, not complete
    last_seen = cur_month - 1
    n_months = last_seen - ARCHIVE_START + 1
    n_cols = n_months + 1  # the running month is read too, to be set apart
    series = pl.scan_parquet(version / "series_monthly.parquet").select(
        "cell_id", "month", "sensor", "n_day", "n_night"
    )
    total = sp.csr_matrix((len(cell_id), n_cols), dtype=np.float32)
    for sensor in sorted(series.select("sensor").unique().collect()["sensor"].to_list()):
        part = series.filter((pl.col("sensor") == sensor) & (pl.col("month") >= ARCHIVE_START)
                             & (pl.col("month") <= cur_month)).collect()
        rows = row_of[part["cell_id"].to_numpy()]
        keep = rows >= 0
        rows, months = rows[keep], part["month"].to_numpy().astype(np.int32)[keep]
        nd, nn = (part[c].to_numpy().astype(np.float32)[keep] for c in ("n_day", "n_night"))
        kd, kn = (_k(tables, kg_index, sensor, rows, months, dn) for dn in ("D", "N"))
        for k, n, dn in ((kd, nd, "D"), (kn, nn, "N")):
            if (np.isnan(k) & (n > 0)).any():
                raise ValueError(f"missing conversion factor for {sensor} {dn}")
        h = nd * np.nan_to_num(kd) + nn * np.nan_to_num(kn)
        total = total + sp.coo_matrix((h, (rows, months - ARCHIVE_START)), shape=total.shape).tocsr()
        del part
    cur_year = cur_month // 12 + 2000
    partial = np.asarray(total[:, n_months].todense()).ravel()
    return Data(cells, total[:, :n_months].tocsr(), last_seen, list(range(ARCHIVE_START // 12 + 2000, cur_year)), partial)


# ---------------------------------------------------------------- areas


def area_weights(cells: pl.DataFrame, geometry: shapely.Geometry) -> tuple[np.ndarray, np.ndarray]:
    """Rows of the cells that touch the area and their weights, the share of each cell inside the geometry
    (the API measures that share on an equal-area projection; on a 0.25 degree cell the plain one is the same
    to a fraction of a percent)."""
    lat, lon = cells["lat"].to_numpy(), cells["lon"].to_numpy()
    x0, y0, x1, y1 = geometry.bounds
    near = np.nonzero((lon + CELL_DEG / 2 >= x0 - CELL_DEG) & (lon - CELL_DEG / 2 <= x1 + CELL_DEG)
                      & (lat + CELL_DEG / 2 >= y0 - CELL_DEG) & (lat - CELL_DEG / 2 <= y1 + CELL_DEG))[0]
    if len(near) == 0:
        return near, np.zeros(0)
    west, south = lon[near] - CELL_DEG / 2, lat[near] - CELL_DEG / 2
    boxes = shapely.box(west, south, west + CELL_DEG, south + CELL_DEG)
    shapely.prepare(geometry)
    w = np.zeros(len(near))
    full = shapely.covers(geometry, boxes)
    w[full] = 1.0
    part = ~full & shapely.intersects(geometry, boxes)
    if part.any():
        w[part] = np.minimum(1.0, shapely.area(shapely.intersection(boxes[part], geometry)) / CELL_DEG**2)
    keep = (w > 0) & (cells["land_frac"].to_numpy()[near] > 0)
    return near[keep], w[keep]


def weight_matrix(n_cells: int, items: list[tuple[np.ndarray, np.ndarray]]) -> sp.csr_matrix:
    """[areas, cells] sparse weights."""
    rows = np.concatenate([np.full(len(i), a) for a, (i, _) in enumerate(items)])
    cols = np.concatenate([i for i, _ in items])
    vals = np.concatenate([w for _, w in items])
    return sp.coo_matrix((vals, (rows, cols)), shape=(len(items), n_cells)).tocsr()


# ---------------------------------------------------------------- boxes


@dataclass
class Boxes:
    """The model grid: which box each cell is in and the counts per box and month."""

    of_cell: np.ndarray  # [cells] -> box index
    ids: np.ndarray  # [boxes] -> row * cols + col of the box in the box grid
    rows: np.ndarray
    cols: np.ndarray
    Y: np.ndarray  # [boxes, months] float32 harmonized counts
    lat: np.ndarray
    zone: np.ndarray  # biome number of the box, 0 for none
    neighbors: np.ndarray  # [boxes, 8] box index of the neighbours, -1 for none

    @property
    def n(self) -> int:
        return len(self.ids)


def make_boxes(data: Data, deg: float = BOX_DEG) -> Boxes:
    f = round(deg / CELL_DEG)
    cid = data.cells["cell_id"].to_numpy().astype(np.int64)
    r, c = cid // GRID_COLS // f, cid % GRID_COLS // f
    n_cols = GRID_COLS // f
    gid = r * n_cols + c
    ids, of_cell = np.unique(gid, return_inverse=True)
    ind = sp.coo_matrix((np.ones(len(cid), np.float32), (of_cell, np.arange(len(cid)))), shape=(len(ids), len(cid))).tocsr()
    Y = np.asarray((ind @ data.H).todense(), dtype=np.float32)
    keep = Y.sum(axis=1) > 0  # boxes without any fire in the archive are not part of the model at all
    remap = np.full(len(ids), -1, np.int64)
    remap[keep] = np.arange(keep.sum())
    of_cell = remap[of_cell]
    ids, Y = ids[keep], Y[keep]
    rows, cols = ids // n_cols, ids % n_cols
    ok = of_cell >= 0
    cell_total = np.asarray(data.H.sum(axis=1)).ravel()  # only to pick the main cell of a box for its biome
    lookup = {int(g): i for i, g in enumerate(ids)}
    n_rows = GRID_ROWS // f
    nb = np.full((len(ids), 8), -1, np.int64)
    k = 0
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            rr, cc = rows + dr, (cols + dc) % n_cols
            nb[:, k] = [lookup.get(int(a * n_cols + b), -1) if 0 <= a < n_rows else -1 for a, b in zip(rr, cc, strict=True)]
            k += 1
    zone_of_cell = data.cells["zone"].to_list()
    zone = np.zeros(len(ids), np.int64)
    best = np.zeros(len(ids))
    for i in np.nonzero(ok)[0]:
        b = of_cell[i]
        if cell_total[i] >= best[b]:
            best[b] = cell_total[i]
            z = zone_of_cell[i]
            zone[b] = int(z.split("-")[1]) * (1 if z.endswith("n") else -1) if z.startswith("resolve") else 0
    cell_lat = data.cells["lat"].to_numpy()
    lat = np.bincount(of_cell[ok], weights=cell_lat[ok], minlength=len(ids)) / np.maximum(np.bincount(of_cell[ok], minlength=len(ids)), 1)
    return Boxes(of_cell, ids, rows, cols, Y, lat, zone, nb)


def box_to_area(boxes: Boxes, W: sp.csr_matrix, cell_total: np.ndarray) -> sp.csr_matrix:
    """[areas, boxes]: the part of each box's count that falls into an area, the cells' weights times the
    share each cell holds of its box, by the counts `cell_total` of the training window only."""
    ok = boxes.of_cell >= 0
    box_total = np.bincount(boxes.of_cell[ok], weights=cell_total[ok], minlength=boxes.n)
    share = np.zeros(len(boxes.of_cell))
    share[ok] = cell_total[ok] / np.maximum(box_total[boxes.of_cell[ok]], 1e-9)
    ind = sp.coo_matrix((share[ok], (np.nonzero(ok)[0], boxes.of_cell[ok])), shape=(len(boxes.of_cell), boxes.n)).tocsr()
    return (W @ ind).tocsr()


# ---------------------------------------------------------------- medians and anomalies


def calendar_medians(Y: np.ndarray, years: list[int]) -> np.ndarray:
    """Median of each calendar month over `years`, [rows, 12]. Y columns start at the archive start."""
    cols = np.array([[(y - 2000) * 12 + m - ARCHIVE_START for m in range(12)] for y in years])
    return np.median(Y[:, cols], axis=1)  # [rows, 12]


def anomalies(Y: np.ndarray, med: np.ndarray) -> np.ndarray:
    """log((count + 1) / (median of the calendar month + 1)) for every month of Y."""
    cal = (np.arange(Y.shape[1]) + ARCHIVE_START) % 12
    return np.log1p(Y) - np.log1p(med[:, cal])


# ---------------------------------------------------------------- the checked areas


@dataclass
class Setup:
    data: Data
    boxes: Boxes
    names: list[str]  # area ids, "world" first
    kinds: list[str]  # world | country | region
    W: sp.csr_matrix  # [areas, cells] weights
    real: np.ndarray  # [areas, months] counts of the areas, rounded like the board does


def build(version: Path, kinds: tuple[str, ...] = ("country", "region"), only: list[str] | None = None,
          deg: float = BOX_DEG, data: Data | None = None) -> Setup:
    data = data or load(version)
    boxes = make_boxes(data, deg)
    regions = pl.read_parquet(version / "regions.parquet").filter(pl.col("kind").is_in(kinds))
    if only is not None:
        regions = regions.filter(pl.col("id").is_in(only))
    items = [(np.arange(len(data.cells)), np.ones(len(data.cells)))]
    names, kinds_out = ["world"], ["world"]
    for rid, kind, wkb in zip(regions["id"].to_list(), regions["kind"].to_list(), regions["geometry_wkb"].to_list(), strict=True):
        idx, w = area_weights(data.cells, shapely.from_wkb(wkb))
        if len(idx):
            items.append((idx, w))
            names.append(rid)
            kinds_out.append(kind)
    W = weight_matrix(len(data.cells), items)
    real = np.rint(np.asarray((W @ data.H).todense())).astype(np.float64)
    return Setup(data, boxes, names, kinds_out, W, real)


def year_cols(year: int) -> np.ndarray:
    return np.arange(12) + (year - 2000) * 12 - ARCHIVE_START


# ---------------------------------------------------------------- baselines (calendar medians of the areas)


@dataclass
class Clim:
    """The calendar of each area: median and 10th / 90th percentile of the calendar month, per target month."""

    med: np.ndarray
    lo: np.ndarray
    hi: np.ndarray


def climatology(real: np.ndarray, years: list[int], mode: str, test_years: list[int]) -> Clim:
    """mode "forward": each test year from the base years before it; "loyo": from all the other base years
    (the board's own check)."""
    out = [np.full(real.shape, np.nan) for _ in range(3)]
    for y in test_years:
        past = [x for x in years if (x < y if mode == "forward" else x != y)]
        cube = np.stack([real[:, year_cols(x)] for x in past], axis=1)
        cols = year_cols(y)
        out[0][:, cols] = np.median(cube, axis=1)
        out[1][:, cols] = np.percentile(cube, 10, axis=1)
        out[2][:, cols] = np.percentile(cube, 90, axis=1)
    return Clim(*out)


def board_year_error(real: np.ndarray, years: list[int]) -> np.ndarray:
    """`Ser.accuracy` of the API: yearly error of the leave-one-year-out median over every base year."""
    guess = climatology(real, years, "loyo", years).med
    err = sum(np.abs(guess[:, year_cols(y)].sum(axis=1) - real[:, year_cols(y)].sum(axis=1)) for y in years)
    return err / np.maximum(1.0, sum(real[:, year_cols(y)].sum(axis=1) for y in years))


# ---------------------------------------------------------------- the state of one fit: medians, anomalies, boxes


@dataclass
class State:
    years: list[int]  # base years the medians come from
    allowed: np.ndarray  # [months] bool: the months training may look at
    med: np.ndarray  # [boxes, 12]
    A: np.ndarray  # [boxes, months] anomalies
    nbA: np.ndarray  # mean anomaly of the neighbours
    csum: np.ndarray  # [boxes, months + 1] running sum of A
    sel: np.ndarray  # [boxes] bool: the model works here
    S: sp.csr_matrix  # [areas, boxes]


def make_state(setup: Setup, years: list[int], allowed: np.ndarray, extra: dict[str, np.ndarray] | None = None) -> State:
    """Everything that is estimated from the training window only: medians, which boxes are active enough, how a
    box splits among areas. `extra` are further [boxes, months] planes known at the end of each month (weather)."""
    boxes, data = setup.boxes, setup.data
    med = calendar_medians(boxes.Y, years)
    A = anomalies(boxes.Y, med)
    cell_total = np.asarray(data.H @ allowed.astype(np.float32)).ravel()
    ok = boxes.of_cell >= 0
    box_total = np.bincount(boxes.of_cell[ok], weights=cell_total[ok], minlength=boxes.n)
    sel = box_total >= MIN_BOX_TOTAL
    pad = np.vstack([A, np.zeros((1, A.shape[1]), A.dtype)])
    nb = boxes.neighbors
    nbsum = sum(pad[nb[:, k]] for k in range(8))
    nbA = nbsum / np.maximum((nb >= 0).sum(axis=1), 1)[:, None]
    csum = np.concatenate([np.zeros((boxes.n, 1), np.float64), np.cumsum(A, axis=1, dtype=np.float64)], axis=1)
    return State(years, allowed, med, A, nbA.astype(np.float32), csum, sel, box_to_area(boxes, setup.W, cell_total))


def area_forecast(st: State, P: np.ndarray, cal: np.ndarray, base: np.ndarray) -> np.ndarray:
    """Counts of the areas from the counts `P` of the boxes. Medians do not add up (the sum of the medians of the
    cells is 80 % of the median of the area), so the boxes only say how far a month is above or below its
    normal, on the log(count + 1) scale of the model: area = (median of the area + 1) times (sum of the forecast
    boxes + 1) / (sum of the median boxes + 1), less 1. The +1 keeps a small area from being thrown about."""
    num = st.S @ P
    den = st.S @ st.med[:, cal]
    return np.maximum((base + 1.0) * (num + 1.0) / (den + 1.0) - 1.0, 0.0)


def boxes_from_anomaly(st: State, anomaly: np.ndarray, cal: np.ndarray) -> np.ndarray:
    """Counts of the boxes: the median of the month times exp(anomaly) where the model works, the median elsewhere."""
    base = st.med[:, cal]
    return np.where(st.sel[:, None], np.maximum((base + 1.0) * np.exp(anomaly) - 1.0, 0.0), base)


# ---------------------------------------------------------------- features


BASE_FEATURES = (
    *[f"a{k}" for k in range(12)], "nb0", "nb1", "nb2", "sum3", "sum6", "sum12", "trend",
    "sin", "cos", "h", "lat", "zone", "lmed", "lbox",
)
ZONE = BASE_FEATURES.index("zone")
LAGS = 12  # the first month of a start needs this many months behind it


def gather(st: State, boxes: Boxes, b: np.ndarray, t: np.ndarray, h: int, extra: dict[str, np.ndarray] | None = None) -> np.ndarray:
    """Features of the (box, start month) pairs for the target month t + h. Only months up to t are looked at.
    `extra` planes add their last four months as columns, so a new source needs no change here."""
    names = list(extra) if extra else []
    X = np.empty((len(b), len(BASE_FEATURES) + 4 * len(names)), np.float32)
    for k in range(12):
        X[:, k] = st.A[b, t - k]
    for k in range(3):
        X[:, 12 + k] = st.nbA[b, t - k]
    cs = st.csum
    for i, k in enumerate((3, 6, 12)):
        X[:, 15 + i] = cs[b, t + 1] - cs[b, t + 1 - k]
    older = (cs[b, np.maximum(t - 11, 0)] - cs[b, np.maximum(t - 23, 0)]) / 12
    X[:, 18] = np.where(t >= 23, (cs[b, t + 1] - cs[b, t - 11]) / 12 - older, 0.0)  # this year against the one before
    cal = (t + h + ARCHIVE_START) % 12
    X[:, 19], X[:, 20] = np.sin(2 * np.pi * cal / 12), np.cos(2 * np.pi * cal / 12)
    X[:, 21] = h
    X[:, 22] = boxes.lat[b]
    X[:, 23] = boxes.zone[b] + 14
    X[:, 24] = np.log1p(st.med[b, cal])
    X[:, 25] = np.log1p(st.med[b].sum(axis=1))
    for i, name in enumerate(names):
        for k in range(4):
            X[:, len(BASE_FEATURES) + 4 * i + k] = extra[name][b, t - k]
    return X


def eligible_starts(allowed: np.ndarray, h: int) -> np.ndarray:
    """Start months whose whole window (LAGS months back to the target h ahead) is inside the training months."""
    m = len(allowed)
    bad = np.concatenate([[0], np.cumsum(~allowed)])
    t = np.arange(LAGS - 1, m - h)
    return t[bad[t + h + 1] - bad[t - LAGS + 1] == 0]


def sample_rows(st: State, h: int, rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    """About `n` (box, start) pairs of the active boxes, the more likely the larger the box, so that the fit
    cares for the boxes that make the sums; every kept pair then counts the same."""
    starts = eligible_starts(st.allowed, h)
    boxes_idx = np.nonzero(st.sel)[0]
    cal = (starts + h + ARCHIVE_START) % 12
    w = np.sqrt(st.med[np.ix_(boxes_idx, np.arange(12))][:, cal] + 1.0)  # [boxes, starts]
    keep = rng.random(w.shape) < np.minimum(1.0, n * w / w.sum())
    bi, ti = np.nonzero(keep)
    return boxes_idx[bi], starts[ti]


# ---------------------------------------------------------------- models: each returns predict(h, start months) -> anomaly [boxes, n]


Predictor = Callable[[int, np.ndarray], np.ndarray]
ROWS_PER_H = 50_000
RIDGE_ALPHA = 30.0


def fit_persistence(st: State, setup: Setup, rng: np.random.Generator, extra=None) -> Predictor:
    """anomaly(T + h) = c_h + rho_h * anomaly(T): two numbers per horizon, weighted least squares over the active
    boxes, on the pairs of months that are both training months."""
    As = st.A[st.sel]
    cal = (np.arange(As.shape[1]) + ARCHIVE_START) % 12
    wt = np.sqrt(st.med[st.sel][:, cal] + 1.0)
    coef, rows = {}, 0
    for h in HORIZONS:
        t = np.arange(As.shape[1] - h)
        t = t[st.allowed[t] & st.allowed[t + h]]
        rows += len(t) * As.shape[0]
        x, y, w = As[:, t], As[:, t + h], wt[:, t + h]
        sw = w.sum()
        mx, my = (w * x).sum() / sw, (w * y).sum() / sw
        rho = (w * (x - mx) * (y - my)).sum() / max((w * (x - mx) ** 2).sum(), 1e-12)
        coef[h] = (my - rho * mx, rho)

    def predict(h: int, t: np.ndarray) -> np.ndarray:
        c, rho = coef[h]
        return np.where(st.sel[:, None], c + rho * st.A[:, t], 0.0)

    predict.rows = rows  # type: ignore[attr-defined]
    return predict


def _design(X: np.ndarray, h: np.ndarray | int, drop: tuple[int, ...] = (ZONE,)) -> np.ndarray:
    """Features for the ridge: without the biome code, plus every feature times the horizon (centred)."""
    keep = [i for i in range(X.shape[1]) if i not in drop]
    Z = X[:, keep]
    return np.hstack([Z, Z * ((np.asarray(h, np.float32) - 4.5) / 1.7).reshape(-1, 1)])


def _training_rows(st: State, setup: Setup, rng: np.random.Generator, extra) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    Xs, ys = [], []
    for h in HORIZONS:
        b, t = sample_rows(st, h, rng, ROWS_PER_H)
        Xs.append(gather(st, setup.boxes, b, t, h, extra))
        ys.append(st.A[b, t + h])
    return np.vstack(Xs), np.concatenate(ys), np.concatenate([np.full(len(y), h) for h, y in zip(HORIZONS, ys, strict=True)])


def _predict_with(model, st: State, setup: Setup, h: int, t: np.ndarray, extra, transform) -> np.ndarray:
    sel = np.nonzero(st.sel)[0]
    b, tt = np.repeat(sel, len(t)), np.tile(t, len(sel))
    X = gather(st, setup.boxes, b, tt, h, extra)
    out = np.zeros((st.sel.shape[0], len(t)))
    out[sel] = model(transform(X, h)).reshape(len(sel), len(t))
    return out


def fit_ridge(st: State, setup: Setup, rng: np.random.Generator, extra=None) -> Predictor:
    X, y, hs = _training_rows(st, setup, rng, extra)
    D = _design(X, hs)
    mu, sd = D.mean(axis=0), D.std(axis=0) + 1e-6
    D = (D - mu) / sd
    ym = y.mean()
    coef = np.linalg.solve(D.T @ D + RIDGE_ALPHA * np.eye(D.shape[1]), D.T @ (y - ym))

    def predict(h: int, t: np.ndarray) -> np.ndarray:
        return _predict_with(lambda Z: ym + Z @ coef, st, setup, h, t, extra, lambda X, h: (_design(X, h) - mu) / sd)

    predict.rows = len(y)  # type: ignore[attr-defined]
    return predict


def fit_boosting(st: State, setup: Setup, rng: np.random.Generator, extra=None) -> Predictor:
    from sklearn.ensemble import HistGradientBoostingRegressor

    X, y, _ = _training_rows(st, setup, rng, extra)
    model = HistGradientBoostingRegressor(
        max_iter=120, learning_rate=0.1, max_leaf_nodes=31, min_samples_leaf=100, l2_regularization=1.0,
        categorical_features=[ZONE], random_state=0,
    ).fit(X, y)

    def predict(h: int, t: np.ndarray) -> np.ndarray:
        return _predict_with(model.predict, st, setup, h, t, extra, lambda X, h: X)

    predict.rows = len(y)  # type: ignore[attr-defined]
    return predict


MODELS = {"persistence": fit_persistence, "ridge": fit_ridge, "boosting": fit_boosting}


# ---------------------------------------------------------------- running folds


def window(setup: Setup, mode: str, year: int) -> tuple[list[int], np.ndarray]:
    """Base years for the medians and the months training may use when `year` is checked.
    forward: only what ended before the year; loyo: everything except the year."""
    months = setup.real.shape[1]
    cols = year_cols(year)
    if mode == "forward":
        return [x for x in setup.data.base_years if x < year], np.arange(months) < cols[0]
    allowed = np.ones(months, bool)
    allowed[cols] = False
    return [x for x in setup.data.base_years if x != year], allowed


def run_folds(setup: Setup, model: str, mode: str, years: list[int], extra=None, seed: int = 0) -> dict[int, np.ndarray]:
    """The forecasts of every month of each checked year at each horizon, per_h[h][area, month] (nan elsewhere)."""
    per_h = {h: np.full(setup.real.shape, np.nan) for h in HORIZONS}
    clim = climatology(setup.real, setup.data.base_years, mode, years)
    for y in years:
        train_years, allowed = window(setup, mode, y)
        st = make_state(setup, train_years, allowed, extra)
        predict = MODELS[model](st, setup, np.random.default_rng(seed + y), extra)
        cols = year_cols(y)
        for h in HORIZONS:
            cal = (cols + ARCHIVE_START) % 12
            P = boxes_from_anomaly(st, predict(h, cols - h), cal)
            per_h[h][:, cols] = area_forecast(st, P, cal, clim.med[:, cols])
    return per_h


# ---------------------------------------------------------------- the range: residuals of the areas, by size


SIZE_EDGES = (300.0, 3000.0, 30000.0)  # mean detections per year of an area: four classes
QUANTILES = (0.10, 0.90)


def size_class(real: np.ndarray, years: list[int]) -> np.ndarray:
    yearly = np.stack([real[:, year_cols(y)].sum(axis=1) for y in years], axis=1).mean(axis=1)
    return np.searchsorted(np.array(SIZE_EDGES), yearly)


NOISE_FLOOR = 0.05


def noise(real: np.ndarray, years: list[int]) -> np.ndarray:
    """How unsteady each area is: the mean absolute log error of its own calendar median (each of `years`
    guessed from the others), [areas]. A range is scaled by it, since a country is far steadier than a province."""
    cube = np.stack([real[:, year_cols(y)] for y in years], axis=1)  # [areas, years, 12]
    guess = np.stack([np.median(np.delete(cube, k, axis=1), axis=1) for k in range(len(years))], axis=1)
    return np.maximum(np.abs(np.log1p(guess) - np.log1p(cube)).mean(axis=(1, 2)), NOISE_FLOOR)


def residual_quantiles(res: dict[int, np.ndarray], cls: np.ndarray) -> np.ndarray:
    """[horizon, class, 2]: the 10th and 90th percentile of the scaled log residuals of the areas of a size class."""
    out = np.zeros((len(HORIZONS), len(SIZE_EDGES) + 1, 2))
    for i, h in enumerate(HORIZONS):
        for c in range(len(SIZE_EDGES) + 1):
            pool = res[h][cls == c].ravel()
            pool = pool[np.isfinite(pool)]
            if len(pool) >= 50:
                out[i, c] = np.quantile(pool, QUANTILES)
            else:  # too few areas of that size: borrow the nearby class
                out[i, c] = out[i, c - 1] if c else (-1.0, 1.0)
    return out


def scaled_residuals(setup: Setup, per_h: dict[int, np.ndarray], mode: str, calib: list[int]) -> dict[int, np.ndarray]:
    """Log residual (real against forecast) of each area, divided by the unsteadiness of the area in the year's
    own training window; [areas, months], nan outside the `calib` years."""
    real = setup.real
    out = {h: np.full(real.shape, np.nan) for h in HORIZONS}
    for x in calib:
        cols = year_cols(x)
        scale = noise(real, window(setup, mode, x)[0])
        for h in HORIZONS:
            out[h][:, cols] = (np.log1p(real[:, cols]) - np.log1p(per_h[h][:, cols])) / scale[:, None]
    return out


def apply_range(forecast: np.ndarray, q: np.ndarray, cls: np.ndarray, scale: np.ndarray, i: int) -> tuple[np.ndarray, np.ndarray]:
    """10th and 90th percentile of `forecast` [areas, n] for horizon index i from quantiles `q` [horizon, class, 2]."""
    lg = np.log1p(forecast)
    return (np.expm1(lg + (q[i, cls, 0] * scale)[:, None]), np.expm1(lg + (q[i, cls, 1] * scale)[:, None]))


def with_range(setup: Setup, per_h: dict[int, np.ndarray], mode: str, years: list[int], calib: list[int]) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """10th and 90th percentile of the forecast of each checked year. The scaled log residuals of the areas, by
    horizon and size class, over the `calib` years of the same kind of check (forward: the years before the checked
    one; loyo: the other years), multiplied back by the unsteadiness of the area in the checked year."""
    real = setup.real
    out = {h: (np.full(real.shape, np.nan), np.full(real.shape, np.nan)) for h in HORIZONS}
    scaled = scaled_residuals(setup, per_h, mode, calib)
    for y in years:
        pool_years = [x for x in calib if (x < y if mode == "forward" else x != y)]
        if not pool_years:
            continue
        train_years, _ = window(setup, mode, y)
        cls, scale = size_class(real, train_years), noise(real, train_years)
        pool = np.concatenate([year_cols(x) for x in pool_years])
        q = residual_quantiles({h: scaled[h][:, pool] for h in HORIZONS}, cls)
        cols = year_cols(y)
        for i, h in enumerate(HORIZONS):
            out[h][0][:, cols], out[h][1][:, cols] = apply_range(per_h[h][:, cols], q, cls, scale, i)
    return out


# ---------------------------------------------------------------- scores


TEST_YEARS = list(range(FIRST_TEST_YEAR, LAST_TEST_YEAR + 1))
CALIB_YEARS = list(range(2009, LAST_TEST_YEAR + 1))  # forward folds; the first test years borrow their residuals
MIN_GAIN = 0.10  # the model must beat the calendar median by this share of its error
COVERAGE_BAND = (0.70, 0.90)  # nominal 0.80
MIN_TEST_TOTAL = 100  # an area with fewer detections in the test years is not scored


@dataclass
class Score:
    """Sums behind the scores of every area, so that any group of areas can be pooled afterwards."""

    err: np.ndarray  # [horizons, areas] sum of |forecast - real|
    real: np.ndarray  # [areas] sum of real
    med: np.ndarray  # [areas] sum of the calendar median
    err6: np.ndarray  # [areas] |six-month forecast total - real total| summed over starts
    real6: np.ndarray  # [areas]
    hit: np.ndarray  # [horizons, areas] months inside the range
    n: np.ndarray  # [areas] months scored


def score(real: np.ndarray, per_h: dict[int, np.ndarray], lo_hi: dict[int, tuple[np.ndarray, np.ndarray]], med: np.ndarray, cols: np.ndarray) -> Score:
    cset = set(cols.tolist())
    starts = np.array([t for t in cols if all((t + h) in cset for h in HORIZONS)])
    err = np.stack([np.abs(per_h[h][:, cols] - real[:, cols]).sum(axis=1) for h in HORIZONS])
    hit = np.stack([((lo_hi[h][0][:, cols] <= real[:, cols]) & (real[:, cols] <= lo_hi[h][1][:, cols])).sum(axis=1) for h in HORIZONS])
    f6 = sum(per_h[h][:, starts + h] for h in HORIZONS)
    r6 = sum(real[:, starts + h] for h in HORIZONS)
    return Score(err, real[:, cols].sum(axis=1), med[:, cols].sum(axis=1), np.abs(f6 - r6).sum(axis=1), r6.sum(axis=1),
                 hit, np.full(real.shape[0], len(cols)))


def baseline_score(real: np.ndarray, clim: Clim, cols: np.ndarray) -> Score:
    """The calendar median as a forecast: the same at every horizon, its own 10-90 percentile as the range."""
    return score(real, {h: clim.med for h in HORIZONS}, {h: (clim.lo, clim.hi) for h in HORIZONS}, clim.med, cols)


def pooled(sc: Score, idx: np.ndarray) -> dict:
    """Errors in % of the real counts (the sum of the errors of the areas over the sum of their counts), the same
    for the next six months, the mean absolute error of a month in shares of the calendar median, and coverage."""
    real, med = max(1.0, sc.real[idx].sum()), max(1.0, sc.med[idx].sum())
    return {
        "err_pct": [round(100 * float(sc.err[i, idx].sum() / real), 1) for i in range(len(HORIZONS))],
        "sum6_pct": round(100 * float(sc.err6[idx].sum() / max(1.0, sc.real6[idx].sum())), 1),
        "mae_of_median": [round(float(sc.err[i, idx].sum() / med), 3) for i in range(len(HORIZONS))],
        "coverage": [round(float(sc.hit[i, idx].sum() / sc.n[idx].sum()), 3) for i in range(len(HORIZONS))],
    }


def scored_areas(setup: Setup, cols: np.ndarray) -> np.ndarray:
    """Areas with enough detections in the test months to be scored."""
    return np.nonzero(setup.real[:, cols].sum(axis=1) >= MIN_TEST_TOTAL)[0]


def use_model(model: Score, base: Score, scored: np.ndarray) -> np.ndarray:
    """[horizons, areas] bool: the model is used on horizons 1..K, K the largest horizon up to which every horizon
    beats the forward calendar median by MIN_GAIN of its error and has a range that covers 70-90 % of the months.
    Past K the calendar median is shown as it is, so the chart has one step from model to median and no more."""
    gain = 1.0 - model.err / np.maximum(base.err, 1e-9)
    cover = model.hit / np.maximum(model.n, 1)
    ok = np.logical_and.accumulate((gain >= MIN_GAIN) & (cover >= COVERAGE_BAND[0]) & (cover <= COVERAGE_BAND[1]), axis=0)
    ok[:, np.setdiff1d(np.arange(model.err.shape[1]), scored)] = False
    return ok


# ---------------------------------------------------------------- the whole check and the forecast of the last month


@dataclass
class Check:
    per: dict[int, np.ndarray]
    rng: dict[int, tuple[np.ndarray, np.ndarray]]
    sc: Score


def event_list(version: Path) -> list[tuple[str, str]]:
    path = version / "events.json"
    if not path.exists():
        return []
    return [(e["region_id"], e["month"]) for e in json.loads(path.read_text())]


def month_col(label: str) -> int:
    y, m = label.split("-")
    return (int(y) - 2000) * 12 + int(m) - 1 - ARCHIVE_START


def slices(setup: Setup, scored: np.ndarray) -> dict[str, np.ndarray]:
    names, kinds = setup.names, setup.kinds
    is_scored = np.zeros(len(names), bool)
    is_scored[scored] = True
    pick = lambda cond: np.array([i for i in range(len(names)) if cond(i) and is_scored[i]], dtype=int)
    return {
        "world": np.array([0]),
        "argentina": np.array([names.index("AR")] if "AR" in names and is_scored[names.index("AR")] else [], dtype=int),
        "countries": pick(lambda i: kinds[i] == "country"),
        "argentina_provinces": pick(lambda i: kinds[i] == "region" and names[i].startswith("AR-")),
        "regions": pick(lambda i: kinds[i] == "region"),
    }


def evaluate(setup: Setup, events: list[tuple[str, str]], models: tuple[str, ...] = tuple(MODELS), log=print) -> dict:
    """Forward and leave-one-year-out checks of every model against the calendar median; the pooled tables, the
    table of the known seasons, the per-area scores and the choice of the model that goes on the site."""
    real, years = setup.real, setup.data.base_years
    cols = np.concatenate([year_cols(y) for y in TEST_YEARS])
    scored = scored_areas(setup, cols)
    event_years = sorted({int(m[:4]) for _, m in events})
    loyo_years = sorted(set(TEST_YEARS) | set(event_years))
    clim_f = climatology(real, years, "forward", CALIB_YEARS)
    clim_l = climatology(real, years, "loyo", loyo_years)
    flat = lambda c: ({h: c.med for h in HORIZONS}, {h: (c.lo, c.hi) for h in HORIZONS}, c.med)
    base_f, base_l = (score(real, *flat(c), cols) for c in (clim_f, clim_l))
    fwd: dict[str, Check] = {}
    loy: dict[str, Check] = {}
    for m in models:
        t = time.time()
        per = run_folds(setup, m, "forward", CALIB_YEARS)
        rng = with_range(setup, per, "forward", TEST_YEARS, CALIB_YEARS)
        fwd[m] = Check(per, rng, score(real, per, rng, clim_f.med, cols))
        per = run_folds(setup, m, "loyo", loyo_years)
        rng = with_range(setup, per, "loyo", loyo_years, loyo_years)
        loy[m] = Check(per, rng, score(real, per, rng, clim_l.med, cols))
        log(f"forecast: {m} checked in {time.time() - t:.0f} s")
    groups = slices(setup, scored)
    tables = {}
    for name, idx in groups.items():
        row = {"areas": len(idx), "baseline_forward": pooled(base_f, idx), "baseline_loyo": pooled(base_l, idx), "models": {}}
        for m in models:
            gain = 1.0 - fwd[m].sc.err[:, idx] / np.maximum(base_f.err[:, idx], 1e-9)
            row["models"][m] = {
                "forward": pooled(fwd[m].sc, idx), "loyo": pooled(loy[m].sc, idx),
                "areas_better_by_10pct": [round(float((gain[i] >= MIN_GAIN).mean()), 3) for i in range(len(HORIZONS))],
            }
        tables[name] = row
    # the model that goes on the site: the lowest mean error over the countries at horizons 1, 3 and 6 (forward)
    cidx = groups["countries"]
    pick = {m: float(np.mean([pooled(fwd[m].sc, cidx)["err_pct"][i] for i in (0, 2, 5)])) for m in models}
    best = min(pick, key=pick.get)
    use = use_model(fwd[best].sc, base_f, scored)
    tables["selection_holdout"] = selection_holdout(setup, fwd[best], clim_f, scored)
    seasons = []
    index = {n: i for i, n in enumerate(setup.names)}
    for rid, month in events:
        if rid not in index:
            continue
        a, c = index[rid], month_col(month)
        row = {"region_id": rid, "month": month, "real": float(real[a, c]), "calendar_median_loyo": float(clim_l.med[a, c])}
        for m in models:
            row[m] = {f"h{h}": float(loy[m].per[h][a, c]) for h in (HORIZONS[0], HORIZONS[2], HORIZONS[-1])}
        seasons.append(row)
    return {
        "tables": tables, "seasons": seasons, "choice": {"model": best, "mean_err_pct_countries": pick},
        "scored": scored, "use": use, "base_forward": base_f, "fwd": fwd, "loyo": loy,
        "climatology_forward": clim_f,
    }


def selection_holdout(setup: Setup, chk: Check, clim: Clim, scored: np.ndarray) -> dict:
    """The areas where the model is switched on are picked on the test years they are also scored on, which is
    kind to them. Here they are picked on the first test years only and scored on the later ones, which they have
    not seen: model error against calendar-median error over the picked areas, per horizon."""
    first, last = TEST_YEARS[: len(TEST_YEARS) // 2], TEST_YEARS[len(TEST_YEARS) // 2 :]
    c1, c2 = (np.concatenate([year_cols(y) for y in ys]) for ys in (first, last))
    sel1 = (score(setup.real, chk.per, chk.rng, clim.med, c1), baseline_score(setup.real, clim, c1))
    use = use_model(sel1[0], sel1[1], np.intersect1d(scored, scored_areas(setup, c1)))
    m2, b2 = score(setup.real, chk.per, chk.rng, clim.med, c2), baseline_score(setup.real, clim, c2)
    out = {"picked_on": [first[0], first[-1]], "scored_on": [last[0], last[-1]], "areas": [int(u.sum()) for u in use]}
    for i, h in enumerate(HORIZONS):
        idx = np.nonzero(use[i])[0]
        out[f"h{h}"] = {
            "model_err_pct": round(100 * float(m2.err[i, idx].sum() / max(1.0, m2.real[idx].sum())), 1),
            "calendar_err_pct": round(100 * float(b2.err[i, idx].sum() / max(1.0, b2.real[idx].sum())), 1),
            "coverage": round(float(m2.hit[i, idx].sum() / max(1, m2.n[idx].sum())), 3),
        }
    return out


def produce(setup: Setup, model: str, ev: dict, extra=None) -> dict:
    """Fit on every month there is and forecast the six months after the last one, for every area with a range.
    Returns months, p10/p50/p90 [horizons, areas] and the number of rows the model was fitted on."""
    real, years = setup.real, setup.data.base_years
    m = real.shape[1]
    st = make_state(setup, years, np.ones(m, bool), extra)
    predict = MODELS[model](st, setup, np.random.default_rng(0), extra)
    scaled = scaled_residuals(setup, ev["fwd"][model].per, "forward", CALIB_YEARS)
    cls, scale = size_class(real, years), noise(real, years)
    q = residual_quantiles({h: scaled[h][:, np.concatenate([year_cols(y) for y in CALIB_YEARS])] for h in HORIZONS}, cls)
    cube = np.stack([real[:, year_cols(y)] for y in years], axis=1)
    p10, p50, p90 = (np.zeros((len(HORIZONS), real.shape[0])) for _ in range(3))
    labels = []
    for i, h in enumerate(HORIZONS):
        abs_month = ARCHIVE_START + m - 1 + h
        labels.append(f"{abs_month // 12 + 2000}-{abs_month % 12 + 1:02d}")
        cal = np.array([abs_month % 12])
        base = np.median(cube[:, :, cal[0]], axis=1)[:, None]
        P = boxes_from_anomaly(st, predict(h, np.array([m - 1])), cal)
        f = area_forecast(st, P, cal, base)
        lo, hi = apply_range(f, q, cls, scale, i)
        p10[i], p50[i], p90[i] = lo[:, 0], f[:, 0], hi[:, 0]
    return {"months": labels, "p10": p10, "p50": p50, "p90": p90, "rows": getattr(predict, "rows", 0)}


def write(version: Path, setup: Setup, ev: dict, out: dict, extra_names: tuple[str, ...] = ()) -> None:
    """forecast.parquet (only the areas and horizons where the model passed the check) and forecast.json."""
    from datetime import UTC, datetime

    from .fit import write_json

    manifest = json.loads((version / "manifest.json").read_text())
    best = ev["choice"]["model"]
    use, base, sc = ev["use"], ev["base_forward"], ev["fwd"][best].sc
    rows = []
    validated, use_map = {}, {}
    for a in ev["scored"]:
        name = setup.names[a]
        err = [round(100 * float(sc.err[i, a] / max(1.0, sc.real[a])), 1) for i in range(len(HORIZONS))]
        berr = [round(100 * float(base.err[i, a] / max(1.0, base.real[a])), 1) for i in range(len(HORIZONS))]
        cov = [round(float(sc.hit[i, a] / sc.n[a]), 3) for i in range(len(HORIZONS))]
        k = int(use[:, a].sum())  # a prefix: horizons 1..k
        validated[name] = {"model_err_pct": err, "base_err_pct": berr, "coverage": cov, "use_model": [bool(u) for u in use[:, a]],
                           "model_horizons": k}
        if k:
            use_map[name] = [bool(u) for u in use[:, a]]
            for i, h in enumerate(HORIZONS):
                if use[i, a]:
                    rows.append({"region_id": name, "month": out["months"][i], "horizon": h, "p10": float(max(0.0, out["p10"][i, a])),
                                 "p50": float(out["p50"][i, a]), "p90": float(out["p90"][i, a]), "method": "model", "err_pct": err[i]})
    schema = {"region_id": pl.String, "month": pl.String, "horizon": pl.Int8, "p10": pl.Float32, "p50": pl.Float32,
              "p90": pl.Float32, "method": pl.String, "err_pct": pl.Float32}
    pl.DataFrame(rows, schema=schema).sort("region_id", "horizon").write_parquet(version / "forecast.parquet")
    doc = {
        "version": manifest["version"],
        "trained_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trained_through": month_label(setup.data.last_seen),
        "train_rows": out["rows"],
        "method_default": "climatology",
        "model": {"name": best, "box_deg": BOX_DEG, "horizons": list(HORIZONS), "features": list(BASE_FEATURES) + list(extra_names),
                  "weather": bool(extra_names), "months": out["months"]},
        "rule": {"min_gain": MIN_GAIN, "coverage_band": list(COVERAGE_BAND), "min_test_total": MIN_TEST_TOTAL,
                 "test_years": [TEST_YEARS[0], TEST_YEARS[-1]], "calibration_years": [CALIB_YEARS[0], CALIB_YEARS[-1]],
                 "range": "10th-90th percentile"},
        "choice": ev["choice"],
        "tables": ev["tables"],
        "seasons": ev["seasons"],
        "validated": validated,
        "use_model": use_map,
        "model_horizons": {name: int(sum(flags)) for name, flags in use_map.items()},
        "counts": horizon_counts(ev["use"], setup.names),
    }
    write_json(version / "forecast.json", doc)


def horizon_counts(use: np.ndarray, names: list[str]) -> dict:
    """How many areas the model is used for: at all (K >= 1), for three months or more, for all six."""
    k = use.sum(axis=0)
    out = {"scored_with_model": int((k >= 1).sum()), "k_at_least_3": int((k >= 3).sum()), "k_6": int((k == 6).sum())}
    out.update({n: int(k[names.index(n)]) for n in ("world", "AR") if n in names})
    return out


def month_label(month: int) -> str:
    return f"{month // 12 + 2000}-{month % 12 + 1:02d}"


def is_current(version: Path) -> bool:
    """The version already holds a forecast of its own (the data of a version never change)."""
    path = version / "forecast.json"
    try:
        return json.loads(path.read_text())["version"] == json.loads((version / "manifest.json").read_text())["version"] and (version / "forecast.parquet").exists()
    except (OSError, ValueError, KeyError):
        return False


def run(version: Path, models: tuple[str, ...] = tuple(MODELS), log=print, force: bool = False) -> dict | None:
    if not force and is_current(version):
        log(f"forecast: {version.name} already has its forecast (--force to build it again)")
        return None
    t0 = time.time()
    setup = build(version)
    log(f"forecast: {len(setup.names)} areas, {setup.boxes.n} boxes in {time.time() - t0:.0f} s")
    ev = evaluate(setup, event_list(version), models, log)
    out = produce(setup, ev["choice"]["model"], ev)
    write(version, setup, ev, out)
    log(f"forecast: {horizon_counts(ev['use'], setup.names)}; done in {time.time() - t0:.0f} s")
    return ev


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline forecast")
    ap.add_argument("--data", required=True, help="data root (contains versions/, current)")
    ap.add_argument("--models", default=",".join(MODELS), help="models to check, comma separated")
    ap.add_argument("--force", action="store_true", help="build again although the version has a forecast")
    args = ap.parse_args(argv)
    version = (config.paths(args.data).current).resolve()
    run(version, tuple(args.models.split(",")), force=args.force)
    return 0
