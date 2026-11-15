"""The check of the seam between the sensors (`seam.json` of a data version, the pipeline's own): how far our series
departs from the reference at the 2012 change from MODIS to VIIRS, against the departures of the years without a change,
and the same for the 2026 change from S-NPP to NOAA-20. Nothing is softened: `fail` is given as `fail`. A version without
the file has no seam block."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .areas import WORLD_ID

if TYPE_CHECKING:
    from .store import Store

SEAM_2012 = "2012-02"
SEAM_2026 = "2026-11"


def load(root: Path) -> dict | None:
    path = root / "seam.json"
    return json.loads(path.read_text()) if path.exists() else None


def _finite(value: float | None) -> float | None:
    """A number of the file; a missing or not finite one (too few placebo dates) stays null."""
    return None if value is None or not math.isfinite(value) else value


def _round(value: float | None) -> float | None:
    return None if _finite(value) is None else round(value, 2)


def _pct(value: float | None) -> float | None:
    return None if value is None else _round(100 * value)


def _slice(found: dict) -> dict:
    return {"name": found["name"], "kind": found["kind"], "gap_pct": _pct(found["seam"]["gap"]),
            "threshold_pct": _pct(found.get("placebo_gap_p90_abs")), "as_is_jump": _finite(found["seam"]["as_is"]),
            "status": found["status"], "seam": SEAM_2012}


def meta(seam: dict | None) -> dict | None:
    """What `/api/meta` says: the world's headline and the 2026 seam, with how many slices pass."""
    if seam is None:
        return None
    head, new = seam["headline"], seam["seam_2026"]
    states = Counter(s["status"] for s in seam["slices"])
    return {
        "headline": {
            "seam": SEAM_2012, "as_is_jump": _finite(head["naive_jump"]), "gap_pct": _round(head["ours_gap_pct"]),
            "threshold_pct": _round(head["placebo_gap_p90_abs_pct"]),
            "typical_change_pct": _round(head["placebo_typical_change_pct"]), "status": head["status"],
            "slices": len(seam["slices"]), "passed": states["pass"], "failed": list(seam["failed"]),
            "insufficient": list(seam["insufficient"]), "text": head["text"],
        },
        "seam_2026": {
            "seam": SEAM_2026, "from_sensor": "viirs_snpp", "to_sensor": "viirs_noaa20",
            "gap_pct": _pct(new["seam"]["gap"]), "threshold_pct": _pct(new["placebo_gap_p90_abs"]), "status": new["status"],
            "days_before": new["before_days"], "days_after": new["after_days"],
        },
    }


def _heaviest(names: np.ndarray, w: np.ndarray) -> str | None:
    if not len(names):
        return None
    totals: dict[str, float] = {}
    for name, weight in zip(names.tolist(), w.tolist(), strict=True):
        totals[name] = totals.get(name, 0.0) + weight
    return max(totals, key=totals.__getitem__)


def slice_for(store: Store, area_id: str | None, idx: np.ndarray, w: np.ndarray) -> dict | None:
    """The 2012 seam of the slice that holds an area: the world for the world, else the country with most of its weight,
    else its zone; None when there is no such slice."""
    if store.seam is None:
        return None
    by_key = {(s["kind"], s["name"]): s for s in store.seam["slices"]}
    if area_id == WORLD_ID:
        keys = [("world", "world")]
    else:
        keys = [("country", _heaviest(store.cells.country[idx], w)), ("zone", _heaviest(store.cells.zone[idx], w))]
    found = next((by_key[k] for k in keys if k in by_key), None)
    return None if found is None else _slice(found)
