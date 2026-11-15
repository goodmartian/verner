import itertools
import json

import numpy as np
import pytest
from synth import NOAA_FIRST, make_pair

from senda_pipeline import validate

LAST = (2025 - 2000) * 12 + 11
CM = np.tile(np.arange(1, 13), 2)
SEASON = np.array([5.0, 8, 13, 30, 60, 90, 70, 40, 20, 12, 7, 6])


def test_metrics_exact_forecast():
    a = np.tile(SEASON, 2)
    m = validate.metrics(a, a, CM)
    assert m["wape"] == 0 and m["bias"] == 0 and m["spearman"] == pytest.approx(1.0)


def test_metrics_doubled_forecast():
    a = np.tile(SEASON, 2)
    m = validate.metrics(2 * a, a, CM)
    assert m["wape"] == pytest.approx(1.0) and m["bias"] == pytest.approx(1.0)
    assert m["spearman"] == pytest.approx(1.0)
    assert m["sign"] == 0.0  # actual equals its own median, forecast is above it


def test_metrics_sign_uses_given_base():
    a = np.array([10.0, 2.0, 10.0, 2.0])
    base = np.full(4, 5.0)
    m = validate.metrics(np.array([9.0, 3.0, 1.0, 9.0]), a, np.array([1, 2, 1, 2]), base)
    assert m["sign"] == 0.5


def test_metrics_undefined_cases_are_none():
    z = np.zeros(24)
    m = validate.metrics(np.ones(24), z, CM)
    assert m["wape"] is None and m["bias"] is None
    flat = validate.metrics(np.full(24, 3.0), np.full(24, 3.0), CM)
    assert flat["spearman"] is None  # constant series has no ranking


def test_error_curve_monotone():
    rng = np.random.default_rng(1)
    mmc = 10 ** rng.uniform(0, 5, 400)
    wape = 0.05 + 1.2 / np.sqrt(mmc) + rng.normal(0, 0.05, 400)
    recs = [{"mean_monthly_count": float(c), "wape": float(max(w, 0.0)), "actual": float(c * 100)} for c, w in zip(mmc, wape, strict=True)]
    curve = validate.error_curve(recs)
    assert 2 <= len(curve) <= validate.CURVE_BINS
    xs, ws = [c["mean_monthly_count"] for c in curve], [c["wape"] for c in curve]
    assert xs == sorted(xs)
    assert all(b <= a + 1e-12 for a, b in itertools.pairwise(ws))
    assert sum(c["samples"] for c in curve) == 400
    assert validate.error_curve([]) == []


def test_scenarios_on_exact_data():
    aqua = make_pair(k=4.0, last=LAST, rate=60.0)
    bridge = make_pair(k=1.0, first=NOAA_FIRST, last=LAST, rate=60.0)
    pool: list = []
    rows = validate.scenarios(aqua, bridge, aqua, pool)
    assert {r["scenario"] for r in rows} == {"loyo", "forward", "bridge_loyo", "bridge_forward", "recent_forward"}
    for scenario in ("loyo", "forward"):
        zone = [r for r in rows if r["scenario"] == scenario and r["level"] == "zone"]
        assert zone and all(r["wape"] < 1e-9 for r in zone)
    blocks = [r for r in rows if r["level"] == "block"]
    assert len(blocks) == 5 and all(r["entity"] == "all" and r["n_blocks"] > 0 for r in blocks)
    assert {"scenario", "level", "entity", "wape", "bias", "spearman", "sign", "n_months", "actual", "mean_monthly_count"} <= set(rows[0])
    loyo = next(r for r in rows if r["scenario"] == "loyo" and r["level"] == "zone")
    assert loyo["n_months"] == 8 * 12 - 1  # 2012-02 .. 2019-12
    assert pool and validate.error_curve(pool)
    json.dumps(rows, allow_nan=False)


def test_scenarios_skip_what_has_no_test_months():
    aqua = make_pair(k=4.0, last=(2019 - 2000) * 12 + 11)  # no forward years
    bridge = make_pair(k=1.0, first=NOAA_FIRST, last=(2021 - 2000) * 12 + 11)
    rows = validate.scenarios(aqua, bridge, aqua)
    assert "forward" not in {r["scenario"] for r in rows}
    assert "bridge_forward" not in {r["scenario"] for r in rows}
