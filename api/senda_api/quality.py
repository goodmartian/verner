"""Expected error of an area, from the validation curve of the harmonization."""

from __future__ import annotations

import numpy as np

from .months import BASE_FIRST_MONTH, round_int
from .store import MODIS_SENSORS, Store
from .weights import weighted_sum

ERROR_FIRST_MONTH = (2012 - 2000) * 12 + 1  # 2012-02
ERROR_LAST_MONTH = (2021 - 2000) * 12 + 11  # 2021-12
SCENARIOS = ("loyo", "forward")


def mean_monthly_count(store: Store, idx: np.ndarray, w: np.ndarray) -> float:
    """Mean raw viirs_snpp count per complete month 2012-02 to 2021-12, empty months included."""
    raw = weighted_sum(store.RAW["viirs_snpp"], idx, w)
    months = [
        m for m in range(ERROR_FIRST_MONTH, ERROR_LAST_MONTH + 1) if m not in store.incomplete and m <= store.cur_month
    ]
    return float(raw[months].mean()) if months else 0.0


def interpolate_error(curve: list[dict], mean_count: float) -> float | None:
    """WAPE read off the error curve, interpolated linearly in log(mean monthly count)."""
    pts = sorted((p["mean_monthly_count"], p["wape"]) for p in curve if p["mean_monthly_count"] > 0)
    if not pts:
        return None
    xs = np.log([p[0] for p in pts])
    ys = [p[1] for p in pts]
    if mean_count <= 0 or np.log(mean_count) <= xs[0]:
        return float(max(ys))
    if np.log(mean_count) >= xs[-1]:
        return float(ys[-1])
    return float(np.interp(np.log(mean_count), xs, ys))


def confidence(error: float, unharmonized_share: float, thresholds: dict) -> str:
    if error <= thresholds["high_wape"] and unharmonized_share <= thresholds["high_unharmonized_share"]:
        return "high"
    if error <= thresholds["medium_wape"] and unharmonized_share <= thresholds["medium_unharmonized_share"]:
        return "medium"
    return "low"


def for_area(store: Store, idx: np.ndarray, w: np.ndarray, area_id: str | None = None) -> dict:
    h = store.harmonization
    validation = h.get("validation", [])
    basis = "+".join(s for s in SCENARIOS if any(v.get("scenario") == s for v in validation))
    converted = weighted_sum(store.CONV, idx, w)[BASE_FIRST_MONTH:].sum()  # over the baseline years only
    fallback = weighted_sum(store.FALLBACK, idx, w)[BASE_FIRST_MONTH:].sum()
    share = float(fallback / converted) if converted > 0 else 0.0
    out = {"expected_error": None, "confidence": None, "unharmonized_share": round(share, 4), "basis": basis}
    if sum(weighted_sum(store.SER[s], idx, w).sum() for s in MODIS_SENSORS) <= 0:
        return out
    error = interpolate_error(h.get("error_curve", []), mean_monthly_count(store, idx, w))
    if error is None:
        return out
    region = store.regions.by_id.get(area_id) if area_id else None
    if region is not None and region.kind == "country":
        own = [
            v["wape"] for v in validation
            if v.get("level") == "country" and v.get("entity") == area_id and v.get("scenario") in SCENARIOS
        ]
        error = max([error, *own])
    error = round(error, 4)
    out["expected_error"] = error
    out["confidence"] = confidence(error, share, h["confidence_thresholds"])
    return out


def band(count: int, error: float) -> tuple[int, int]:
    """Lower and upper bound of a converted month: the count plus and minus the expected error."""
    return max(0, round_int(count * (1 - error))), round_int(count * (1 + error))
