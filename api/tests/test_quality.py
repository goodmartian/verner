import math

import numpy as np
import polars as pl
import pytest

from senda_api import areas, quality, weights

CURVE = [
    {"mean_monthly_count": 1.0, "wape": 0.6, "samples": 1},
    {"mean_monthly_count": 10.0, "wape": 0.3, "samples": 1},
    {"mean_monthly_count": 100.0, "wape": 0.15, "samples": 1},
    {"mean_monthly_count": 1000.0, "wape": 0.08, "samples": 1},
]
CELL_A = {"bbox": [20.0, 9.75, 20.25, 10.0]}
WEST = {"bbox": [20.0, 9.0, 21.25, 10.0]}
EAST = {"bbox": [21.25, 9.0, 22.5, 10.0]}
NEVER = {"bbox": [22.25, 9.0, 22.5, 9.25]}


def of(store, selector, **kw):
    area = areas.parse(selector, store)
    idx, w = weights.cell_weights(store, area)
    return quality.for_area(store, idx, w, area_id=area.id, **kw)


def test_expected_error_interpolates():
    assert quality.interpolate_error(CURVE, math.sqrt(10)) == pytest.approx(0.45)  # halfway in log space
    assert quality.interpolate_error(CURVE, 10.0) == pytest.approx(0.3)
    assert quality.interpolate_error(CURVE, 31.6227766) == pytest.approx(0.225)
    assert quality.interpolate_error(CURVE, 0.2) == 0.6  # left of the curve: the largest error
    assert quality.interpolate_error(CURVE, 0.0) == 0.6
    assert quality.interpolate_error(CURVE, 5000) == 0.08
    assert quality.interpolate_error([], 5) is None


def test_expected_error_uses_raw_snpp_mean(store, data_dir):
    got = of(store, CELL_A)
    monthly = pl.read_parquet(data_dir / "monthly.parquet").filter(
        (pl.col("cell_id") == 461600) & (pl.col("sensor") == "viirs_snpp") & (pl.col("month") >= 145) & (pl.col("month") <= 263)
    )
    mean = (monthly["n_day"].sum() + monthly["n_night"].sum()) / 119  # 2012-02 .. 2021-12 with zeros
    assert got["expected_error"] == pytest.approx(quality.interpolate_error(CURVE, mean), abs=1e-4)
    assert got["basis"] == "loyo+forward"


@pytest.mark.parametrize(
    "error,share,expected",
    [(0.1, 0.0, "high"), (0.15, 0.05, "high"), (0.1, 0.1, "medium"), (0.3, 0.0, "medium"), (0.5, 0.0, "low"),
     (0.1, 0.5, "low"), (0.35, 0.2, "medium")],
)
def test_confidence_rule(error, share, expected):
    thresholds = {"high_wape": 0.15, "medium_wape": 0.35, "high_unharmonized_share": 0.05,
                  "medium_unharmonized_share": 0.20}
    assert quality.confidence(error, share, thresholds) == expected


def test_unharmonized_share(store):
    assert of(store, WEST)["unharmonized_share"] == 0.0  # kgroup 1 factors are zone x month
    east = of(store, EAST)["unharmonized_share"]
    assert 0.5 < east <= 1.0  # kgroup 2 MODIS factors are zone-only


def test_quality_null_without_modis_months(store):
    got = of(store, NEVER)
    assert got == {"expected_error": None, "confidence": None, "unharmonized_share": 0.0, "basis": "loyo+forward"}


def test_country_validation_raises_error(store):
    plain = of(store, {"bbox": [20.0, 9.0, 22.5, 10.0]})
    country = of(store, {"id": "XA"})
    assert country["expected_error"] == pytest.approx(max(plain["expected_error"], 0.45))


def test_mean_monthly_count_skips_incomplete_months(store):
    idx, w = weights.cell_weights(store, areas.parse(CELL_A, store))
    assert quality.mean_monthly_count(store, idx, w) >= 0
    assert np.isfinite(quality.mean_monthly_count(store, idx, w))
