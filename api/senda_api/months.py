"""Month numbers (months since 2000-01) and period parsing."""

from __future__ import annotations

import calendar
import re
from datetime import date

import numpy as np

from .errors import ApiError

# First year of the comparison baseline (medians, normals, ranks, season, trend, expected error, forecast). The months
# before it come from MODIS Terra, a morning satellite, and from the first half-year of Aqua: they are shown in the
# series, the yearly totals and the exports, but never enter the baseline.
BASE_FIRST_YEAR = 2003
BASE_FIRST_MONTH = (BASE_FIRST_YEAR - 2000) * 12

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def month_of(d: date) -> int:
    return (d.year - 2000) * 12 + d.month - 1


def month_label(m: int) -> str:
    return f"{m // 12 + 2000:04d}-{m % 12 + 1:02d}"


def month_start(m: int) -> date:
    return date(m // 12 + 2000, m % 12 + 1, 1)


def month_end(m: int) -> date:
    y, mo = m // 12 + 2000, m % 12 + 1
    return date(y, mo, calendar.monthrange(y, mo)[1])


def parse_month_label(value: str) -> int:
    match = _MONTH_RE.match(value) if isinstance(value, str) else None
    if not match or not 1 <= int(match.group(2)) <= 12 or not 1900 <= int(match.group(1)) <= 2999:
        raise ValueError(f"expected YYYY-MM, got {value!r}")
    return (int(match.group(1)) - 2000) * 12 + int(match.group(2)) - 1


def parse_month(value: str | None, name: str) -> int | None:
    if value is None:
        return None
    try:
        return parse_month_label(value)
    except ValueError:
        raise ApiError(400, "invalid_period", f"{name} must look like 2026-10") from None


def parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ApiError(400, "invalid_period", f"{name} must be a date like 2026-10-28") from None


def round_int(x: float) -> int:
    """Round half to even, the rule used for every count in the API."""
    return int(np.rint(x))
