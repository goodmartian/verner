import shutil

import fixture
import polars as pl
import pytest
from fastapi.testclient import TestClient

from senda_api.app import create_app
from senda_api.store import Store


def row(store, cell_id):
    return int(store.cells.row_of[cell_id])


def test_load_shapes(store):
    assert len(store.cells.cell_id) == 40
    assert store.H.shape[0] == 40
    assert store.months[0] == 36 and store.months[-1] == fixture.mi(2026, 11)
    assert set(store.RAW) == {"modis_terra", "modis_aqua", "viirs_snpp", "viirs_noaa20"}
    assert store.last_complete_date == fixture.LAST_COMPLETE
    assert store.cur_month == fixture.mi(2026, 11)


def test_h_equals_series_times_k(store, data_dir, ids):
    r = row(store, ids["a"])
    m = fixture.mi(2005, 7)
    series = pl.read_parquet(data_dir / "series_monthly.parquet").filter(
        (pl.col("cell_id") == ids["a"]) & (pl.col("month") == m)
    )
    assert series["sensor"].to_list() == ["modis_aqua"]
    assert (series["n_day"][0], series["n_night"][0]) == (10, 5)
    assert store.SER["modis_aqua"][r, m] == 15
    assert store.H[r, m] == pytest.approx(60.0)  # k = 4 for kgroup 1
    assert store.H[r, fixture.mi(2015, 7)] == pytest.approx(7.0)  # S-NPP, k = 1


def test_recent_window_used_from_2022(store, ids):
    r = row(store, ids["a"])
    assert store.H[r, fixture.mi(2022, 3)] == pytest.approx(30.0)  # 10 fires x recent k 3.0, era k would give 40


def test_conv_and_fallback_parts(store, ids):
    a, b = row(store, ids["a"]), row(store, ids["b"])
    m = fixture.mi(2005, 7)
    assert store.CONV[a, m] == pytest.approx(60.0)
    assert store.FALLBACK[a, m] == 0  # basis zone_month
    assert store.FALLBACK[b, m] == pytest.approx(30.0)  # kgroup 2: basis zone
    assert store.CONV[a, fixture.mi(2015, 7)] == 0


def test_k_lookup_is_one_for_reference(store):
    import numpy as np

    k, fb, miss = store.k_lookup("viirs_snpp", np.array([0, 1]), np.array([150, 151]), "D")
    assert k.tolist() == [1.0, 1.0] and not fb.any() and not miss.any()


def test_missing_factor_rejected(data_dir, tmp_path):
    copy = tmp_path / "v"
    shutil.copytree(data_dir, copy, ignore=shutil.ignore_patterns("rows"))
    f = pl.read_parquet(copy / "factors.parquet")
    f.filter(~((pl.col("sensor") == "modis_aqua") & (pl.col("kgroup") == 2) & (pl.col("window") == "era"))).write_parquet(
        copy / "factors.parquet"
    )
    with pytest.raises(ValueError, match="factor"):
        Store.load(copy)


def test_nonfinite_factor_rejected(data_dir, tmp_path):
    copy = tmp_path / "v"
    shutil.copytree(data_dir, copy, ignore=shutil.ignore_patterns("rows"))
    f = pl.read_parquet(copy / "factors.parquet")
    f.with_columns(k=pl.when(pl.col("sensor") == "viirs_noaa20").then(0.0).otherwise(pl.col("k"))).write_parquet(
        copy / "factors.parquet"
    )
    with pytest.raises(ValueError, match="factor"):
        Store.load(copy)


def test_base_years(store):
    assert store.base_years[0] == 2003 and store.base_years[-1] == 2025
    assert 2026 not in store.base_years
    assert 2008 in store.base_years  # a year with a gap month stays in the baseline


def test_meta_shape(client):
    res = client.get("/api/meta")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"data_version", "archive", "sensors", "gap_dates", "examples", "chat", "seam"}
    assert isinstance(body["chat"]["enabled"], bool)
    assert body["archive"] == {"first_month": "2003-01", "last_complete_date": "2026-11-12"}
    assert body["data_version"] == "test-1"
    assert {s["id"] for s in body["sensors"]} == {"modis_aqua", "viirs_snpp", "viirs_noaa20"}
    snpp = next(s for s in body["sensors"] if s["id"] == "viirs_snpp")
    assert set(snpp) == {"id", "name", "first", "last", "retired_at"}
    assert snpp["retired_at"] == "2026-11-02T13:00:00Z"
    assert [e["id"] for e in body["examples"]] == ["xa-2010-08"]  # only found events


def test_unknown_route_has_error_shape(client):
    res = client.get("/api/nope")
    assert res.status_code == 404
    assert set(res.json()) == {"error"} and set(res.json()["error"]) == {"code", "message"}


def test_unavailable_without_data():
    res = TestClient(create_app(store=None, load_on_start=False)).get("/api/meta")
    assert res.status_code == 503 and res.json()["error"]["code"] == "unavailable"


def test_archive_starts_at_the_first_month_of_the_version_and_the_baseline_at_2003(data_dir, tmp_path):
    import json

    copy = tmp_path / "v"
    shutil.copytree(data_dir, copy, ignore=shutil.ignore_patterns("rows"))
    manifest = json.loads((copy / "manifest.json").read_text())
    manifest["first_month"] = "2001-01"
    (copy / "manifest.json").write_text(json.dumps(manifest))
    early = Store.load(copy)
    assert early.first_month == 12 and early.base_years[0] == 2003


def test_events_file_is_optional(data_dir, tmp_path):
    copy = tmp_path / "v"
    shutil.copytree(data_dir, copy, ignore=shutil.ignore_patterns("rows"))
    (copy / "events.json").unlink()
    assert Store.load(copy).events == []
