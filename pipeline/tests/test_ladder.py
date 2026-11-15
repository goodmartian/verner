import numpy as np
import pytest
from synth import NOAA_FIRST, clone, make_pair

from senda_pipeline import fit, ladder

LAST = (2025 - 2000) * 12 + 11


def row(table, level):
    return next(r for r in table if r["level"] == level)


def test_daynight_needs_one_percent():
    assert ladder.choose_daynight(1.000, 0.995) is False  # 0.5 % better
    assert ladder.choose_daynight(1.000, 0.980) is True  # 2 % better
    assert ladder.choose_daynight(1.000, 0.990) is False  # exactly 1 % is not below
    assert ladder.choose_daynight(None, 0.5) is False


def test_daynight_chosen_only_when_the_data_split():
    split = make_pair(k_fn=lambda z, c, cm, dn: 3.0 if dn == "D" else 8.0, rate=30.0, noise=True)
    flat = make_pair(k=4.0, rate=30.0, noise=True)
    assert ladder.fit_l5(split, ladder.era_sel(split)).split is True
    assert ladder.fit_l5(flat, ladder.era_sel(flat)).split is False


def test_naive_level_is_worst():
    d = make_pair(k=4.0, rate=50.0)
    out = ladder.run(d)
    table = out["ladder"]
    assert [r["level"] for r in table] == list(ladder.LEVELS)
    assert row(table, "L0")["loyo_zone_wape"] == pytest.approx(0.75, abs=1e-9)
    assert row(table, "L3")["loyo_zone_wape"] < 0.01
    assert row(table, "L5")["forward_zone_wape"] < 0.01
    assert [r["level"] for r in table if r["chosen"]] == ["L5"]


def test_error_falls_down_the_ladder():
    d = make_pair(k_fn=lambda z, c, cm, dn: {"z0": 2.0, "z1": 4.0, "z2": 8.0}.get(z, 4.0), rate=40.0, noise=True)
    t = ladder.run(d)["ladder"]
    z = [row(t, lv)["loyo_zone_wape"] for lv in ("L0", "L1", "L2")]
    assert z[0] > z[1] > z[2]
    assert row(t, "L3")["loyo_zone_wape"] <= z[2] * 1.05


def test_selection_block():
    d = make_pair(k=4.0, rate=50.0, noise=True)
    out = ladder.run(d)
    sel = out["selection"]
    assert sel["lambda"] in fit.LAMBDAS and len(sel["lambda_scores"]) == len(fit.LAMBDAS)
    assert sel["daynight"] is False and sel["countries_used"] == int(out["final"].country.use.sum())
    assert len(sel["rules"]) >= 6 and all(isinstance(r, str) for r in sel["rules"])
    assert not any("{" in r for r in sel["rules"])


def test_predict_shapes_and_unknown_level():
    d = make_pair(k=4.0)
    sel, test = ladder.era_sel(d), d.valid & (d.year == 2020)
    pred, act = ladder.predict("L3", d, sel, test)
    assert pred.shape == act.shape == (len(d.g_zone), 12)
    assert np.allclose(pred, act)
    with pytest.raises(ValueError):
        ladder.predict("L9", d, sel, test)


def drifting(k_late):
    d = make_pair(k=1.0, first=NOAA_FIRST, last=LAST, rate=60.0)
    v = d.V.copy()
    v[:, d.year >= 2020] *= k_late
    return clone(d, d.M, v)


def test_bridge_window_last3_when_the_ratio_moved():
    window, scores = ladder.bridge_choose(drifting(1.3))
    assert window == "last3" and scores["last3"] < scores["all"]


def test_bridge_window_all_on_a_tie():
    window, _ = ladder.bridge_choose(drifting(1.0))
    assert window == "all"


def test_bridge_and_recent_folds():
    d = drifting(1.3)
    folds = ladder.bridge_folds(d, "last3")
    assert [int(np.unique(d.year[t])[0]) for _, t in folds["loyo"]] == [2023, 2024, 2025]
    fit_sel, test = folds["forward"][0]
    assert d.year[fit_sel].max() == 2022 and d.year[test].min() == 2023
    assert not (fit_sel & test).any()
    (rfit, rtest), = ladder.recent_folds(d)
    assert set(np.unique(d.year[rfit])) == {2022, 2023, 2024} and set(np.unique(d.year[rtest])) == {2025}
