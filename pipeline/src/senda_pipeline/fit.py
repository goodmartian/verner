"""Pair data and the shrinkage fits of the harmonization.

Every fit is a pure function of a boolean mask of months `sel`: a scenario cannot use a month it was not given.
Arrays are `[group, month, dn]` with dn 0 = day, 1 = night. A group is one (country, zone, 1 degree block).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse

from . import chain

LAMBDAS = (0.0, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0)
LAMBDA_TOL = 1.01  # largest lambda whose error is within 1 % of the best
MIN_M_SUM = 25  # a zone, or a zone month, needs at least this many source hotspots in the fit period
MIN_PAIR_DAYS = 20
COUNTRY_MIN_PAIRS = 50_000  # candidate country: sum M and sum V at least this
COUNTRY_GAIN = 0.9  # country WAPE must be at most 0.9 of the zone WAPE
BIAS_FLOOR = 0.05
K_MIN = 0.01  # a factor is never below this: zero would delete every converted hotspot
BASIS = ("zone_month", "zone", "global")
BLOCK_KEY = 70_000


# ---------------------------------------------------------------- data

def _indicator(idx: np.ndarray, n: int) -> sparse.csr_matrix:
    return sparse.csr_matrix((np.ones(len(idx)), (idx, np.arange(len(idx)))), shape=(n, len(idx)))


def agg(s: sparse.csr_matrix, x: np.ndarray) -> np.ndarray:
    """Sum rows of x (first axis) into the rows of the indicator matrix s."""
    shape = x.shape
    return (s @ x.reshape(shape[0], -1)).reshape((s.shape[0], *shape[1:]))


@dataclass
class PairData:
    """Counts of a sensor pair: M from the source sensor, V from the reference, on the paired days only."""

    src: str
    dst: str
    M: np.ndarray  # [G, T, 2]
    V: np.ndarray  # [G, T, 2]
    month: np.ndarray  # [T] months since 2000-01
    valid: np.ndarray  # [T] month has at least MIN_PAIR_DAYS paired dates
    g_zone: np.ndarray  # [G] index into zones; the last zone is "global" (zone none)
    g_country: np.ndarray  # [G] index into countries
    g_block: np.ndarray  # [G] block index 0..B-1
    zones: list[str]
    countries: list[str]
    cell_to_g: np.ndarray | None = None  # [max cell_id + 1], -1 outside the groups
    count_raw: dict | None = None  # mean monthly raw reference counts per scale (set by attach_counts)
    dropped: int = 0  # pair rows whose cell is not in cells.parquet
    cache: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.year = 2000 + self.month // 12
        self.calmonth = self.month % 12 + 1
        self.zg = len(self.zones) - 1
        nz = len(self.zones)
        key = self.g_country.astype(np.int64) * nz + self.g_zone
        pk, self.g_pair = np.unique(key, return_inverse=True)
        self.pair_country = pk // nz
        self.pair_zone = pk % nz
        self.n_blocks = int(self.g_block.max()) + 1 if len(self.g_block) else 0
        self.S = {
            "zone": _indicator(self.g_zone, nz),
            "pair": _indicator(self.g_pair, len(pk)),
            "country": _indicator(self.g_country, len(self.countries)),
            "block": _indicator(self.g_block, self.n_blocks),
        }
        self.S_pair_country = _indicator(self.pair_country, len(self.countries))
        self.A = {name: (agg(s, self.M), agg(s, self.V)) for name, s in self.S.items()}

    zM = property(lambda self: self.A["zone"][0])
    zV = property(lambda self: self.A["zone"][1])
    pM = property(lambda self: self.A["pair"][0])
    pV = property(lambda self: self.A["pair"][1])
    cM = property(lambda self: self.A["country"][0])
    cV = property(lambda self: self.A["country"][1])

    def mean_count(self, scale: str) -> np.ndarray:
        """Mean monthly raw reference count of each entity; falls back to the pair-day counts."""
        if self.count_raw and scale in self.count_raw:
            return self.count_raw[scale]
        v = self.A[scale][1].sum(-1)
        return v[:, self.valid].mean(1) if self.valid.any() else np.zeros(len(v))


def _codes(values: np.ndarray) -> tuple[list[str], np.ndarray]:
    uniq, inv = np.unique(values, return_inverse=True)
    return [str(u) for u in uniq], inv


def _read_n_days(pairs_path: Path, days_path: Path | None, src: str, dst: str) -> pl.DataFrame:
    side = pairs_path.with_name(pairs_path.stem + "__days.parquet")
    if side.exists():
        return pl.read_parquet(side).select(pl.col("month").cast(pl.Int64), pl.col("n_days").cast(pl.Int64))
    if days_path is None or not days_path.exists():
        raise FileNotFoundError(f"no paired day counts: {side} and {days_path} are missing")
    days = pl.read_parquet(days_path).filter(pl.col("sensor").is_in([src, dst]) & pl.col("ok"))
    both = days.group_by("utc_date").agg(pl.len().alias("n")).filter(pl.col("n") == 2)
    return (
        both.group_by(((pl.col("utc_date").dt.year() - 2000) * 12 + pl.col("utc_date").dt.month() - 1).alias("month"))
        .agg(pl.len().cast(pl.Int64).alias("n_days"))
        .sort("month")
    )


def load_pair(pairs_path: Path, days_path: Path | None, cells: pl.DataFrame) -> PairData:
    """Read `pairs/<src>__<dst>.parquet` into group arrays. Cells absent from `cells` are dropped."""
    src, dst = pairs_path.stem.split("__")
    cells = cells.sort("cell_id")
    zone = cells["zone"].fill_null("none").to_numpy()
    country = cells["country"].fill_null("ZZ").to_numpy()
    zone_names, z_inv = _codes(zone)
    zones = [z for z in zone_names if z != "none"] + ["global"]
    zmap = np.array([zones.index(z) if z != "none" else len(zones) - 1 for z in zone_names])
    cell_zone = zmap[z_inv]
    countries, cell_country = _codes(country)
    lat = np.floor(cells["lat"].to_numpy().astype(np.float64)).astype(np.int64) + 90
    lon = np.clip(np.floor(cells["lon"].to_numpy().astype(np.float64)).astype(np.int64) + 180, 0, 359)
    cell_block_key = lat * 360 + lon
    nz = len(zones)
    key = (cell_country.astype(np.int64) * nz + cell_zone) * BLOCK_KEY + cell_block_key
    ukey, cell_g_local = np.unique(key, return_inverse=True)
    g_block_key = ukey % BLOCK_KEY
    g_zone = (ukey // BLOCK_KEY) % nz
    g_country = ukey // BLOCK_KEY // nz
    _, g_block = np.unique(g_block_key, return_inverse=True)
    cell_ids = cells["cell_id"].to_numpy().astype(np.int64)
    cell_to_g = np.full(int(cell_ids.max()) + 1, -1, dtype=np.int32)
    cell_to_g[cell_ids] = cell_g_local

    pairs = pl.read_parquet(pairs_path)
    nd = _read_n_days(pairs_path, days_path, src, dst)
    lows = [int(x) for x in (pairs["month"].min(), nd["month"].min()) if x is not None]
    highs = [int(x) for x in (pairs["month"].max(), nd["month"].max()) if x is not None]
    if not lows:
        raise ValueError(f"{pairs_path} has no months")
    m0, m1 = min(lows), max(highs)
    month = np.arange(m0, m1 + 1)
    valid = np.zeros(len(month), dtype=bool)
    valid[nd["month"].to_numpy() - m0] = nd["n_days"].to_numpy() >= MIN_PAIR_DAYS

    ng, nt = len(ukey), len(month)
    cid = pairs["cell_id"].to_numpy().astype(np.int64)
    in_map = cid < len(cell_to_g)
    g = np.where(in_map, cell_to_g[np.minimum(cid, len(cell_to_g) - 1)], -1)
    keep = g >= 0
    flat = (g[keep] * nt + (pairs["month"].to_numpy().astype(np.int64)[keep] - m0)) * 2 + (
        (pairs["dn"] == "N").to_numpy()[keep]
    )
    M = np.bincount(flat, weights=pairs["n_src"].to_numpy()[keep].astype(np.float64), minlength=ng * nt * 2)
    V = np.bincount(flat, weights=pairs["n_dst"].to_numpy()[keep].astype(np.float64), minlength=ng * nt * 2)
    return PairData(
        src=src,
        dst=dst,
        M=M.reshape(ng, nt, 2),
        V=V.reshape(ng, nt, 2),
        month=month,
        valid=valid,
        g_zone=g_zone,
        g_country=g_country,
        g_block=g_block,
        zones=zones,
        countries=countries,
        cell_to_g=cell_to_g,
        dropped=int((~keep).sum()),
    )


def attach_counts(d: PairData, monthly_path: Path, days_path: Path) -> None:
    """Mean monthly raw counts of the reference sensor over the complete months 2012-02 to 2021-12."""
    days = pl.read_parquet(days_path)
    first, last = date(2012, 2, 1), date(2021, 12, 31)
    incomplete = set(chain.incomplete_months(days, first, last))
    months = [
        (y - 2000) * 12 + m - 1
        for y in range(2012, 2022)
        for m in range(1, 13)
        if (y, m) >= (2012, 2) and f"{y:04d}-{m:02d}" not in incomplete
    ]
    tot = (
        pl.scan_parquet(monthly_path)
        .filter((pl.col("sensor") == d.dst) & pl.col("month").cast(pl.Int64).is_in(months))
        .group_by("cell_id")
        .agg((pl.col("n_day").cast(pl.Int64) + pl.col("n_night").cast(pl.Int64)).sum().alias("n"))
        .collect()
    )
    cid = tot["cell_id"].to_numpy().astype(np.int64)
    ok = cid < len(d.cell_to_g)
    g = d.cell_to_g[cid[ok]]
    ok2 = g >= 0
    per_group = np.bincount(g[ok2], weights=tot["n"].to_numpy()[ok][ok2].astype(np.float64), minlength=len(d.g_zone))
    d.count_raw = {name: (s @ per_group) / max(len(months), 1) for name, s in d.S.items()}


# ---------------------------------------------------------------- zone fit (L3)

def _onehot(cm: np.ndarray) -> np.ndarray:
    return (cm[:, None] - 1 == np.arange(12)[None, :]).astype(np.float64)


def fit_zone_arrays(zM, zV, cm, use, lam, split_dn, zg):
    """k[zone, calmonth, dn] and basis codes [zone, calmonth] from zone totals on the months `use`.

    k = (V + a R_z) / (M + a), a = lam * mean over calendar months of M. A zone month with fewer than
    MIN_M_SUM source hotspots takes R_z; a zone with fewer takes the global ratio; the global slot always does.
    """
    w = _onehot(cm[use])
    mc = np.einsum("ztd,tc->zcd", zM[:, use], w)
    vc = np.einsum("ztd,tc->zcd", zV[:, use], w)
    if not split_dn:
        mc, vc = mc.sum(-1, keepdims=True), vc.sum(-1, keepdims=True)
    mg, vg = mc.sum((0, 1)), vc.sum((0, 1))
    rg = np.where(mg > 0, vg / np.where(mg > 0, mg, 1.0), 1.0)
    mz, vz = mc.sum(1), vc.sum(1)
    rz = np.where(mz > 0, vz / np.where(mz > 0, mz, 1.0), rg[None, :])
    a = lam * mc.mean(1, keepdims=True)
    den = mc + a
    k = np.where(den > 0, (vc + a * rz[:, None, :]) / np.where(den > 0, den, 1.0), rz[:, None, :])
    month_ok = mc.sum(-1) >= MIN_M_SUM
    zone_ok = mc.sum((1, 2)) >= MIN_M_SUM
    zone_ok[zg] = False
    k = np.where(month_ok[:, :, None], k, rz[:, None, :])
    k = np.where(zone_ok[:, None, None], k, rg[None, None, :])
    basis = np.where(zone_ok[:, None], np.where(month_ok, 0, 1), 2).astype(np.int8)
    k = np.maximum(k, K_MIN)
    if not split_dn:
        k = np.repeat(k, 2, axis=-1)
    return k, basis


def fit_zone_full(d: PairData, sel: np.ndarray, lam: float, split_dn: bool):
    return fit_zone_arrays(d.zM, d.zV, d.calmonth, sel & d.valid, lam, split_dn, d.zg)


def fit_zone(d: PairData, sel: np.ndarray, lam: float, split_dn: bool) -> np.ndarray:
    """L3: k[zone, calmonth, dn] fitted only on the months of `sel`."""
    return fit_zone_full(d, sel, lam, split_dn)[0]


def fit_global(d: PairData, sel: np.ndarray) -> float:
    """L1: one k, sum V over sum M."""
    use = sel & d.valid
    m, v = d.M[:, use].sum(), d.V[:, use].sum()
    return float(max(v / m, K_MIN)) if m > 0 else 1.0


def fit_zone_flat(d: PairData, sel: np.ndarray) -> np.ndarray:
    """L2: one k per zone (same for every month and for day and night); unsupported zones take the global k."""
    use = sel & d.valid
    m, v = d.zM[:, use].sum((1, 2)), d.zV[:, use].sum((1, 2))
    rg = fit_global(d, sel)
    ok = m >= MIN_M_SUM
    ok[d.zg] = False
    r = np.where(ok, np.maximum(v / np.where(m > 0, m, 1.0), K_MIN), rg)
    return np.broadcast_to(r[:, None, None], (len(r), 12, 2)).copy()


def zone_supported(d: PairData, use: np.ndarray) -> np.ndarray:
    ok = d.zM[:, use].sum((1, 2)) >= MIN_M_SUM
    ok[d.zg] = False
    return ok


def zone_wape(d: PairData, k: np.ndarray, test: np.ndarray) -> np.ndarray:
    """WAPE of zone totals on the months `test` for a zone factor array k[zone, calmonth, dn]."""
    t = test & d.valid
    p = (d.zM[:, t] * k[:, d.calmonth[t] - 1, :]).sum(-1)
    v = d.zV[:, t].sum(-1)
    num, den = np.abs(p - v).sum(1), v.sum(1)
    return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


def inner_loyo_zone(d: PairData, sel: np.ndarray, lam: float, split_dn: bool) -> np.ndarray:
    """WAPE per zone over the years of `sel` left out one at a time (the fit sees only the other years of `sel`)."""
    use = sel & d.valid
    err = np.zeros(len(d.zones))
    act = np.zeros(len(d.zones))
    for y in np.unique(d.year[use]):
        fit, test = use & (d.year != y), use & (d.year == y)
        k, _ = fit_zone_arrays(d.zM, d.zV, d.calmonth, fit, lam, split_dn, d.zg)
        p = (d.zM[:, test] * k[:, d.calmonth[test] - 1, :]).sum(-1)
        v = d.zV[:, test].sum(-1)
        err += np.abs(p - v).sum(1)
        act += v.sum(1)
    ok = zone_supported(d, use) & (act > 0)
    return np.where(ok, err / np.where(act > 0, act, 1.0), np.nan)


def pick_lambda(scores: dict[float, float | None]) -> float:
    """Largest lambda whose error is within 1 % of the best."""
    finite = {lam: s for lam, s in scores.items() if s is not None and np.isfinite(s)}
    if not finite:
        return 0.0
    best = min(finite.values())
    return max(lam for lam, s in finite.items() if s <= best * LAMBDA_TOL)


def select_lambda(d: PairData, sel: np.ndarray, split_dn: bool) -> tuple[float, list[dict]]:
    """Lambda by inner leave-one-year-out inside `sel`. Returns the choice and every candidate score."""
    scores = []
    for lam in LAMBDAS:
        w = inner_loyo_zone(d, sel, lam, split_dn)
        scores.append(float(np.nanmean(w)) if np.isfinite(w).any() else None)
    chosen = pick_lambda(dict(zip(LAMBDAS, scores, strict=True)))
    return chosen, [{"lambda": lam, "score": s} for lam, s in zip(LAMBDAS, scores, strict=True)]


def score_of(scores: list[dict], lam: float) -> float | None:
    return next(s["score"] for s in scores if s["lambda"] == lam)


# ---------------------------------------------------------------- country rule

@dataclass
class CountryFit:
    use: np.ndarray  # [C] country gets its own factors
    cand: np.ndarray  # [C] country passed the size threshold in the fit months
    gain: np.ndarray  # [C] 1 - WAPE_country / WAPE_zone, inner leave-one-year-out
    F: np.ndarray  # [P, 12, 2] factors of every (country, zone) pair
    lam_c: float
    lam_scores: list[dict]


def country_rule(w_loyo_z, w_loyo_c, w_fwd_z, w_fwd_c, b_fwd_z, b_fwd_c) -> np.ndarray:
    """The three conditions of the country rule, elementwise."""
    arrays = [np.asarray(a, dtype=float) for a in (w_loyo_z, w_loyo_c, w_fwd_z, w_fwd_c, b_fwd_z, b_fwd_c)]
    finite = np.all([np.isfinite(a) for a in arrays], axis=0)
    c1 = (arrays[0] > 0) & (arrays[1] <= COUNTRY_GAIN * arrays[0])
    c2 = (arrays[3] <= arrays[2]) & (np.abs(arrays[5]) <= np.maximum(np.abs(arrays[4]), BIAS_FLOOR))
    return finite & c1 & c2


def _pair_factors(d: PairData, use, kz, lam_c, split_dn) -> np.ndarray:
    w = _onehot(d.calmonth[use])
    mc = np.einsum("ptd,tc->pcd", d.pM[:, use], w)
    vc = np.einsum("ptd,tc->pcd", d.pV[:, use], w)
    kp = kz[d.pair_zone]
    if not split_dn:
        mc, vc, kp = mc.sum(-1, keepdims=True), vc.sum(-1, keepdims=True), kp[..., :1]
    beta = lam_c * mc.mean(1, keepdims=True)
    den = mc + beta
    f = np.where(den > 0, (vc + beta * kp) / np.where(den > 0, den, 1.0), kp)
    f = np.where((d.pair_zone == d.zg)[:, None, None], kp, f)
    f = np.maximum(f, K_MIN)
    return np.repeat(f, 2, axis=-1) if not split_dn else f


def _country_preds(d: PairData, k_pair: np.ndarray, test: np.ndarray) -> np.ndarray:
    """Country totals [C, t] of M converted with pair factors k_pair[pair, calmonth, dn] on the months `test`."""
    p = (d.pM[:, test] * k_pair[:, d.calmonth[test] - 1, :]).sum(-1)
    return d.S_pair_country @ p


def fit_country(d: PairData, sel: np.ndarray, lam: float, kz: np.ndarray, split_dn: bool = False) -> CountryFit:
    """Country factors and the decision, using only the months of `sel`.

    `lam` and `split_dn` describe the zone model `kz`; it is refitted without the held-out years inside.
    """
    use = sel & d.valid
    nc = len(d.countries)
    cand = (d.cM[:, use].sum((1, 2)) >= COUNTRY_MIN_PAIRS) & (d.cV[:, use].sum((1, 2)) >= COUNTRY_MIN_PAIRS)
    years = np.unique(d.year[use])
    none = CountryFit(np.zeros(nc, bool), cand, np.zeros(nc), kz[d.pair_zone].copy(), 0.0, [])
    if not cand.any() or len(years) < 3:
        return none
    # inner leave-one-year-out at country scale: zone model and each lambda_c
    abs_z, act = np.zeros(nc), np.zeros(nc)
    abs_c = {lc: np.zeros(nc) for lc in LAMBDAS}
    for y in years:
        fit, test = use & (d.year != y), use & (d.year == y)
        kz_y, _ = fit_zone_arrays(d.zM, d.zV, d.calmonth, fit, lam, split_dn, d.zg)
        vt = d.cV[:, test].sum(-1)
        pz = _country_preds(d, kz_y[d.pair_zone], test)
        abs_z += np.abs(pz - vt).sum(1)
        act += vt.sum(1)
        for lc in LAMBDAS:
            pc = _country_preds(d, _pair_factors(d, fit, kz_y, lc, split_dn), test)
            abs_c[lc] += np.abs(pc - vt).sum(1)
    ok = cand & (act > 0)

    def wape(a):
        return np.where(act > 0, a / np.where(act > 0, act, 1.0), np.nan)

    lam_scores = [
        {"lambda": lc, "score": float(np.nanmean(wape(abs_c[lc])[ok])) if ok.any() else None} for lc in LAMBDAS
    ]
    lam_c = pick_lambda({s["lambda"]: s["score"] for s in lam_scores})
    w_loyo_z, w_loyo_c = wape(abs_z), wape(abs_c[lam_c])
    # inner forward: first two thirds of the fit years against the last third
    nf = round(len(years) * 2 / 3)
    fit_f, test_f = use & np.isin(d.year, years[:nf]), use & np.isin(d.year, years[nf:])
    kz_f, _ = fit_zone_arrays(d.zM, d.zV, d.calmonth, fit_f, lam, split_dn, d.zg)
    vf = d.cV[:, test_f].sum(-1)
    pz_f = _country_preds(d, kz_f[d.pair_zone], test_f)
    pc_f = _country_preds(d, _pair_factors(d, fit_f, kz_f, lam_c, split_dn), test_f)
    af = vf.sum(1)

    def wb(p):
        return (
            np.where(af > 0, np.abs(p - vf).sum(1) / np.where(af > 0, af, 1.0), np.nan),
            np.where(af > 0, (p - vf).sum(1) / np.where(af > 0, af, 1.0), np.nan),
        )

    w_f_z, b_f_z = wb(pz_f)
    w_f_c, b_f_c = wb(pc_f)
    use_c = cand & country_rule(w_loyo_z, w_loyo_c, w_f_z, w_f_c, b_f_z, b_f_c)
    gain = np.where(np.isfinite(w_loyo_z) & (w_loyo_z > 0), 1 - w_loyo_c / np.where(w_loyo_z > 0, w_loyo_z, 1.0), 0.0)
    gain = np.where(np.isfinite(gain), gain, 0.0)
    return CountryFit(use_c, cand, gain, _pair_factors(d, use, kz, lam_c, split_dn), lam_c, lam_scores)


# ---------------------------------------------------------------- shared helpers

def write_json(path: Path, obj) -> None:
    """Deterministic JSON without NaN (NaN and inf become null)."""

    def clean(x):
        if isinstance(x, dict):
            return {str(k): clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        if isinstance(x, np.ndarray):
            return clean(x.tolist())
        if isinstance(x, np.generic):
            return clean(x.item())
        if isinstance(x, float) and not np.isfinite(x):
            return None
        return x

    path.write_text(json.dumps(clean(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False))
