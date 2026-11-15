import numpy as np
import oracle
import pytest

from senda_api import areas, levels
from senda_api import cells as cells_mod
from senda_api.errors import ApiError

REGION = {"id": "XA"}
CELL_A = 461600


def month_cells(store, area, month):
    return cells_mod.month_cells(store, areas.parse(area, store), month)


def test_cells_levels(store, data_dir):
    cells = month_cells(store, REGION, "2015-07")["cells"]
    assert cells and all(set(c) == {"cell_id", "lat", "lon", "count", "median", "level"} for c in cells)
    assert [c["cell_id"] for c in cells] == sorted(c["cell_id"] for c in cells)
    daily = oracle.load_daily(data_dir)
    for c in cells:
        assert c["count"] > 0 or c["median"] > 0
        assert c["level"] == levels.ratio_level(c["count"], c["median"])[1]
        totals = oracle.month_totals(daily, {c["cell_id"]: 1.0})
        values = [oracle.rint(totals.get((y, 7), 0.0)) for y in range(2003, 2026)]
        assert c["count"] == oracle.rint(totals.get((2015, 7), 0.0))
        assert c["median"] == oracle.rint(np.median(values))
    a = next(c for c in cells if c["cell_id"] == CELL_A)
    assert a["count"] == 7 and (a["lat"], a["lon"]) == (9.875, 20.125)


def test_cells_skip_cells_that_are_empty_and_usually_empty(store):
    ids = {c["cell_id"] for c in month_cells(store, REGION, "2015-07")["cells"]}
    assert 461600 + 9 + 3 * 1440 not in ids  # the cell that never burned


def test_cells_respect_area_weights(store):
    half = month_cells(store, {"bbox": [20.0, 9.75, 20.125, 10.0]}, "2015-07")["cells"]
    assert [c["cell_id"] for c in half] == [CELL_A] and half[0]["count"] in (3, 4)  # 7 fires x weight 0.5


def test_cells_current_month_uses_data_to_date(store):
    assert all(c["count"] >= 0 for c in month_cells(store, REGION, "2026-11")["cells"])


@pytest.mark.parametrize("month", ["2002-12", "2026-12", "x", "2015-13", None])
def test_cells_bad_month(store, month):
    with pytest.raises(ApiError) as error:
        month_cells(store, REGION, month)
    assert (error.value.status, error.value.code) == (400, "invalid_period")


def test_cells_bad_area(store):
    with pytest.raises(ApiError) as error:
        month_cells(store, {"bbox": [0, 0, 1, 1]}, "2015-07")
    assert (error.value.status, error.value.code) == (422, "no_land")
