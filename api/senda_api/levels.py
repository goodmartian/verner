"""Ratio and colour level of a count against its median."""

from __future__ import annotations

RATIO_FLOOR = 1
UNUSUAL_MIN_COUNT = 10
LEVEL_EDGES = (0.8, 1.25, 2.0, 4.0)


def level_of(ratio: float) -> int:
    """0 below 0.8, 1 from 0.8, 2 from 1.25, 3 from 2, 4 from 4 (lower edge included)."""
    return sum(ratio >= edge for edge in LEVEL_EDGES)


def ratio_level(count: int, median: int | None) -> tuple[float | None, int | None]:
    """Ratio to the median (2 decimals) and level. An empty month in an area that is usually empty counts as normal."""
    if median is None:
        return None, None
    if count == 0 and median == 0:
        return 1.0, 1
    ratio = count / max(median, RATIO_FLOOR)
    return round(ratio, 2), level_of(ratio)
