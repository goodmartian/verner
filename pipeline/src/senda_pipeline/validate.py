"""Validation scenarios, metrics and the expected-error curve."""

from __future__ import annotations

import numpy as np
from scipy.optimize import isotonic_regression
from scipy.stats import rankdata

from . import fit, ladder

CURVE_BINS = 16


def metrics_many(pred: np.ndarray, actual: np.ndarray, calmonth: np.ndarray, base: np.ndarray | None = None) -> dict:
    """wape, bias, spearman, sign for every row of `pred` and `actual` ([entity, month]); NaN where undefined.

    `base[entity, month]` is the sign reference: the median of the reference counts by calendar month in the
    fit years. Without it the median of `actual` itself by calendar month is used.
    """
    pred, actual = np.atleast_2d(pred).astype(float), np.atleast_2d(actual).astype(float)
    cm = np.asarray(calmonth)
    den = actual.sum(1)
    pos = den > 0
    safe = np.where(pos, den, 1.0)
    out = {
        "wape": np.where(pos, np.abs(pred - actual).sum(1) / safe, np.nan),
        "bias": np.where(pos, (pred - actual).sum(1) / safe, np.nan),
    }
    present = np.unique(cm)
    if len(present) >= 3:
        w = (cm[:, None] == present[None, :]).astype(float)
        n = w.sum(0)
        rp = rankdata(pred @ w / n, axis=1)
        ra = rankdata(actual @ w / n, axis=1)
        rp, ra = rp - rp.mean(1, keepdims=True), ra - ra.mean(1, keepdims=True)
        d2 = np.sqrt((rp**2).sum(1) * (ra**2).sum(1))
        out["spearman"] = np.where(d2 > 0, (rp * ra).sum(1) / np.where(d2 > 0, d2, 1.0), np.nan)
    else:
        out["spearman"] = np.full(len(pred), np.nan)
    if base is None:
        base = np.full(actual.shape, np.nan)
        for c in present:
            cols = cm == c
            base[:, cols] = np.median(actual[:, cols], axis=1, keepdims=True)
    ok = np.isfinite(base)
    same = (np.sign(pred - base) == np.sign(actual - base)) & ok
    out["sign"] = np.where(ok.any(1), same.sum(1) / np.maximum(ok.sum(1), 1), np.nan)
    return out


def metrics(pred, actual, calmonth, base=None) -> dict:
    """wape, bias, spearman, sign of one series; None where undefined."""
    m = metrics_many(np.asarray(pred)[None], np.asarray(actual)[None], calmonth, None if base is None else np.asarray(base)[None])
    return {k: (float(v[0]) if np.isfinite(v[0]) else None) for k, v in m.items()}


def error_curve(records: list[dict]) -> list[dict]:
    """Sixteen log-spaced bins of mean monthly count, WAPE weighted by actual, then a decreasing isotonic fit."""
    rec = [
        r
        for r in records
        if r["mean_monthly_count"] and r["mean_monthly_count"] > 0 and r["wape"] is not None and r["actual"] > 0
    ]
    if not rec:
        return []
    x = np.log([r["mean_monthly_count"] for r in rec])
    w = np.array([r["wape"] for r in rec], dtype=float)
    a = np.array([r["actual"] for r in rec], dtype=float)
    lo, hi = x.min(), x.max()
    idx = np.zeros(len(x), dtype=int) if hi == lo else np.clip(((x - lo) / (hi - lo) * CURVE_BINS).astype(int), 0, CURVE_BINS - 1)
    cnt = np.bincount(idx, minlength=CURVE_BINS)
    wsum = np.bincount(idx, weights=a, minlength=CURVE_BINS)
    keep = cnt > 0
    wape_b = np.bincount(idx, weights=a * w, minlength=CURVE_BINS)[keep] / wsum[keep]
    x_b = np.bincount(idx, weights=a * x, minlength=CURVE_BINS)[keep] / wsum[keep]
    iso = isotonic_regression(wape_b, weights=wsum[keep], increasing=False).x
    return [
        {"mean_monthly_count": float(np.exp(xx)), "wape": float(ww), "samples": int(n)}
        for xx, ww, n in zip(x_b, iso, cnt[keep], strict=True)
    ]


def _num(x: float) -> float | None:
    return float(x) if np.isfinite(x) else None


def _rows(d: fit.PairData, scenario: str, level: str, folds, ent: dict, pool: list | None) -> list[dict]:
    if not any((test & d.valid).any() for _, test in folds):
        return []
    s = ladder.collect(d, level, folds)
    names = {"zone": d.zones, "country": d.countries}
    rows = []
    for scale in ladder.SCALES:
        e = ent.get(scale, np.arange(s.pred[scale].shape[0]))
        p, a, b = s.pred[scale][e], s.act[scale][e], s.base[scale][e]
        m = metrics_many(p, a, s.cm, b)
        mmc = d.mean_count(scale)[e]
        tot = a.sum(1)
        if pool is not None:
            pool += [
                {"mean_monthly_count": float(c), "wape": float(w), "actual": float(t)}
                for c, w, t in zip(mmc, m["wape"], tot, strict=True)
                if np.isfinite(w) and t > 0 and c > 0
            ]
        if scale == "block":
            ok = tot > 0
            act_sum = tot[ok].sum()
            rows.append(
                {
                    "scenario": scenario,
                    "level": "block",
                    "entity": "all",
                    "wape": _num(np.abs(p - a)[ok].sum() / act_sum) if act_sum > 0 else None,
                    "bias": _num((p - a)[ok].sum() / act_sum) if act_sum > 0 else None,
                    "spearman": _num(np.nanmedian(m["spearman"][ok])) if np.isfinite(m["spearman"][ok]).any() else None,
                    "sign": _num(np.nanmedian(m["sign"][ok])) if np.isfinite(m["sign"][ok]).any() else None,
                    "n_months": len(s.cm),
                    "actual": float(act_sum),
                    "mean_monthly_count": _num(np.median(mmc[ok])) if ok.any() else None,
                    "n_blocks": int(ok.sum()),
                }
            )
            continue
        for i, idx in enumerate(e):
            rows.append(
                {
                    "scenario": scenario,
                    "level": scale,
                    "entity": names[scale][idx],
                    "wape": _num(m["wape"][i]),
                    "bias": _num(m["bias"][i]),
                    "spearman": _num(m["spearman"][i]),
                    "sign": _num(m["sign"][i]),
                    "n_months": len(s.cm),
                    "actual": float(tot[i]),
                    "mean_monthly_count": _num(mmc[i]),
                }
            )
    return rows


def scenarios(d_aqua: fit.PairData, d_bridge: fit.PairData, d_recent: fit.PairData, pool: list | None = None) -> list[dict]:
    """Rows of `validation`: loyo and forward for modis_aqua (L5), bridge_loyo, bridge_forward, recent_forward (L3).

    Records of loyo and forward at zone, country and block scale are appended to `pool` for the error curve.
    """
    rows: list[dict] = []
    ent = ladder.entities(d_aqua, ladder.era_sel(d_aqua))
    folds = ladder.aqua_folds(d_aqua)
    rows += _rows(d_aqua, "loyo", "L5", folds["loyo"], ent, pool)
    rows += _rows(d_aqua, "forward", "L5", folds["forward"], ent, pool)
    window, _ = ladder.bridge_choose(d_bridge)
    bf = ladder.bridge_folds(d_bridge, window)
    ent_b = ladder.entities(d_bridge, ladder.bridge_final_sel(d_bridge, window))
    rows += _rows(d_bridge, "bridge_loyo", "L3", bf["loyo"], ent_b, None)
    rows += _rows(d_bridge, "bridge_forward", "L3", bf["forward"], ent_b, None)
    rf = ladder.recent_folds(d_recent)
    rows += _rows(d_recent, "recent_forward", "L3", rf, ladder.entities(d_recent, rf[0][0]), None)
    return rows
