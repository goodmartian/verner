from dataclasses import replace
from datetime import date

import numpy as np
import oracle
import pytest

from senda_api import areas, daily, weights

TWO_CELLS = {"bbox": [20.0, 9.75, 20.5, 10.0]}
FRACTIONAL = {"bbox": [20.1, 9.1, 21.9, 9.9]}


@pytest.fixture(scope="module")
def rows(data_dir):
    return oracle.load_daily(data_dir)


def run(store, selector, start, end):
    area = areas.parse(selector, store)
    idx, w = weights.cell_weights(store, area)
    return daily.same_dates(store, idx, w, start, end), {
        int(store.cells.cell_id[i]): float(x) for i, x in zip(idx, w, strict=True)
    }


def expected(rows, w, start, end, store):
    def shift(d, year):
        return date(year, 2, 28) if (d.month, d.day) == (2, 29) and year % 4 else date(year, d.month, d.day)

    cross = (end.month, end.day) < (start.month, start.day)
    values = []
    for y in store.base_years:
        s, e = shift(start, y), shift(end, y + cross)
        values.append(oracle.rint(oracle.window_total(rows, w, s, e)))
    count = oracle.rint(oracle.window_total(rows, w, start, end))
    return count, values


@pytest.mark.parametrize(
    "selector,start,end",
    [
        (TWO_CELLS, date(2026, 11, 1), date(2026, 11, 12)),
        (FRACTIONAL, date(2026, 11, 1), date(2026, 11, 12)),
        (FRACTIONAL, date(2010, 7, 5), date(2010, 8, 20)),
        (FRACTIONAL, date(2025, 12, 20), date(2026, 1, 10)),
        (FRACTIONAL, date(2022, 3, 1), date(2022, 3, 31)),
    ],
)
def test_same_dates_matches_oracle(store, rows, selector, start, end):
    got, w = run(store, selector, start, end)
    count, values = expected(rows, w, start, end, store)
    assert got["count"] == count
    assert got["median"] == oracle.rint(np.median(values))
    assert got["p10"] == oracle.rint(np.percentile(values, 10)) and got["p90"] == oracle.rint(np.percentile(values, 90))
    assert got["years"] == len(values) and got["of"] == len(values) + (0 if start.year in store.base_years else 1)
    assert got["rank"] == 1 + sum(v > count for v in values)
    assert got["ratio"] == (1.0 if count == 0 and got["median"] == 0 else round(count / max(got["median"], 1), 2))
    assert set(got) == {"count", "median", "p10", "p90", "rank", "of", "ratio", "years"}


def test_feb29_maps_to_feb28(store, rows):
    assert daily.shift_to_year(date(2024, 2, 29), 2023) == date(2023, 2, 28)
    assert daily.shift_to_year(date(2024, 2, 29), 2020) == date(2020, 2, 29)
    assert daily.shift_to_year(date(2024, 3, 1), 2023) == date(2023, 3, 1)
    got, w = run(store, FRACTIONAL, date(2024, 2, 1), date(2024, 2, 29))
    count, values = expected(rows, w, date(2024, 2, 1), date(2024, 2, 29), store)
    assert got["count"] == count and got["median"] == oracle.rint(np.median(values))


def test_fewer_than_three_years_null_median(store):
    small = replace(store, base_years=[2003, 2004])
    got, _ = run(small, TWO_CELLS, date(2026, 11, 1), date(2026, 11, 12))
    assert got["count"] is not None and got["years"] == 2
    assert got["median"] is None and got["ratio"] is None and got["rank"] is None


def test_cross_year_window_reads_both_years(store, rows):
    got, w = run(store, FRACTIONAL, date(2024, 12, 20), date(2025, 1, 10))
    count, values = expected(rows, w, date(2024, 12, 20), date(2025, 1, 10), store)
    assert got["count"] == count and got["years"] == len(values) == len(store.base_years)


def test_never_burned_window(store):
    got, _ = run(store, {"bbox": [22.25, 9.0, 22.5, 9.25]}, date(2026, 11, 1), date(2026, 11, 12))
    assert got["count"] == 0 and got["median"] == 0 and got["ratio"] == 1.0 and got["rank"] == 1 + 0
