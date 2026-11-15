from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import box

from senda_pipeline import cells


def test_zone_name():
    assert cells.zone_name(7, -27) == "resolve-07-s"
    assert cells.zone_name(1, 5) == "resolve-01-n"
    assert cells.zone_name(14, 0.125) == "resolve-14-n"


def test_cell_id_formula():
    # row = floor((90 - lat) / 0.25), col = floor((lon + 180) / 0.25)
    assert cells.cell_id(89.9, -179.9) == 0
    assert cells.cell_id(-27.4, -58.8) == int((90 + 27.4) // 0.25) * 1440 + int((-58.8 + 180) // 0.25)
    assert cells.cell_id(-90.0, 180.0) == 719 * 1440 + 1439  # poles and the antimeridian stay in range
    assert np.array_equal(cells.cell_id(np.array([89.9, 89.9]), np.array([-179.9, -179.8])), [0, 0])


def test_land_frac_partial():
    # the cell [10, 10.25] x [5, 5.25]; the polygon covers x in [10, 10.1]: 2 of 5 point columns
    df = cells.compute([("AA", box(10.0, 5.0, 10.1, 5.25))], [])
    assert df.height == 1
    row = df.row(0, named=True)
    assert 0.4 <= row["land_frac"] <= 0.6
    assert row["cell_id"] == cells.cell_id(5.1, 10.1)
    assert row["lat"] == pytest.approx(5.125) and row["lon"] == pytest.approx(10.125)


def test_full_cell_has_land_frac_one():
    df = cells.compute([("AA", box(10.0, 5.0, 10.25, 5.25))], [])
    assert df["land_frac"].to_list() == [1.0]
    assert df["country"].to_list() == ["AA"]


def test_ocean_cell_absent():
    df = cells.compute([("AA", box(10.0, 5.0, 10.25, 5.25))], [])
    assert df.height == 1
    assert df["cell_id"].to_list() == [cells.cell_id(5.1, 10.1)]  # neighbours in the sea are not listed


def test_country_of_sea_centred_cell_is_the_one_with_most_points():
    # centre point x = 10.125 stays in the sea; A holds 1 column, B holds 2 columns
    a = ("AA", box(10.0, 5.0, 10.06, 5.25))
    b = ("BB", box(10.13, 5.0, 10.25, 5.25))
    df = cells.compute([a, b], [])
    assert df["country"].to_list() == ["BB"]
    assert df["land_frac"][0] == pytest.approx(0.6)


def test_country_of_centre_wins():
    a = ("AA", box(10.0, 5.0, 10.14, 5.25))  # covers the centre and 3 columns
    b = ("BB", box(10.14, 5.0, 10.25, 5.25))  # 2 columns
    assert cells.compute([a, b], [])["country"].to_list() == ["AA"]


def test_zone_from_biome_at_centre_and_none_without():
    land = ("AA", box(10.0, -5.25, 10.5, 5.25))
    north = box(10.0, 0.0, 10.5, 5.25)
    df = cells.compute([land], [(7, north)]).sort("cell_id")
    zones = dict(zip(df["lat"].to_list(), df["zone"].to_list()))
    assert zones[5.125] == "resolve-07-n"
    assert zones[-5.125] == "none"


def test_coastal_cell_takes_majority_biome():
    # the biome starts at x = 10.13: the centre (10.125) is outside, 2 columns x 5 rows = 10 of 25 points inside
    land = ("AA", box(10.0, 5.0, 10.25, 5.25))
    df = cells.compute([land], [(12, box(10.13, 5.0, 10.25, 5.25))])
    assert df["zone"].to_list() == ["resolve-12-n"]


def test_biome_tie_goes_to_centre_biome():
    land = ("AA", box(10.0, 5.0, 10.25, 5.25))
    a = (3, box(10.0, 5.0, 10.1, 5.25))  # 10 points, smaller number
    b = (9, box(10.1, 5.0, 10.2, 5.25))  # 10 points, holds the centre
    assert cells.compute([land], [a, b])["zone"].to_list() == ["resolve-09-n"]


def test_empty_input_gives_typed_empty_table():
    df = cells.compute([], [])
    assert df.height == 0
    assert df.columns == ["cell_id", "lat", "lon", "zone", "country", "land_frac"]
