import json
from datetime import date, timedelta

import numpy as np
import pytest
import synth

from senda_pipeline import harmonize, seam

SIZE = (2027 - 2000) * 12
K = 5.0  # VIIRS counts a fire K times as often as MODIS
FIRST, LAST = 36, (2026 - 2000) * 12 + 9  # 2003-01 .. 2026-10
YEARS = seam.placebo_years(FIRST, LAST)


def weather(growth=0.0, wobble=0.0, seed=0) -> np.ndarray:
    """Monthly activity of the land itself: seasonal, a steady trend, optional year to year noise."""
    t = np.arange(SIZE)
    rng = np.random.default_rng(seed)
    year_noise = np.exp(wobble * rng.standard_normal(SIZE // 12 + 1))[t // 12]
    return 1e5 * (1.2 + np.sin(2 * np.pi * t / 12)) * np.exp(growth * t) * year_noise


def series(w, factor=K, noise=0.0, seed=1) -> dict[str, np.ndarray]:
    """modis = w, VIIRS = K * w. as_is splices the raw sensors, ours converts MODIS with `factor`."""
    rng = np.random.default_rng(seed)
    t = np.arange(SIZE)
    before = t < seam.SEAM_MONTH
    seen_by_viirs = K * w * np.exp(noise * rng.standard_normal(SIZE))  # each sensor reads the land with its own noise
    converted = factor * w * np.exp(noise * rng.standard_normal(SIZE))
    return {
        "modis": w.copy(),
        "as_is": np.where(before, w, seen_by_viirs),
        "ours": np.where(before, converted, seen_by_viirs),
    }


def test_placebo_years_skip_the_join_and_split_by_era():
    assert YEARS["modis_era"] == list(range(2004, 2012))
    assert YEARS["viirs_era"] == list(range(2013, 2026))
    assert 2012 not in YEARS["modis_era"] + YEARS["viirs_era"]


def test_naive_series_jumps_and_ours_does_not():
    r = seam.evaluate(series(weather(growth=0.001)), YEARS)
    true_ratio = np.exp(0.001 * 12)
    assert r["seam"]["modis"] == pytest.approx(true_ratio, rel=1e-3)
    assert r["seam"]["as_is"] == pytest.approx(K * true_ratio, rel=1e-3)
    assert r["seam"]["gap"] == pytest.approx(0, abs=1e-6)
    assert r["seam"]["as_is_gap"] == pytest.approx(K - 1, rel=1e-3)
    assert r["status"] == "pass"


def test_placebo_ratio_is_the_known_growth():
    r = seam.evaluate(series(weather(growth=0.002)), YEARS)
    assert r["placebo_ratio"]["all"]["n"] == len(YEARS["modis_era"]) + len(YEARS["viirs_era"])
    # whole 12-month windows of a seasonal curve cancel the season, only the trend is left
    for era in ("modis_era", "viirs_era"):
        assert r["placebo_ratio"][era]["median"] == pytest.approx(np.exp(0.002 * 12), rel=1e-3)
        assert r["placebo_ratio"][era]["p10"] == pytest.approx(r["placebo_ratio"][era]["p90"], rel=1e-6)


def test_percentile_places_naive_jump_beyond_the_placebo_and_ours_inside():
    w = weather(growth=0.0, wobble=0.15)
    r = seam.evaluate(series(w, noise=0.02), YEARS)
    assert r["as_is_percentile"] == 100.0
    assert r["as_is_z"] > 3
    assert r["ours_percentile"] is not None
    assert abs(r["ours_z"]) < 3


def test_wrong_factor_is_marked_as_failed():
    w = weather(growth=0.0, wobble=0.1)
    ok = seam.evaluate(series(w, noise=0.03), YEARS)
    bad = seam.evaluate(series(w, factor=0.7 * K, noise=0.03), YEARS)
    assert abs(ok["seam"]["gap"]) < 0.1
    assert bad["status"] == "fail"
    assert bad["seam"]["gap"] == pytest.approx(1 / 0.7 - 1, abs=0.06)  # the part before the join is too small
    assert abs(bad["seam"]["gap"]) > bad["placebo_gap_p90_abs"]


def test_small_slice_is_not_judged():
    s = {k: v * 1e-6 for k, v in series(weather()).items()}
    r = seam.evaluate(s, YEARS)
    assert r["status"] == "insufficient"
    assert r["ours_percentile"] is None


def test_percentile_and_summary():
    assert seam.percentile_of(3, [1, 2, 3, 4, 5]) == 50.0
    assert seam.percentile_of(9, [1, 2]) == 100.0
    assert seam.percentile_of(float("nan"), [1, 2]) is None
    s = seam.summary([1, 2, 3, 4, float("nan")])
    assert s["n"] == 4 and s["median"] == 2.5 and s["p10"] == pytest.approx(1.3) and s["p90"] == pytest.approx(3.7)
    assert seam.summary([])["n"] == 0


def test_judge_uses_the_90th_percentile_of_absolute_gaps():
    gaps = [0.01, -0.02, 0.03, -0.04, 0.05, -0.06, 0.07, -0.08, 0.09, -0.10]
    limit = float(np.percentile(np.abs(gaps), 90))
    assert seam.judge(limit, gaps)["status"] == "pass"
    assert seam.judge(-limit * 1.01, gaps)["status"] == "fail"
    assert seam.judge(0.0, gaps[:3])["status"] == "insufficient"


def test_headline_text_carries_the_three_numbers():
    h = seam.headline(seam.evaluate(series(weather(growth=0.001)), YEARS))
    assert h["naive_jump"] == pytest.approx(K * np.exp(0.012), rel=1e-3)
    assert h["ours_gap_pct"] == pytest.approx(0, abs=1e-4)
    assert h["placebo_p10"] <= h["placebo_median"] <= h["placebo_p90"]
    assert f"{h['naive_jump']:.2f}" in h["text"] and "year to year" in h["text"]


# ---------------------------------------------------------------- short join

LAST_DAY = date(2026, 11, 12)
SEAM_DAY = date(2026, 11, 2)


def daily(start: date, end: date, fn) -> dict[date, float]:
    return {start + timedelta(days=i): float(fn(start + timedelta(days=i))) for i in range((end - start).days + 1)}


def test_day_mean_needs_enough_days():
    c = daily(date(2026, 1, 1), date(2026, 1, 10), lambda d: 10)
    assert seam.day_mean(c, date(2026, 1, 1), date(2026, 1, 10)) == 10
    assert np.isnan(seam.day_mean(c, date(2026, 1, 1), date(2026, 1, 30)))


def test_short_join_noaa_is_a_different_scale_but_ours_is_not():
    span = (date(2013, 1, 1), date(2026, 12, 31))
    base = lambda d: 1000 * (1 + 0.3 * np.cos((d.timetuple().tm_yday / 365) * 2 * np.pi))
    snpp = daily(*span, base)
    noaa = daily(date(2018, 4, 1), span[1], lambda d: 1.1 * base(d))  # NOAA-20 counts 10% more
    as_is = {d: (v if d < SEAM_DAY else noaa[d]) for d, v in snpp.items() if d <= LAST_DAY}
    ours = {d: (v if d < SEAM_DAY else noaa[d] / 1.1) for d, v in snpp.items() if d <= LAST_DAY}
    r = seam.short_seam(ours, as_is, noaa, snpp, noaa, SEAM_DAY, LAST_DAY, 2018)
    assert r["after_days"] == 11 and r["before_days"] == 30
    assert r["seam"]["as_is_gap"] == pytest.approx(0.1, abs=1e-9)
    assert r["seam"]["gap"] == pytest.approx(0.0, abs=1e-9)
    assert [x["year"] for x in r["placebo"]] == list(range(2018, 2026))
    assert r["status"] in ("pass", "insufficient")
    assert r["placebo_gap"]["median"] == pytest.approx(0.0, abs=1e-9)


def test_run_on_synthetic_work(tmp_path):
    w = synth.write_work(tmp_path)
    harmonize.run(w)
    out = seam.run(w)
    assert json.loads((w / "built" / "seam.json").read_text())["parameters"]["seam_2012"] == "2012-02"
    assert out["slices"][0]["kind"] == "world"
    assert {"naive_jump", "ours_gap_pct", "placebo_p10", "placebo_p90"} <= set(out["headline"])


def test_headline_text_survives_too_few_placebo_years():
    world = seam.evaluate(series(weather(growth=0.001)), YEARS)
    world |= {"placebo_change_median_abs": None, "placebo_gap_p90_abs": None, "status": "insufficient"}
    h = seam.headline(world)
    assert h["placebo_typical_change_pct"] is None and "not known" in h["text"]
