import json
import re

import pytest
import synth

from senda_pipeline import harmonize, publish


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    w = synth.write_work(tmp_path_factory.mktemp("pub"))
    harmonize.run(w)
    return w


def test_version_name_stable(work, tmp_path):
    a = publish.run(work, tmp_path / "one")
    b = publish.run(work, tmp_path / "two")
    assert a == b
    assert re.fullmatch(r"20251230-[0-9a-f]{12}", a)  # last chosen date 2025-12-31 minus one day


def test_version_changes_with_content(work, tmp_path):
    other = synth.write_work(tmp_path / "x", seed=5)
    harmonize.run(other)
    assert publish.run(other, tmp_path / "d1") != publish.run(work, tmp_path / "d2")


def test_manifest_written_last(work, tmp_path):
    version = publish.run(work, tmp_path)
    folder = tmp_path / "versions" / version
    times = {p: p.stat().st_mtime_ns for p in folder.rglob("*") if p.is_file()}
    manifest = folder / "manifest.json"
    assert times[manifest] >= max(t for p, t in times.items() if p != manifest)
    listed = set(json.loads(manifest.read_text())["files"])
    on_disk = {p.relative_to(folder).as_posix() for p in times} - {"manifest.json"}
    assert listed == on_disk


def test_only_the_published_files_are_copied(work, tmp_path):
    version = publish.run(work, tmp_path)
    folder = tmp_path / "versions" / version
    assert not (folder / "pairs").exists() and not (folder / "build_report.json").exists()
    for name in ("cells.parquet", "regions.parquet", "days.parquet", "monthly.parquet", "series_monthly.parquet", "factors.parquet", "cell_groups.parquet", "harmonization.json", "manifest.json"):
        assert (folder / name).exists(), name
    assert (folder / "series_daily" / "year=2020" / "part-0.parquet").exists()
    assert (folder / "rows" / "year=2020" / "tile=30_-60" / "part-0.parquet").exists()


def test_manifest_content(work, tmp_path):
    version = publish.run(work, tmp_path)
    folder = tmp_path / "versions" / version
    m = json.loads((folder / "manifest.json").read_text())
    assert m["version"] == version and m["last_complete_date"] == "2025-12-30"
    assert m["first_month"] == "2020-01"
    assert set(m["sensors"]) == {"modis_terra", "modis_aqua", "viirs_snpp", "viirs_noaa20"}
    assert m["sensors"]["viirs_snpp"]["first"] == "2012-01-20" and m["sensors"]["viirs_snpp"]["retired_at"] == "2026-11-02"
    assert m["sensors"]["modis_aqua"]["retired_at"] is None
    # the first month lacks its day before (2000-10-31), the last one is open
    assert m["incomplete_months"] == ["2000-11", "2025-12"] and m["gap_dates"] == []
    assert m["stats"]["outside_land"] == 0 and m["stats"]["series_monthly_rows"] == 48 and m["stats"]["cells"] == 256
    for rel, digest in m["files"].items():
        assert publish.sha256(folder / rel) == digest
    assert json.loads((folder / "harmonization.json").read_text())["version"] == version


def test_symlink_switch_atomic(work, tmp_path):
    first = publish.run(work, tmp_path)
    assert (tmp_path / "current").is_symlink() and (tmp_path / "current").resolve().name == first
    other = synth.write_work(tmp_path / "x", seed=7)
    harmonize.run(other)
    second = publish.run(other, tmp_path)
    assert second != first
    assert (tmp_path / "current").resolve().name == second
    assert (tmp_path / "versions" / first / "manifest.json").exists()  # the old version stays on disk
    assert not (tmp_path / ".current.tmp").exists()
    assert [p.name for p in (tmp_path / "versions").iterdir() if p.name.startswith(".")] == []


def test_publish_twice_keeps_one_folder(work, tmp_path):
    publish.run(work, tmp_path)
    publish.run(work, tmp_path)
    assert len(list((tmp_path / "versions").iterdir())) == 1


def test_missing_input_stops_before_anything_is_switched(work, tmp_path):
    broken = synth.write_work(tmp_path / "x")  # not harmonized: no factors
    with pytest.raises(FileNotFoundError):
        publish.run(broken, tmp_path / "data")
    assert not (tmp_path / "data" / "current").exists()
    assert list((tmp_path / "data" / "versions").iterdir()) == []


def test_current_must_not_be_a_real_folder(work, tmp_path):
    (tmp_path / "current").mkdir()
    with pytest.raises(SystemExit):
        publish.run(work, tmp_path)
    assert (tmp_path / "current").is_dir() and not (tmp_path / "current").is_symlink()


def test_same_content_is_up_to_date(work, tmp_path, capsys):
    a = publish.run(work, tmp_path)
    capsys.readouterr()
    b = publish.run(work, tmp_path)
    assert a == b and "up to date" in capsys.readouterr().out
    assert [p.name for p in (tmp_path / "versions").iterdir()] == [a]
    assert (tmp_path / "current").resolve().name == a


def test_prune_keeps_current_and_previous_only(work, tmp_path):
    other = synth.write_work(tmp_path / "x", seed=5)
    harmonize.run(other)
    third = synth.write_work(tmp_path / "y", seed=6)
    harmonize.run(third)
    root = tmp_path / "data"
    v1 = publish.run(work, root)
    v2 = publish.run(other, root)
    assert {p.name for p in (root / "versions").iterdir()} == {v1, v2}
    v3 = publish.run(third, root)
    assert {p.name for p in (root / "versions").iterdir()} == {v2, v3}
    assert (root / "current").resolve().name == v3


def test_prune_touches_only_version_folders_and_never_current(tmp_path):
    from senda_pipeline import config

    for name in ("20260101-aaaaaaaaaaaa", "20260102-bbbbbbbbbbbb", "notes", ".tmp-1"):
        (tmp_path / name).mkdir()
    config.prune_dirs(tmp_path, publish.VERSION_NAME, {"20260101-aaaaaaaaaaaa"})
    assert {p.name for p in tmp_path.iterdir()} == {"20260101-aaaaaaaaaaaa", "notes", ".tmp-1"}
