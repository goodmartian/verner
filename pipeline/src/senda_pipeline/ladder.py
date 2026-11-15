"""Model ladder L0..L5 for modis_aqua -> viirs_snpp and the fit windows of every pair.

All fits go through `fit_l3` and `fit_l5`, which take a month mask and cache the result on the PairData object
(the cache key is the mask itself). A scenario passes its own mask, so it sees nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import fit

LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
SCALES = ("zone", "country", "block")
ERA_YEARS = (2012, 2019)
FORWARD_YEARS = (2020, 2021)
RECENT_FIT_YEARS = (2022, 2024)
RECENT_TEST_YEAR = 2025
RECENT_FINAL_YEARS = (2023, 2025)
BRIDGE_SPLIT_YEAR = 2022
DAYNIGHT_GAIN = 0.99  # L4 must be below 0.99 of the L3 error


def _years(d: fit.PairData, lo: int, hi: int) -> np.ndarray:
    return d.valid & (d.year >= lo) & (d.year <= hi)


def era_sel(d: fit.PairData) -> np.ndarray:
    return _years(d, *ERA_YEARS)


def recent_final_sel(d: fit.PairData) -> np.ndarray:
    return _years(d, *RECENT_FINAL_YEARS)


# ---------------------------------------------------------------- fits

@dataclass
class ZoneFit:
    lam: float
    scores: list[dict]
    score: float | None  # inner leave-one-year-out mean zone WAPE at the chosen lambda
    k: np.ndarray  # [zone, 12, 2]
    basis: np.ndarray  # [zone, 12] codes into fit.BASIS


@dataclass
class Final:
    split: bool  # day and night fitted apart
    zone: ZoneFit  # the chosen one of z3 and z4
    country: fit.CountryFit
    z3: ZoneFit
    z4: ZoneFit


def fit_l3(d: fit.PairData, sel: np.ndarray, split_dn: bool = False) -> ZoneFit:
    """L3 (split_dn False) or L4 (True) on the months of `sel`, with lambda chosen inside `sel`."""
    key = ("l3", split_dn, sel.tobytes())
    if key not in d.cache:
        lam, scores = fit.select_lambda(d, sel, split_dn)
        k, basis = fit.fit_zone_full(d, sel, lam, split_dn)
        d.cache[key] = ZoneFit(lam, scores, fit.score_of(scores, lam), k, basis)
    return d.cache[key]


def choose_daynight(score3: float | None, score4: float | None) -> bool:
    """L4 replaces L3 only if its error is lower by at least 1 % relative."""
    return score3 is not None and score4 is not None and score4 < DAYNIGHT_GAIN * score3


def fit_l5(d: fit.PairData, sel: np.ndarray) -> Final:
    key = ("l5", sel.tobytes())
    if key not in d.cache:
        z3, z4 = fit_l3(d, sel, False), fit_l3(d, sel, True)
        split = choose_daynight(z3.score, z4.score)
        zf = z4 if split else z3
        d.cache[key] = Final(split, zf, fit.fit_country(d, sel, zf.lam, zf.k, split), z3, z4)
    return d.cache[key]


# ---------------------------------------------------------------- prediction

def predict(level: str, d: fit.PairData, fit_sel: np.ndarray, test_sel: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(prediction, actual) of the reference count per group and test month, `[group, month]`, dn summed."""
    t = test_sel & d.valid
    actual = d.V[:, t].sum(-1)
    if level == "L0":
        return d.M[:, t].sum(-1), actual
    final = None
    if level == "L1":
        k = np.full((len(d.zones), 12, 2), fit.fit_global(d, fit_sel))
    elif level == "L2":
        k = fit.fit_zone_flat(d, fit_sel)
    elif level == "L3":
        k = fit_l3(d, fit_sel, False).k
    elif level == "L4":
        k = fit_l3(d, fit_sel, True).k
    elif level == "L5":
        final = fit_l5(d, fit_sel)
        k = final.zone.k
    else:
        raise ValueError(f"unknown level {level}")
    kg = k[d.g_zone]
    if final is not None:
        use_g = final.country.use[d.g_country] & (d.pair_zone[d.g_pair] != d.zg)
        kg[use_g] = final.country.F[d.g_pair[use_g]]
    return (d.M[:, t] * kg[:, d.calmonth[t] - 1, :]).sum(-1), actual


@dataclass
class Series:
    pred: dict  # scale -> [entity, month]
    act: dict
    base: dict  # scale -> [entity, month] median of the reference in the fit years, same calendar month
    cm: np.ndarray  # [month] calendar month of the concatenated test months


def _base(d: fit.PairData, scale: str, fit_sel: np.ndarray) -> np.ndarray:
    """Median of the reference by calendar month on the fit months, `[entity, 12]` (NaN when absent)."""
    key = ("base", scale, fit_sel.tobytes())
    if key not in d.cache:
        use = fit_sel & d.valid
        v = d.A[scale][1].sum(-1)[:, use]
        cm = d.calmonth[use]
        out = np.full((v.shape[0], 12), np.nan)
        for c in range(1, 13):
            cols = cm == c
            if cols.any():
                out[:, c - 1] = np.median(v[:, cols], axis=1)
        d.cache[key] = out
    return d.cache[key]


def collect(d: fit.PairData, level: str, folds: list[tuple[np.ndarray, np.ndarray]]) -> Series:
    """Predictions of every fold at zone, country and block scale, concatenated along the month axis."""
    parts = {s: ([], [], []) for s in SCALES}
    cms = []
    for fit_sel, test_sel in folds:
        t = test_sel & d.valid
        if not t.any():
            continue
        pg, ag = predict(level, d, fit_sel, test_sel)
        cm = d.calmonth[t]
        cms.append(cm)
        for s in SCALES:
            parts[s][0].append(d.S[s] @ pg)
            parts[s][1].append(d.S[s] @ ag)
            parts[s][2].append(_base(d, s, fit_sel)[:, cm - 1])
    if not cms:
        raise ValueError("no test months in any fold")
    cat = {s: [np.concatenate(p, axis=1) for p in parts[s]] for s in SCALES}
    return Series(
        {s: cat[s][0] for s in SCALES}, {s: cat[s][1] for s in SCALES}, {s: cat[s][2] for s in SCALES}, np.concatenate(cms)
    )


def wape(pred: np.ndarray, act: np.ndarray) -> np.ndarray:
    den = act.sum(1)
    return np.where(den > 0, np.abs(pred - act).sum(1) / np.where(den > 0, den, 1.0), np.nan)


# ---------------------------------------------------------------- windows and folds

def _loyo(sel: np.ndarray, d: fit.PairData) -> list[tuple[np.ndarray, np.ndarray]]:
    return [(sel & (d.year != y), sel & (d.year == y)) for y in np.unique(d.year[sel])]


def aqua_folds(d: fit.PairData) -> dict:
    sel = era_sel(d)
    return {"loyo": _loyo(sel, d), "forward": [(sel, _years(d, *FORWARD_YEARS))]}


def recent_folds(d: fit.PairData) -> list[tuple[np.ndarray, np.ndarray]]:
    return [(_years(d, *RECENT_FIT_YEARS), _years(d, RECENT_TEST_YEAR, RECENT_TEST_YEAR))]


def full_years(d: fit.PairData) -> list[int]:
    """Calendar years in which every month is valid."""
    return [int(y) for y in np.unique(d.year[d.valid]) if (d.valid & (d.year == y)).sum() == 12]


def bridge_sels(d: fit.PairData) -> dict:
    early_full = [y for y in full_years(d) if y <= BRIDGE_SPLIT_YEAR]
    return {
        "all": d.valid & (d.year <= BRIDGE_SPLIT_YEAR),
        "last3": d.valid & np.isin(d.year, early_full[-3:]),
        "test": d.valid & (d.year > BRIDGE_SPLIT_YEAR),
    }


def bridge_choose(d: fit.PairData) -> tuple[str, dict]:
    """Window of the bridge fit: both windows are fitted up to 2022 and tested after it; lower mean zone WAPE wins."""
    sels = bridge_sels(d)
    scores = {}
    for w in ("all", "last3"):
        if not sels[w].any() or not sels["test"].any():
            scores[w] = None
            continue
        z = fit_l3(d, sels[w], False)
        wz = fit.zone_wape(d, z.k, sels["test"])
        ok = fit.zone_supported(d, sels[w]) & np.isfinite(wz)
        scores[w] = float(wz[ok].mean()) if ok.any() else None
    a, b = scores["all"], scores["last3"]
    return ("last3" if a is not None and b is not None and b < a else "all"), scores


def bridge_final_sel(d: fit.PairData, window: str) -> np.ndarray:
    fy = full_years(d)
    if window == "last3" and len(fy) >= 3:
        return d.valid & np.isin(d.year, fy[-3:])
    return d.valid.copy()


def bridge_folds(d: fit.PairData, window: str) -> dict:
    sels = bridge_sels(d)
    return {
        "loyo": _loyo(bridge_final_sel(d, window), d),
        "forward": [(sels[window], sels["test"])],
    }


def entities(d: fit.PairData, sel: np.ndarray) -> dict:
    """Entities with support in the fit months: zones with enough source hotspots, candidate countries."""
    use = sel & d.valid
    cand = (d.cM[:, use].sum((1, 2)) >= fit.COUNTRY_MIN_PAIRS) & (d.cV[:, use].sum((1, 2)) >= fit.COUNTRY_MIN_PAIRS)
    return {"zone": np.flatnonzero(fit.zone_supported(d, use)), "country": np.flatnonzero(cand)}


# ---------------------------------------------------------------- the ladder table

def _median(x: np.ndarray) -> float | None:
    x = x[np.isfinite(x)]
    return float(np.median(x)) if len(x) else None


RULES = (
    "Pairs are fitted on UTC dates where both sensors passed the day check, months with at least 20 such dates.",
    "Lambda is the largest of 0, 0.01, 0.03, 0.1, 0.3, 1, 3 whose inner leave-one-year-out mean zone WAPE is within 1 percent of the best; chosen {lam}.",
    "Day and night are fitted apart only if that lowers the inner leave-one-year-out mean zone WAPE by at least 1 percent; chosen {dn}.",
    "A zone with fewer than 25 source hotspots in the fit period takes the global factor; a zone month with fewer takes the zone factor.",
    "A factor is never below 0.01.",
    "A country gets its own factors only if it has at least 50000 source and 50000 reference hotspots in the fit period, its inner leave-one-year-out WAPE is at most 0.9 of the zone WAPE, its inner forward WAPE is not worse than the zone WAPE and its bias is within the zone bias or 0.05, and no metric is missing.",
    "Lambda, day and night and the country decisions are chosen again inside every scenario, using only the fit years of that scenario.",
    "Forward checks are reported and never used to choose anything for the modis_aqua pair.",
)


def run(d: fit.PairData) -> dict:
    """Ladder table, selection and country decisions of modis_aqua -> viirs_snpp, fitted on 2012 to 2019."""
    sel = era_sel(d)
    folds = aqua_folds(d)
    ent = entities(d, sel)
    table = []
    for level in LEVELS:
        row = {"level": level}
        for scenario in ("loyo", "forward"):
            s = collect(d, level, folds[scenario])
            for scale in ("zone", "country"):
                e = ent[scale]
                row[f"{scenario}_{scale}_wape"] = _median(wape(s.pred[scale][e], s.act[scale][e]))
        row["chosen"] = level == "L5"
        table.append(row)
    final = fit_l5(d, sel)
    cf = final.country
    selection = {
        "lambda": final.zone.lam,
        "lambda_scores": final.zone.scores,
        "daynight": final.split,
        "daynight_scores": {"L3": final.z3.score, "L4": final.z4.score},
        "bridge_window": None,
        "countries_used": int(cf.use.sum()),
        "lambda_country": cf.lam_c,
        "rules": [r.format(lam=final.zone.lam, dn="yes" if final.split else "no") for r in RULES],
    }
    decisions = [
        {"country": d.countries[c], "use": bool(cf.use[c]), "gain": float(cf.gain[c])} for c in np.flatnonzero(cf.cand)
    ]
    return {"ladder": table, "selection": selection, "country_decisions": decisions, "final": final, "entities": ent}
