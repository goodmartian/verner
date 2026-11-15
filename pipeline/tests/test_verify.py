import json
import shutil
from datetime import date

import polars as pl
import pytest
import synth

from senda_pipeline import harmonize, publish, verify


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    root = tmp_path_factory.mktemp("ver")
    work = synth.write_work(root)
    harmonize.run(work)
    publish.run(work, root / "data")
    return root / "data"


@pytest.fixture
def data(base, tmp_path):
    """A private copy of the published data root, safe to break."""
    out = tmp_path / "data"
    shutil.copytree(base, out, symlinks=True)
    return out


def vdir(data):
    return data / "current"


def rehash(folder):
    """Recompute the manifest hashes so that only the intended damage is left."""
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["files"] = {
        p.relative_to(folder).as_posix(): publish.sha256(p) for p in sorted(folder.rglob("*")) if p.is_file() and p.name != "manifest.json"
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))


def edit_manifest(folder, **changes):
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest.update(changes)
    (folder / "manifest.json").write_text(json.dumps(manifest))


def test_verify_ok_on_fixture(data):
    assert verify.run(vdir(data)) == []


def test_verify_catches_sum_mismatch(data):
    f = vdir(data) / "series_daily" / "year=2020" / "part-0.parquet"
    df = pl.read_parquet(f)
    df.with_columns(pl.when(pl.int_range(pl.len()) == 0).then(pl.col("n_day") + 1).otherwise(pl.col("n_day")).alias("n_day")).write_parquet(f)
    rehash(vdir(data))
    problems = verify.run(vdir(data))
    assert len(problems) == 1 and "series sums differ in 2020" in problems[0]


def test_verify_catches_two_chosen(data):
    f = vdir(data) / "days.parquet"
    days = pl.read_parquet(f)
    days.with_columns(pl.when(pl.col("utc_date") == date(2020, 5, 5)).then(True).otherwise(pl.col("chosen")).alias("chosen")).write_parquet(f)
    rehash(vdir(data))
    problems = verify.run(vdir(data))
    assert any("more than one chosen" in p for p in problems)


def test_verify_catches_a_changed_file(data):
    f = vdir(data) / "cells.parquet"
    f.write_bytes(f.read_bytes() + b"x")
    assert any("sha256 of cells.parquet" in p for p in verify.run(vdir(data)))


def test_verify_catches_a_file_missing_from_the_manifest(data):
    shutil.copyfile(vdir(data) / "cells.parquet", vdir(data) / "stray.parquet")
    assert any("stray.parquet is not in the manifest" in p for p in verify.run(vdir(data)))


def test_verify_catches_wrong_schema(data):
    f = vdir(data) / "cells.parquet"
    pl.read_parquet(f).with_columns(pl.col("lat").cast(pl.Float64)).write_parquet(f)
    rehash(vdir(data))
    assert any(p.startswith("schema cells.parquet") for p in verify.run(vdir(data)))


def test_verify_catches_incomplete_factors(data):
    f = vdir(data) / "factors.parquet"
    pl.read_parquet(f).filter(~((pl.col("kgroup") == 0) & (pl.col("calmonth") == 3) & (pl.col("sensor") == "viirs_noaa20"))).write_parquet(f)
    rehash(vdir(data))
    problems = verify.run(vdir(data))
    assert any("lack a complete factor set for viirs_noaa20 era" in p for p in problems)


def test_verify_catches_non_positive_k(data):
    f = vdir(data) / "factors.parquet"
    pl.read_parquet(f).with_columns(pl.when(pl.int_range(pl.len()) == 0).then(0.0).otherwise(pl.col("k")).cast(pl.Float32).alias("k")).write_parquet(f)
    rehash(vdir(data))
    assert any("non positive k" in p for p in verify.run(vdir(data)))


def test_verify_catches_cells_without_a_group(data):
    f = vdir(data) / "cell_groups.parquet"
    pl.read_parquet(f).head(10).write_parquet(f)
    rehash(vdir(data))
    assert any("have no kgroup" in p for p in verify.run(vdir(data)))


def test_verify_catches_outside_land(data):
    f = vdir(data) / "series_monthly.parquet"
    df = pl.read_parquet(f)
    pl.concat([df, df.head(1).with_columns(pl.lit(999_999).cast(pl.Int32).alias("cell_id"))]).write_parquet(f)
    rehash(vdir(data))
    problems = verify.run(vdir(data))
    assert any("outside cells.parquet" in p for p in problems) and any("stats.outside_land" in p for p in problems)


def test_verify_catches_wrong_incomplete_months(data):
    edit_manifest(vdir(data), incomplete_months=[])
    assert any("incomplete_months differ" in p for p in verify.run(vdir(data)))


def test_verify_catches_a_gap_the_manifest_does_not_know(data):
    f = vdir(data) / "days.parquet"
    days = pl.read_parquet(f)
    days.with_columns(pl.when(pl.col("utc_date") == date(2020, 5, 5)).then(False).otherwise(pl.col("chosen")).alias("chosen")).write_parquet(f)
    rehash(vdir(data))
    problems = verify.run(vdir(data))
    assert any("incomplete_months differ" in p and "2020-05" in p for p in problems)
    assert any("gap_dates differ" in p for p in problems)


def test_verify_catches_a_broken_ladder(data):
    f = vdir(data) / "harmonization.json"
    h = json.loads(f.read_text())
    h["ladder"] = h["ladder"][:5]
    f.write_text(json.dumps(h))
    rehash(vdir(data))
    assert any("ladder levels" in p for p in verify.run(vdir(data)))


def test_verify_without_manifest(data):
    (vdir(data) / "manifest.json").unlink()
    assert verify.run(vdir(data)) == ["manifest.json is missing: the version was not completed"]


def test_cli_exit_code(data, capsys):
    assert verify.main(["--data", str(data)]) == 0
    assert capsys.readouterr().out.startswith("ok")
    edit_manifest(vdir(data), incomplete_months=[])
    assert verify.main(["--data", str(data)]) == 1
    assert "incomplete_months differ" in capsys.readouterr().err


def test_verify_allows_events_outside_manifest(data):
    ev = [{"id": "a", "region_id": "AA", "month": "2020-01", "found": True}]
    (vdir(data) / "events.json").write_text(json.dumps(ev))
    assert verify.run(vdir(data)) == []


def test_verify_allows_the_ready_mark_of_an_earlier_run(data):
    (vdir(data) / verify.READY_FILE).touch()
    assert verify.run(vdir(data)) == []


def test_verify_rejects_broken_events(data):
    (vdir(data) / "events.json").write_text(json.dumps([{"id": "a"}]))
    assert any("events.json must be a list" in p for p in verify.run(vdir(data)))
    (vdir(data) / "events.json").write_text("{")
    assert any("not valid JSON" in p for p in verify.run(vdir(data)))


def test_verify_rejects_unknown_extra_file(data):
    (vdir(data) / "other.json").write_text("[]")
    assert any("other.json is not in the manifest" in p for p in verify.run(vdir(data)))


def _forecast_files(folder, version, use=None, rows=None):
    doc = {k: {} for k in verify.FORECAST_KEYS}
    doc.update(version=version, method_default="climatology", use_model=use or {}, model={"horizons": [2, 3, 4, 5, 6, 7]}, model_horizons={r: sum(v) for r, v in (use or {}).items()})
    (folder / "forecast.json").write_text(json.dumps(doc))
    cols = {"region_id": pl.String, "month": pl.String, "horizon": pl.Int8, "p10": pl.Float32, "p50": pl.Float32,
            "p90": pl.Float32, "method": pl.String, "err_pct": pl.Float32}  # fmt: skip
    pl.DataFrame(rows or [], schema=cols).write_parquet(folder / "forecast.parquet")


def test_verify_allows_a_forecast_of_this_version(data):
    version = json.loads((vdir(data) / "manifest.json").read_text())["version"]
    row = {"region_id": "AA", "month": "2027-01", "horizon": 2, "p10": 1.0, "p50": 2.0, "p90": 3.0, "method": "model", "err_pct": 9.0}
    _forecast_files(vdir(data), version, {"AA": [True, False, False, False, False, False]}, [row])
    assert verify.run(vdir(data)) == []


def test_verify_rejects_a_forecast_of_another_version_or_with_odd_rows(data):
    folder = vdir(data)
    _forecast_files(folder, "20200101-000000000000")
    assert any("another version" in p for p in verify.run(folder))
    version = json.loads((folder / "manifest.json").read_text())["version"]
    _forecast_files(folder, version, {"AA": [True] * 6})  # use_model says rows, the table has none
    assert any("differ from use_model" in p for p in verify.run(folder))
    _forecast_files(folder, version, {"AA": [True, False, True, False, False, False]})  # a gap in the model horizons
    assert any("not a prefix" in p for p in verify.run(folder))
    (folder / "forecast.parquet").unlink()
    assert any("forecast.parquet is missing" in p for p in verify.run(folder))
