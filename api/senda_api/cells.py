"""Cells of an area in one month, for the map layer."""

from __future__ import annotations

import numpy as np

from .areas import Area
from .daily import MIN_BASE_YEARS
from .errors import ApiError
from .levels import ratio_level
from .months import month_label, parse_month
from .store import Store
from .weights import cell_weights


def month_cells(store: Store, area: Area, month: str) -> dict:
    """Cells with fires in the month or a usual count above zero: weighted count, median of the same month, level."""
    m = parse_month(month, "month")
    if m is None or not store.first_month <= m <= store.cur_month:
        raise ApiError(400, "invalid_period",
                       f"month must lie in the archive, {month_label(store.first_month)} to {month_label(store.cur_month)}")
    idx, w = cell_weights(store, area)
    sub = store.H[idx]
    counts = np.rint(sub[:, m].toarray().ravel() * w).astype(np.int64)
    base_cols = [(y - 2000) * 12 + m % 12 for y in store.base_years]
    medians = None
    if len(base_cols) >= MIN_BASE_YEARS:
        base = np.rint(sub[:, base_cols].toarray() * w[:, None])
        medians = np.rint(np.median(base, axis=1)).astype(np.int64)
    keep = counts > 0
    if medians is not None:
        keep |= medians > 0
    cells = store.cells
    out = []
    for i in np.nonzero(keep)[0]:
        median = None if medians is None else int(medians[i])
        out.append({
            "cell_id": int(cells.cell_id[idx[i]]),
            "lat": round(float(cells.lat[idx[i]]), 4),
            "lon": round(float(cells.lon[idx[i]]), 4),
            "count": int(counts[i]),
            "median": median,
            "level": ratio_level(int(counts[i]), median)[1],
        })
    return {"cells": out}

