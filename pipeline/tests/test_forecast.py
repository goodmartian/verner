import json

import numpy as np
import polars as pl
import pytest

from senda_pipeline import forecast as f

YEARS = list(range(2003, 2023))  # synthetic archive: 2003-01 .. 2022-12
MONTHS = len(YEARS) * 12
FIRST_CELL = 100 * 1440 + 100  # boxes of 1 degree are 4 x 4 cells; the grid below is 2 x 2 boxes with 4 cells each


def make_setup(seed: int = 0, scale_from: int | None = None, factor: float = 1.0) -> f.Setup:
    """Four boxes with a seasonal profile, a yearly level that lasts, and noise. `scale_from`: month column from
    which the counts are multiplied by `factor` (to check that a forecast does not look at the future)."""
    rng = np.random.default_rng(seed)
    ids, box_of = [], []
    for br in range(2):
        for bc in range(2):
            for dr in (0, 1):
                for dc in (0, 1):
                    ids.append((100 + 4 * br + dr) * 1440 + 100 + 4 * bc + dc)
                    box_of.append(br * 2 + bc)
    ids = np.array(ids)
    order = np.argsort(ids)
    ids, box_of = ids[order], np.array(box_of)[order]
    season = 1.0 + 0.9 * np.sin(2 * np.pi * (np.arange(MONTHS) % 12 - box_of[:, None] * 2) / 12)
    level = np.zeros((4, MONTHS))
    for m in range(1, MONTHS):
        level[:, m] = 0.8 * level[:, m - 1] + rng.normal(0, 0.35, 4)
    mean = 60 * season * np.exp(level[box_of]) * (1 + box_of[:, None])
    counts = rng.poisson(mean / 4).astype(np.float32)
    if scale_from is not None:
        counts[:, scale_from:] *= factor
    import scipy.sparse as sp

    cells = pl.DataFrame({
        "cell_id": ids, "lat": 90 - (ids // 1440 + 0.5) * 0.25, "lon": -180 + (ids % 1440 + 0.5) * 0.25,
        "zone": ["resolve-01-n"] * len(ids), "country": ["AA"] * len(ids), "land_frac": np.ones(len(ids), np.float32),
    })  # fmt: skip
    data = f.Data(cells, sp.csr_matrix(counts), 36 + MONTHS - 1, YEARS)
    boxes = f.make_boxes(data)
    items = [(np.arange(len(ids)), np.ones(len(ids))), (np.nonzero(box_of < 2)[0], np.ones(8)), (np.nonzero(box_of == 2)[0], np.ones(4))]
    W = f.weight_matrix(len(ids), items)
    real = np.rint(np.asarray((W @ data.H).todense()))
    return f.Setup(data, boxes, ["world", "AR", "AR-A"], ["world", "country", "region"], W, real)


@pytest.fixture(autouse=True)
def small(monkeypatch):
    monkeypatch.setattr(f, "ROWS_PER_H", 3000)
    monkeypatch.setattr(f, "MIN_BOX_TOTAL", 20)
    monkeypatch.setattr(f, "MIN_TEST_TOTAL", 10)
    monkeypatch.setattr(f, "TEST_YEARS", [2017, 2018, 2019, 2020, 2021, 2022])
    monkeypatch.setattr(f, "CALIB_YEARS", list(range(2011, 2023)))


def test_board_error_is_the_apis_formula():
    rng = np.random.default_rng(1)
    real = rng.integers(0, 500, (3, MONTHS)).astype(float)
    got = f.board_year_error(real, YEARS)
    values = np.stack([real[:, f.year_cols(y)] for y in YEARS], axis=1)  # areas x years x 12
    for a in range(3):  # the code of Ser.accuracy, per area
        v = values[a]
        guess = np.array([np.median(np.delete(v, k, axis=0), axis=0) for k in range(len(v))])
        expected = np.abs(guess.sum(axis=1) - v.sum(axis=1)).sum() / max(1.0, v.sum())
        assert got[a] == pytest.approx(expected)


def test_forward_median_sees_only_the_past():
    real = np.zeros((1, MONTHS))
    for y in YEARS:
        real[0, f.year_cols(y)] = y  # every month of a year equals the year
    clim = f.climatology(real, YEARS, "forward", [2010])
    assert clim.med[0, f.year_cols(2010)[0]] == np.median(np.arange(2003, 2010))
    loyo = f.climatology(real, YEARS, "loyo", [2010])
    assert loyo.med[0, f.year_cols(2010)[0]] == np.median([y for y in YEARS if y != 2010])


@pytest.mark.parametrize("model", ["persistence", "ridge"])
def test_no_leakage_a_forecast_ignores_what_comes_after_its_start(model):
    year, c = 2018, f.year_cols(2018)[0] + 5
    base = make_setup()
    changed = make_setup(scale_from=c, factor=7.0)  # everything from month c on is different
    a = f.run_folds(base, model, "forward", [year])
    b = f.run_folds(changed, model, "forward", [year])
    cols = f.year_cols(year)
    for h in f.HORIZONS:
        ok = cols[(cols - h) < c]  # forecasts made before month c
        assert len(ok) or h > 5
        assert np.allclose(a[h][:, ok], b[h][:, ok]), (model, h)
    assert not np.allclose(a[f.HORIZONS[0]][:, cols[-1]], b[f.HORIZONS[0]][:, cols[-1]])  # while the last months do react


def test_loyo_training_never_touches_the_checked_year():
    allowed = np.ones(MONTHS, bool)
    allowed[f.year_cols(2015)] = False
    for h in f.HORIZONS:
        t = f.eligible_starts(allowed, h)
        assert len(t) > 100
        for window in (np.arange(x - f.LAGS + 1, x + h + 1) for x in t[::7]):
            assert allowed[window].all()
    assert f.eligible_starts(allowed, 1).min() == f.LAGS - 1


def test_a_normal_month_keeps_the_calendar_median_of_the_area():
    setup = make_setup()
    years, allowed = f.window(setup, "forward", 2019)
    st = f.make_state(setup, years, allowed)
    cols = f.year_cols(2019)
    cal = (cols + f.ARCHIVE_START) % 12
    base = np.stack([setup.real[:, f.year_cols(y)] for y in years], axis=1)
    med = np.median(base, axis=1)
    P = f.boxes_from_anomaly(st, np.zeros((setup.boxes.n, 12)), cal)
    got = f.area_forecast(st, P, cal, med)
    assert np.allclose(got, med)  # no anomaly, no change, however the medians of the boxes add up


def test_selection_and_shares_come_from_the_training_window_only():
    setup = make_setup()
    cols = f.year_cols(2019)
    early = np.arange(MONTHS) < cols[0]
    st_early = f.make_state(setup, list(range(2003, 2019)), early)
    boosted = make_setup(scale_from=cols[0], factor=1000.0)  # the years after the window explode
    st_boost = f.make_state(boosted, list(range(2003, 2019)), early)
    assert (st_early.sel == st_boost.sel).all()
    assert np.allclose(st_early.S.toarray(), st_boost.S.toarray())


def test_ranges_are_ordered_and_cover_about_four_fifths():
    setup = make_setup(seed=3)
    per = f.run_folds(setup, "persistence", "forward", f.CALIB_YEARS)
    rng = f.with_range(setup, per, "forward", f.TEST_YEARS, f.CALIB_YEARS)
    cols = np.concatenate([f.year_cols(y) for y in f.TEST_YEARS])
    hits = []
    for h in f.HORIZONS:
        lo, hi = rng[h][0][:, cols], rng[h][1][:, cols]
        assert (lo <= hi).all() and (lo >= 0).all()
        hits.append(((lo <= setup.real[:, cols]) & (setup.real[:, cols] <= hi)).mean())
    assert 0.6 < np.mean(hits) < 0.95


def test_use_model_needs_ten_percent_and_a_good_range():
    n = 7
    base = f.Score(np.full((6, n), 100.0), np.full(n, 1000.0), np.full(n, 1000.0), np.zeros(n), np.ones(n), np.zeros((6, n)), np.full(n, 100))
    err = np.tile([[80.0], [89.9], [90.1], [80.0], [80.0], [80.0]], (1, n))  # horizons 1-6: 20 %, 10.1 %, 9.9 % better, ...
    hit = np.full((6, n), 75.0)
    hit[:, 3], hit[:, 4], hit[:, 5] = 69, 91, 70  # too narrow, too wide, the edge of the band (in)
    model = f.Score(err, base.real, base.med, base.err6, base.real6, hit, base.n)
    ok = f.use_model(model, base, np.arange(n - 1))  # the last area is not scored
    assert ok[0, 0] and ok[1, 0] and not ok[2, 0]
    assert not ok[:, 0][3:].any()  # horizon 3 fails (9.9 %), so 4-6 are median even though they pass
    assert not ok[0, 3] and not ok[0, 4] and ok[0, 5] and not ok[:, 6].any()


def test_the_model_is_used_on_a_prefix_of_horizons():
    n = 3
    base = f.Score(np.full((6, n), 100.0), np.full(n, 1000.0), np.full(n, 1000.0), np.zeros(n), np.ones(n), np.zeros((6, n)), np.full(n, 100))
    err = np.full((6, n), 80.0)
    err[3, 1] = 100.0  # area 1: horizon 4 no better than the median
    err[0, 2] = 100.0  # area 2: already horizon 1 is not
    model = f.Score(err, base.real, base.med, base.err6, base.real6, np.full((6, n), 75.0), base.n)
    ok = f.use_model(model, base, np.arange(n))
    assert ok.sum(axis=0).tolist() == [6, 3, 0]
    for a in range(n):
        k = ok[:, a].sum()
        assert ok[:, a].tolist() == [True] * k + [False] * (6 - k)
    counts = f.horizon_counts(ok, ["world", "AR", "XX"])
    assert counts == {"scored_with_model": 2, "k_at_least_3": 2, "k_6": 1, "world": 6, "AR": 3}


def test_noise_has_a_floor_and_size_classes_follow_the_mean_year():
    real = np.zeros((3, MONTHS))
    real[1] = 50.0
    real[2] = 5000.0
    assert (f.noise(real, YEARS) == f.NOISE_FLOOR).all()
    assert f.size_class(real, YEARS).tolist() == [0, 1, 3]  # 0, 600 and 60000 detections a year


def test_check_writes_the_files_the_api_reads(tmp_path):
    setup = make_setup(seed=5)
    ev = f.evaluate(setup, [("AR-A", "2019-07")], ("persistence", "ridge"), log=lambda _: None)
    out = f.produce(setup, ev["choice"]["model"], ev)
    (tmp_path / "manifest.json").write_text(json.dumps({"version": "20230101-abcdef123456"}))
    f.write(tmp_path, setup, ev, out)
    doc = json.loads((tmp_path / "forecast.json").read_text())
    assert doc["version"] == "20230101-abcdef123456" and doc["trained_through"] == "2022-12"
    assert doc["method_default"] == "climatology" and doc["model"]["months"][0] == "2023-02" and doc["model"]["horizons"] == [2, 3, 4, 5, 6, 7] and doc["train_rows"] > 0
    assert set(doc["tables"]) == {"world", "argentina", "countries", "argentina_provinces", "regions", "selection_holdout"}
    assert doc["seasons"][0]["region_id"] == "AR-A"
    one = doc["validated"]["world"]
    assert len(one["model_err_pct"]) == len(one["coverage"]) == len(one["use_model"]) == 6
    table = pl.read_parquet(tmp_path / "forecast.parquet")
    assert table.columns == ["region_id", "month", "horizon", "p10", "p50", "p90", "method", "err_pct"]
    assert (table["method"] == "model").all()
    assert (table["p10"] >= 0).all()
    for name, flags in doc["use_model"].items():
        k = sum(flags)
        assert flags == [True] * k + [False] * (6 - k) and doc["model_horizons"][name] == k == doc["validated"][name]["model_horizons"]
    flags = {(r, doc["model"]["horizons"][i]) for r, v in doc["use_model"].items() for i, on in enumerate(v) if on}
    assert flags == set(zip(table["region_id"].to_list(), table["horizon"].to_list(), strict=True))


def test_load_builds_the_harmonized_series_with_the_factors(tmp_path):
    cells = pl.DataFrame({"cell_id": [100 * 1440 + 100, 100 * 1440 + 101], "lat": [64.9, 64.9], "lon": [-154.9, -154.6],
                          "zone": ["none", "none"], "country": ["AA", "AA"], "land_frac": [1.0, 1.0]})  # fmt: skip
    cells.write_parquet(tmp_path / "cells.parquet")
    pl.DataFrame({"cell_id": cells["cell_id"], "kgroup": [7, 7]}).write_parquet(tmp_path / "cell_groups.parquet")
    rows = []
    for sensor, window, kd, kn in (("modis_aqua", "era", 2.0, 3.0), ("modis_aqua", "recent", 5.0, 7.0), ("viirs_noaa20", "era", 1.5, 1.5)):
        for dn, k in (("D", kd), ("N", kn)):
            for cal in range(1, 13):
                rows.append({"kgroup": 7, "sensor": sensor, "calmonth": cal, "dn": dn, "window": window, "k": k, "basis": "zone"})
    pl.DataFrame(rows).write_parquet(tmp_path / "factors.parquet")
    c0 = 100 * 1440 + 100
    series = [  # cell, month (absolute), sensor, day, night
        (c0, 12 * 21 + 5, "modis_aqua", 10, 4),  # 2021-06: era window
        (c0, 12 * 22 + 2, "modis_aqua", 10, 4),  # 2022-03: recent window
        (c0, 12 * 22 + 2, "viirs_snpp", 10, 4),  # the reference sensor keeps its counts
        (c0 + 1, 12 * 22 + 2, "viirs_noaa20", 2, 2),
    ]
    pl.DataFrame(series, schema=["cell_id", "month", "sensor", "n_day", "n_night"], orient="row").write_parquet(tmp_path / "series_monthly.parquet")
    (tmp_path / "manifest.json").write_text(json.dumps({"last_complete_date": "2023-01-20", "version": "x"}))
    data = f.load(tmp_path)
    assert data.last_seen == 12 * 22 + 11 and data.base_years[0] == 2003 and data.base_years[-1] == 2022
    H = data.H.toarray()
    assert H[0, 12 * 21 + 5 - 36] == 10 * 2 + 4 * 3
    assert H[0, 12 * 22 + 2 - 36] == 10 * 5 + 4 * 7 + 14
    assert H[1, 12 * 22 + 2 - 36] == 2 * 1.5 + 2 * 1.5
    pl.DataFrame(series[:1], schema=["cell_id", "month", "sensor", "n_day", "n_night"], orient="row").with_columns(
        sensor=pl.lit("viirs_noaa20")).write_parquet(tmp_path / "series_monthly.parquet")
    pl.DataFrame(rows[:1]).write_parquet(tmp_path / "factors.parquet")  # a table without the noaa20 factor
    with pytest.raises(ValueError, match="missing conversion factor"):
        f.load(tmp_path)


def test_a_version_with_its_forecast_is_not_built_again(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"version": "v1"}))
    assert not f.is_current(tmp_path)
    (tmp_path / "forecast.json").write_text(json.dumps({"version": "v1"}))
    assert not f.is_current(tmp_path)  # the table is missing
    pl.DataFrame({"a": [1]}).write_parquet(tmp_path / "forecast.parquet")
    assert f.is_current(tmp_path)
    assert f.run(tmp_path, log=lambda _: None) is None
    (tmp_path / "forecast.json").write_text(json.dumps({"version": "v0"}))
    assert not f.is_current(tmp_path)
