from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from fixture_zips import MODIS_HEAD, VIIRS_HEAD, modis, viirs, write_api, write_zip

from senda_pipeline import grid, normalize

FIX = Path(__file__).parent / "fixtures" / "zips"


def _raw(rows: list[str], head: str = VIIRS_HEAD) -> pl.DataFrame:
    import io

    return pl.read_csv(io.StringIO("\n".join([head, *rows])), infer_schema_length=0)


def test_normalize_columns_and_types():
    df = normalize.normalize(_raw([viirs(10.1, 20.1, "2025-04-01", "0100")]), "sp")
    assert df.columns == normalize.NORM
    s = df.schema
    assert s["cell_id"] == pl.Int32 and s["cell01"] == pl.Int64 and s["type"] == pl.Int8
    assert s["acq_utc"] == pl.Datetime("ms", "UTC") and s["month"] == pl.Int16 and s["frp_mw"] == pl.Float32


def test_normalize_filters():
    rows = [
        modis(1.1, 1.1, "2025-04-01", "0916", conf=29),
        modis(1.2, 1.2, "2025-04-01", "0916", conf=30),
        modis(1.3, 1.3, "2025-04-01", "0916", sat="Terra", conf=90),
        modis(1.4, 1.4, "2025-04-01", "0916", sat="Terra", conf=29),
    ]
    out = normalize.normalize(_raw(rows, MODIS_HEAD), "sp").sort("lat")
    assert out["lat"].to_list() == [1.2, 1.3] and out["sensor"].to_list() == ["modis_aqua", "modis_terra"]
    assert out["confidence"].to_list() == ["30", "90"]
    rows = [
        viirs(2.1, 2.1, "2025-04-01", "0100", conf="l"),
        viirs(2.2, 2.2, "2025-04-01", "0100", conf="n"),
        viirs(2.3, 2.3, "2025-04-01", "0100", conf="high"),
        viirs(2.4, 2.4, "2025-04-01", "0100", sat="N21"),
        viirs(2.5, 2.5, "2025-04-01", "0100", sat="N20"),
    ]
    out = normalize.normalize(_raw(rows), "sp").sort("lat")
    assert out["lat"].to_list() == [2.2, 2.3, 2.5]
    assert out["confidence"].to_list() == ["n", "h", "n"]
    assert out["sensor"].to_list() == ["viirs_snpp", "viirs_snpp", "viirs_noaa20"]


def test_normalize_keeps_type():
    sp = normalize.normalize(_raw([viirs(3.1, 3.1, "2025-04-01", "0100", typ=2)]), "sp")
    assert sp["type"].to_list() == [2]
    nrt_raw = _raw([viirs(3.1, 3.1, "2025-04-01", "0100", typ=2)]).drop("type")
    nrt = normalize.normalize(nrt_raw, "nrt")
    assert nrt["type"].to_list() == [None] and nrt["source"].to_list() == ["nrt"]


def test_duplicates_counted_once():
    row = viirs(4.1, 4.1, "2025-04-01", "0100")
    out = normalize.normalize(_raw([row, row, viirs(4.1, 4.1, "2025-04-01", "0101")]), "sp")
    assert out.height == 2


def test_acq_time_without_leading_zeros_and_satellite_letters():
    # API answers: acq_time as a bare number, MODIS satellite A/T
    raw = _raw([modis(5.1, 5.1, "2025-04-01", 916, sat="A"), modis(5.2, 5.2, "2025-04-01", 5, sat="T")], MODIS_HEAD)
    out = normalize.normalize(raw, "nrt").sort("lat")
    assert out.height == 2
    assert out["acq_utc"][0] == datetime(2025, 4, 1, 9, 16, tzinfo=UTC)
    assert out["sensor"].to_list() == ["modis_aqua", "modis_terra"]
    raw = _raw([modis(5.1, 5.1, "2025-04-01", 5, sat="A")], MODIS_HEAD)
    assert normalize.normalize(raw, "nrt")["acq_utc"][0] == datetime(2025, 4, 1, 0, 5, tzinfo=UTC)


def test_bad_rows_dropped_not_fatal():
    rows = [viirs(95.0, 1.0, "2025-04-01", "0100"), viirs(6.1, 6.1, "2025-04-01", "2570"), viirs(6.2, 6.2, "bad", "0100")]
    assert normalize.normalize(_raw(rows), "sp").height == 0


def test_missing_required_column_named():
    with pytest.raises(ValueError, match="frp"):
        normalize.normalize(_raw([viirs(1, 1, "2025-04-01", "0100")]).drop("frp"), "sp")


def test_local_date_and_month_use_solar_time():
    out = normalize.normalize(_raw([viirs(-30.0, 150.0, "2025-03-31", "2000")]), "sp")
    assert out["utc_date"][0] == date(2025, 3, 31) and out["local_date"][0] == date(2025, 4, 1)
    assert out["month"][0] == grid.month_index(2025, 4)


def test_iter_zip_one_frame_per_country():
    frames = list(normalize.iter_zip(FIX / "viirs-snpp_2025_fixture.zip"))
    assert [f.height for f in frames] == [8, 1]


def test_read_api_csv_rejects_error_text(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Invalid MAP_KEY.")
    with pytest.raises(ValueError):
        normalize.read_api_csv(p)


def test_iter_normalized_api_window_and_sp_nrt(tmp_path):
    write_api(tmp_path / "VIIRS_SNPP_NRT" / "2025-04-01_2.csv",
              [viirs(7.1, 7.1, "2025-04-01", "0100"), viirs(7.2, 7.2, "2025-04-05", "0100")])
    write_zip(tmp_path / "z" / "a.zip", {"a/x.csv": [viirs(7.3, 7.3, "2025-04-01", "0100")]}, VIIRS_HEAD)
    out = list(normalize.iter_normalized(tmp_path / "z", tmp_path))
    assert [(g, s, f.height) for g, s, f in out] == [("a.zip", "sp", 1), ("VIIRS_SNPP_NRT", "nrt", 1)]


def test_overlapping_api_windows_are_refused(tmp_path):
    row = viirs(7.1, 7.1, "2025-04-01", "0100")
    write_api(tmp_path / "VIIRS_SNPP_NRT" / "2025-04-01_5.csv", [row])
    write_api(tmp_path / "VIIRS_SNPP_NRT" / "2025-04-01_1.csv", [row])
    with pytest.raises(ValueError, match="same day"):
        list(normalize.iter_normalized(tmp_path / "z", tmp_path))


def test_leftover_part_files_and_other_names_are_not_read(tmp_path):
    write_api(tmp_path / "VIIRS_SNPP_NRT" / "2025-04-01_2.csv", [viirs(7.1, 7.1, "2025-04-01", "0100")])
    write_api(tmp_path / "VIIRS_SNPP_NRT" / "2025-04-01_2.csv.123.part", [viirs(7.1, 7.1, "2025-04-01", "0100")])
    out = list(normalize.iter_normalized(tmp_path / "z", tmp_path))
    assert [f.height for _, _, f in out] == [1]


def test_a_run_without_the_yearly_archives_stops_at_once(tmp_path):
    # an empty folder, a folder that is not there, and a link that leads nowhere (the data copied to another machine)
    (tmp_path / "empty").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "gone")
    for zips in (tmp_path / "empty", tmp_path / "absent", tmp_path / "link"):
        with pytest.raises(SystemExit, match="no FIRMS archives"):
            normalize.require_archives(zips)
    normalize.require_archives(FIX)
