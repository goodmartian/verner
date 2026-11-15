import json
from datetime import UTC, date, datetime

import polars as pl
import pytest
from fixture_zips import MODIS_HEAD, VIIRS_HEAD, modis, viirs, write_api, write_zip

from senda_pipeline import build, grid


def _cid(lat, lon):
    return pl.DataFrame({"a": [lat], "b": [lon]}).select(grid.cell_id(pl.col("a"), pl.col("b")))["cell_id"][0]


def _cell01(lat, lon):
    return pl.DataFrame({"a": [lat], "b": [lon]}).select(grid.cell01(pl.col("a"), pl.col("b")))["cell01"][0]


C1, C2, C3, C4 = _cid(10.1, 20.1), _cid(10.6, 20.6), _cid(-30.1, 150.1), _cid(-27.4, -58.8)
JUN, JUL = grid.month_index(2025, 6), grid.month_index(2025, 7)
JAN26 = grid.month_index(2026, 1)

# (utc_date, snpp ok, noaa20 ok, aqua ok); the chosen sensor is the first ok one of the chain
DAYS = [
    (date(2025, 6, 1), True, True, True),
    (date(2025, 6, 2), False, True, True),  # S-NPP low day
    (date(2025, 6, 3), True, False, True),
    (date(2025, 6, 30), True, True, True),
    (date(2025, 7, 1), False, True, True),
    (date(2000, 10, 30), False, False, True),
    (date(2000, 10, 31), False, False, True),
]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("build")
    work = root / "work"
    work.mkdir()
    rows = []
    for d, s, n, a in DAYS:
        chosen = "viirs_snpp" if s else "viirs_noaa20" if n else "modis_aqua"
        for sensor, ok in (("viirs_snpp", s), ("viirs_noaa20", n), ("modis_aqua", a)):
            rows.append({"utc_date": d, "sensor": sensor, "rows": 10, "ok": ok, "chosen": sensor == chosen, "source": "sp"})
    rows.append({"utc_date": date(2026, 1, 2), "sensor": "viirs_noaa20", "rows": 10, "ok": True, "chosen": True, "source": "nrt"})
    rows.append({"utc_date": date(2026, 1, 3), "sensor": "viirs_noaa20", "rows": 10, "ok": True, "chosen": True, "source": "nrt"})
    pl.DataFrame(rows).write_parquet(work / "days.parquet")
    pl.DataFrame({"sensor": ["viirs_noaa20"], "cell01": [_cell01(1.001, 2.001)]}).write_parquet(work / "static_mask.parquet")

    zips = root / "zips"
    write_zip(
        zips / "snpp.zip",
        {
            "a/A.csv": [
                viirs(10.1, 20.1, "2025-06-01", "0100"),
                viirs(10.1, 20.1, "2025-06-02", "0100", dn="N"),  # S-NPP not chosen on this date
                viirs(10.6, 20.6, "2025-06-03", "0100"),
                viirs(10.3, 20.3, "2025-06-01", "0100", typ=2),  # constant source
                viirs(-30.1, 150.1, "2025-06-30", "2000"),  # local solar date 2025-07-01
                viirs(-27.4, -58.8, "2025-06-03", "1500"),  # written before the earlier one
                viirs(-27.4, -58.8, "2025-06-01", "1500"),
            ]
        },
        VIIRS_HEAD,
    )
    write_zip(
        zips / "noaa20.zip",
        {
            "b/B.csv": [
                viirs(10.1, 20.1, "2025-06-02", "0200", sat="N20"),
                viirs(-30.1, 150.1, "2025-07-01", "0300", sat="N20"),
                viirs(10.1, 20.1, "2025-06-01", "0200", sat="N20"),  # S-NPP chosen on this date
            ]
        },
        VIIRS_HEAD,
    )
    write_zip(
        zips / "aqua.zip",
        {
            "c/C.csv": [
                modis(10.1, 20.1, "2025-06-01", "0500"),
                modis(10.1, 20.1, "2025-06-02", "0500"),
                modis(10.1, 20.1, "2000-10-30", "0500"),  # before SERIES_START: monthly only
                modis(10.1, 20.1, "2000-10-31", "2300"),  # local solar date 2000-11-01: in the series
            ]
        },
        MODIS_HEAD,
    )
    api = root / "api"
    write_api(
        api / "VIIRS_NOAA20_NRT" / "2026-01-01_5.csv",
        [
            viirs(1.001, 2.001, "2026-01-02", "0300", sat="N20"),  # in the mask
            viirs(3.001, 4.001, "2026-01-02", "0300", sat="N20"),
            viirs(3.001, 4.001, "2026-01-03", "0300", sat="N20"),  # after last_complete_date: published nowhere
        ],
    )
    build.run(zips, api, work)
    return work / "built"


def _rows(path, **kw):
    return pl.read_parquet(path, **kw)


def _series(built):
    return _rows(built / "series_monthly.parquet")


def test_series_uses_only_chosen_sensor(built):
    mon = _rows(built / "monthly.parquet")
    got = {(r["cell_id"], r["month"], r["sensor"]): (r["n_day"], r["n_night"]) for r in mon.to_dicts()}
    assert got[(C1, JUN, "viirs_snpp")] == (1, 1)  # includes the not chosen 06-02 row
    assert got[(C1, JUN, "viirs_noaa20")] == (2, 0)
    assert got[(C1, JUN, "modis_aqua")] == (2, 0)
    ser = {(r["cell_id"], r["month"], r["sensor"]): (r["n_day"], r["n_night"]) for r in _series(built).to_dicts()}
    assert ser[(C1, JUN, "viirs_snpp")] == (1, 0)
    assert ser[(C1, JUN, "viirs_noaa20")] == (1, 0)
    assert (C1, JUN, "modis_aqua") not in ser
    rows = pl.read_parquet(built / "rows" / "**" / "*.parquet")
    assert rows.filter(pl.col("acq_utc") == datetime(2025, 6, 2, 1, 0, tzinfo=UTC)).is_empty()
    assert rows.filter(pl.col("sensor") == "modis_aqua", pl.col("local_date") > date(2000, 11, 1)).is_empty()
    assert mon.columns == ["cell_id", "month", "sensor", "n_day", "n_night", "frp_mw"]
    assert mon.filter(pl.col("sensor") == "viirs_snpp", pl.col("cell_id") == C1)["frp_mw"][0] == pytest.approx(3.0)
    assert _series(built).columns == ["cell_id", "month", "sensor", "n_day", "n_night", "frp_day", "frp_night"]


def test_sums_agree(built):
    rep = json.loads((built / "build_report.json").read_text())
    assert rep["all_agree"]
    by = {(r["year"], r["sensor"]): r for r in rep["by_year_sensor"]}
    assert by[(2025, "viirs_snpp")]["series_monthly"] == by[(2025, "viirs_snpp")]["series_daily"] == by[(2025, "viirs_snpp")]["rows"] == 5
    assert by[(2025, "viirs_noaa20")]["rows"] == 2
    assert by[(2026, "viirs_noaa20")]["rows"] == 1
    # recompute from the files themselves
    ser = _series(built)
    assert ser.filter(pl.col("sensor") == "viirs_snpp").select((pl.col("n_day") + pl.col("n_night")).sum()).item() == 5
    daily = pl.read_parquet(built / "series_daily" / "**" / "*.parquet")
    total = pl.col("n_day") + pl.col("n_night")
    assert daily.select(total.sum()).item() == ser.select(total.sum()).item() == 9  # 5 + 2 + 1 + 1 (2000-11-01)


def test_mixed_month_sum_of_days(built):
    ser = _series(built).filter(pl.col("month") == JUL)
    assert sorted(ser["sensor"].to_list()) == ["viirs_noaa20", "viirs_snpp"]
    assert ser["n_day"].sum() == 2
    daily = pl.read_parquet(built / "series_daily" / "year=2025" / "part-0.parquet").filter(
        pl.col("cell_id") == C3
    )
    assert daily["local_date"].to_list() == [date(2025, 7, 1)] * 2
    assert daily["n_day"].sum() == ser["n_day"].sum()
    assert daily.columns == ["cell_id", "local_date", "sensor", "n_day", "n_night"]


def test_nrt_mask_applied(built):
    ser = _series(built).filter(pl.col("month") == JAN26)
    assert ser["cell_id"].to_list() == [_cid(3.001, 4.001)]  # the masked cell is gone
    mon = _rows(built / "monthly.parquet")
    assert _cid(1.001, 2.001) not in mon["cell_id"].to_list()
    assert _cid(10.3, 20.3) not in mon["cell_id"].to_list()  # SP row with type 2
    assert mon.filter(pl.col("month") == JAN26)["n_day"].sum() == 1  # the 01-03 tail row is not published


def test_pairs_only_common_ok_days(built):
    p = _rows(built / "pairs" / "modis_aqua__viirs_snpp.parquet")
    assert p.columns == ["cell_id", "month", "dn", "n_src", "n_dst"]
    got = {(r["cell_id"], r["month"], r["dn"]): (r["n_src"], r["n_dst"]) for r in p.to_dicts()}
    # 06-02 is low for S-NPP: neither the S-NPP night row nor the Aqua row of that date is counted
    assert got[(C1, JUN, "D")] == (1, 1)
    assert (C1, JUN, "N") not in got
    assert got[(C2, JUN, "D")] == (0, 1)
    assert got[(C3, JUL, "D")] == (0, 1)  # local month of the 06-30 row is July
    days = _rows(built / "pairs" / "modis_aqua__viirs_snpp__days.parquet")
    assert days.to_dicts() == [{"month": JUN, "n_days": 3}]  # 06-01, 06-03, 06-30 (UTC months)
    q = _rows(built / "pairs" / "viirs_noaa20__viirs_snpp.parquet")
    got = {(r["cell_id"], r["month"], r["dn"]): (r["n_src"], r["n_dst"]) for r in q.to_dicts()}
    assert got[(C1, JUN, "D")] == (1, 1)  # noaa20 06-01 row against snpp 06-01 row; 06-02 not paired
    assert _rows(built / "pairs" / "viirs_noaa20__viirs_snpp__days.parquet").to_dicts() == [{"month": JUN, "n_days": 2}]


def test_rows_sorted_and_tiled(built):
    p = built / "rows" / "year=2025" / "tile=-30_-60" / "part-0.parquet"
    df = _rows(p)
    assert df["acq_utc"].to_list() == [datetime(2025, 6, 1, 15, 0, tzinfo=UTC), datetime(2025, 6, 3, 15, 0, tzinfo=UTC)]
    assert df.columns == ["lat", "lon", "acq_utc", "local_date", "sensor", "frp_mw", "confidence", "daynight", "source"]
    assert df.schema["lat"] == pl.Float32 and df.schema["acq_utc"] == pl.Datetime("ms", "UTC")
    assert (built / "rows" / "year=2026" / "tile=0_0" / "part-0.parquet").exists()
    assert not (built / "_spill").exists()


def test_series_cut_at_last_complete_date(built):
    mon = _rows(built / "monthly.parquet")
    assert mon.filter(pl.col("month") == JAN26)["n_day"].sum() == 1  # the tail is cut from monthly too
    assert _series(built).filter(pl.col("month") == JAN26)["n_day"].sum() == 1
    daily = pl.read_parquet(built / "series_daily" / "**" / "*.parquet")
    rows = pl.read_parquet(built / "rows" / "**" / "*.parquet")
    assert daily["local_date"].max() <= date(2026, 1, 2) and rows["local_date"].max() <= date(2026, 1, 2)
    assert date(2026, 1, 3) not in daily["local_date"].to_list() + rows["local_date"].to_list()
    assert json.loads((built / "build_report.json").read_text())["all_agree"]


def test_series_starts_2000_11(built):
    mon = _rows(built / "monthly.parquet")
    assert mon.filter(pl.col("month") == grid.month_index(2000, 10), pl.col("sensor") == "modis_aqua")["n_day"].sum() == 1
    assert mon.filter(pl.col("month") == grid.month_index(2000, 11), pl.col("sensor") == "modis_aqua")["n_day"].sum() == 1
    daily = pl.read_parquet(built / "series_daily" / "**" / "*.parquet")
    assert daily["local_date"].min() == date(2000, 11, 1)
    assert _series(built)["month"].min() == grid.month_index(2000, 11)
    assert not (built / "series_daily" / "year=1999").exists()


def test_series_daily_sorted(built):
    df = pl.read_parquet(built / "series_daily" / "year=2025" / "part-0.parquet")
    assert df.equals(df.sort("local_date", "cell_id", "sensor"))
    assert df["local_date"].is_sorted()


def test_tail_detections_change_no_published_table(tmp_path):
    days = [
        {"utc_date": date(2026, 1, d), "sensor": "viirs_noaa20", "rows": 10, "ok": True, "chosen": d <= 3, "source": "nrt"}
        for d in (1, 2, 3, 4)
    ]
    head = [viirs(3.001, 4.001, "2026-01-02", "0300", sat="N20")]
    tail = [viirs(3.001, 4.001, "2026-01-03", "0300", sat="N20", dn="N"), viirs(5.001, 6.001, "2026-01-04", "0300", sat="N20")]
    files = {}
    for name, extra in (("a", []), ("b", tail)):
        work = tmp_path / name
        work.mkdir()
        pl.DataFrame(days).write_parquet(work / "days.parquet")
        pl.DataFrame({"sensor": [], "cell01": []}, schema={"sensor": pl.String, "cell01": pl.Int64}).write_parquet(work / "static_mask.parquet")
        api = tmp_path / f"api{name}"
        write_api(api / "VIIRS_NOAA20_NRT" / "2026-01-01_4.csv", head + extra)
        build.run(tmp_path / "nozips", api, work)
        built = work / "built"
        files[name] = {p.relative_to(built).as_posix(): p.read_bytes() for p in built.rglob("*.parquet")}
    assert files["a"] and files["a"] == files["b"]
