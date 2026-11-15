import json
import shutil
from datetime import date
from pathlib import Path

import polars as pl
from fixture_zips import viirs, write_api

from senda_pipeline import grid, scan

FIX = Path(__file__).parent / "fixtures" / "zips"


def _cell01(lat, lon):
    return pl.DataFrame({"a": [lat], "b": [lon]}).select(grid.cell01(pl.col("a"), pl.col("b")))["cell01"][0]


def _run(tmp_path, api=None):
    api_dir = tmp_path / "api"
    api_dir.mkdir(exist_ok=True)
    if api:
        api(api_dir)
    work = tmp_path / "work"
    scan.run(FIX, api_dir, work)
    return work


def _rows(work):
    df = pl.read_parquet(work / "days_raw.parquet")
    return {(r["utc_date"], r["sensor"], r["source"]): r["rows"] for r in df.to_dicts()}


def test_scan_counts(tmp_path):
    work = _run(tmp_path)
    # counted by hand from tests/fixture_zips.py (repeats, low confidence, N21, conf 29 and static rows excluded)
    assert _rows(work) == {
        (date(2025, 4, 1), "modis_terra", "sp"): 1,
        (date(2025, 3, 31), "viirs_snpp", "sp"): 1,
        (date(2025, 4, 1), "viirs_snpp", "sp"): 3,
        (date(2025, 4, 1), "modis_aqua", "sp"): 1,
        (date(2025, 4, 2), "modis_aqua", "sp"): 1,
    }
    st = pl.read_parquet(work / "static_counts.parquet")
    assert sorted(st.columns) == ["cell01", "n", "sensor", "year"]
    got = {(r["sensor"], r["year"], r["cell01"]): r["n"] for r in st.to_dicts()}
    assert got == {
        ("viirs_snpp", 2025, _cell01(11.001, 21.001)): 1,
        ("modis_aqua", 2025, _cell01(21.001, 41.001)): 1,
    }
    rep = json.loads((work / "scan_report.json").read_text())
    assert rep["rows_by_sensor"] == {"viirs_snpp": 4, "modis_aqua": 2, "modis_terra": 1}


def test_scan_prefers_sp_over_nrt(tmp_path):
    def api(d):
        write_api(
            d / "VIIRS_SNPP_NRT" / "2025-04-01_2.csv",
            [viirs(10.9, 20.9, "2025-04-01", "0500"), viirs(10.9, 20.9, "2025-04-02", "0500")],
        )

    rows = _rows(_run(tmp_path, api))
    assert (date(2025, 4, 1), "viirs_snpp", "nrt") not in rows  # SP has this date
    assert rows[(date(2025, 4, 1), "viirs_snpp", "sp")] == 3
    assert rows[(date(2025, 4, 2), "viirs_snpp", "nrt")] == 1  # no SP on this date


def test_scan_keeps_nrt_cells_for_mask(tmp_path):
    def api(d):
        write_api(d / "VIIRS_NOAA20_NRT" / "2026-01-01_5.csv", [viirs(1.001, 2.001, "2026-01-02", "0300", sat="N20")] * 2)
        write_api(d / "VIIRS_NOAA20_NRT" / "bad.csv", [])
        (d / "VIIRS_NOAA20_NRT" / "2026-01-06_5.csv").write_text("Invalid MAP_KEY.")

    work = _run(tmp_path, api)
    nc = pl.read_parquet(work / "nrt_cells.parquet")
    assert nc.to_dicts() == [
        {"utc_date": date(2026, 1, 2), "sensor": "viirs_noaa20", "cell01": _cell01(1.001, 2.001), "n": 1}
    ]  # exact repeat counted once; error text file skipped


def test_scan_cli_dispatch(tmp_path):
    data = tmp_path / "data"
    (data / "_work").mkdir(parents=True)
    shutil.copytree(FIX, data / "_work" / "zips")
    assert scan.main(["--data", str(data)]) == 0
    assert (data / "_work" / "days_raw.parquet").exists()
