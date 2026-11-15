"""Season summary of an area: when it burns, how strongly, and how the year so far compares."""

from __future__ import annotations

import numpy as np

from .levels import UNUSUAL_MIN_COUNT
from .months import round_int

MIN_BASE_YEARS = 3
SEASON_FACTOR = 1.25


def _ratio(count: int, base: int) -> float:
    return 1.0 if count == 0 and base == 0 else round(count / max(base, 1), 2)


def summarize(series: list[dict], normals: list[dict], yearly: list[dict]) -> dict | None:
    """series: every month of the archive; normals: 12 entries; yearly: every year with data. None without 3 base years."""
    base = [y for y in yearly if y["complete"]]
    if len(base) < MIN_BASE_YEARS:
        return None
    median = {n["month"]: n["median"] for n in normals}
    counts = {e["month"]: e["count"] for e in series if e["count"] is not None}
    average_year = float(np.mean([y["count"] for y in base]))
    season_months = [m for m in range(1, 13) if average_year > 0 and median[m] >= SEASON_FACTOR * average_year / 12]
    total = sum(y["count"] for y in base)
    in_season = sum(counts.get(f"{y['year']}-{m:02d}", 0) for y in base for m in season_months)
    peak = min(range(1, 13), key=lambda m: (-median[m], m))
    quiet = min(range(1, 13), key=lambda m: (median[m], m))
    record = min(base, key=lambda y: (-y["count"], y["year"]))
    quietest = min(base, key=lambda y: (y["count"], y["year"]))
    unusual = [
        e["month"] for e in series
        if e["level"] is not None and e["level"] >= 3 and e["count"] is not None and e["count"] >= UNUSUAL_MIN_COUNT
    ]
    return {
        "season_months": season_months,
        "season_share": round(in_season / total, 2) if season_months and total > 0 else None,
        "record_year": {"year": record["year"], "count": record["count"]},
        "quiet_year": {"year": quietest["year"], "count": quietest["count"]},
        "peak_month": {"month": peak, "median": median[peak]},
        "quiet_month": {"month": quiet, "median": median[quiet]},
        "average_year": round_int(average_year),
        "ytd": _ytd(series, yearly, counts),
        "unusual_months": {"count": len(unusual), "last": max(unusual) if unusual else None},
        "season_strength": round(median[peak] / max(median[quiet], 1), 1),
    }


def _ytd(series: list[dict], yearly: list[dict], counts: dict[str, int]) -> dict | None:
    if not yearly or yearly[-1]["complete"]:
        return None
    year = yearly[-1]["year"]
    done = [int(e["month"][5:]) for e in series if e["month"].startswith(f"{year}-") and not e["partial"]
            and e["count"] is not None]
    if not done:
        return None
    through = max(done)
    count = sum(counts.get(f"{year}-{m:02d}", 0) for m in range(1, through + 1))
    last_year = sum(counts.get(f"{year - 1}-{m:02d}", 0) for m in range(1, through + 1))
    return {"through": f"{year}-{through:02d}", "count": count, "last_year": last_year,
            "ratio": _ratio(count, last_year)}
