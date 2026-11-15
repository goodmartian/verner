import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pytest
from gfs_grib import Layout, message

from senda_pipeline import climate, config, gfs

NOW = datetime(2026, 11, 14, 8, 30, tzinfo=UTC)  # ERA5 has October by now, November comes about the 7th of December
FULL = (gfs.ROWS, gfs.COLS)


def fields(year: int, months: int):
    """What the reader says about one downloaded year: temperature = the month number in degC, rain 1 mm/day."""
    for month in range(1, months + 1):
        stamp = year * 10000 + month * 100 + 1
        yield "2t", stamp, np.full(FULL, 273.15 + month, np.float32)
        yield "tp", stamp, np.full(FULL, 0.001, np.float32)


def fake_reader(path: Path):
    parts = [int(x) for x in path.stem.split("-")]
    for year in range(parts[0], parts[-2] + 1 if len(parts) == 3 else parts[0] + 1):
        yield from fields(year, parts[-1] if year == parts[-2 if len(parts) == 3 else 0] else 12)


class FakeCds:
    def __init__(self, fail: dict[str, int] | None = None):
        self.submitted: list[str] = []
        self.polled: list[str] = []
        self.downloaded: list[str] = []
        self.fail = fail or {}

    def submit(self, chunk):
        self.submitted.append(chunk.key)
        return f"job-{chunk.key}"

    def status(self, job):
        self.polled.append(job)
        key = job.removeprefix("job-")
        if self.fail.get(key, 0) > 0:
            self.fail[key] -= 1
            return "failed"
        return "successful"

    def reason(self, job):
        return "boom"

    def download(self, job, dest):
        self.downloaded.append(job)
        dest.write_bytes(b"grib")


def no_sleep(_):
    pass


def decoded(arr, scale):
    return np.where(arr == -32768, np.nan, arr * scale)


def test_rain_is_metres_per_day_times_days_of_month():
    got = climate.convert("tp", 2020, 2, np.full(FULL, 0.001, np.float32))
    assert got is not None and got[0] == "rain_mm"
    assert np.allclose(got[3], 29.0)  # leap February: 0.001 m/day * 1000 * 29
    assert np.allclose(climate.convert("tp", 2021, 2, np.full(FULL, 0.001, np.float32))[3], 28.0)
    assert np.allclose(climate.convert("2t", 2021, 2, np.full(FULL, 300.15, np.float32))[3], 27.0)
    assert climate.convert("sp", 2021, 2, np.zeros(FULL, np.float32)) is None  # not ours


def test_normal_uses_only_its_years(tmp_path):
    def reader(_):
        for year, kelvin in [(1992, 200.0), (1993, 273.15 + 10), (2016, 273.15 + 20), (2017, 400.0)]:
            yield "2t", year * 10000 + 301, np.full(FULL, kelvin, np.float32)

    series, normals, newest = climate.assemble([tmp_path / "x"], (2017, 3), reader)
    assert newest == (2017, 3)
    assert np.allclose(decoded(normals["normal_temp_c"][2], 0.01), 15.0)  # mean of 1993 and 2016 only
    assert (normals["normal_temp_c"][0] == -32768).all()  # no January at all
    assert (normals["normal_rain_mm"] == -32768).all()
    assert series["temp_c"].shape == (climate.month_index(2017, 3) + 1, climate.ROWS, climate.COLS)
    assert np.allclose(decoded(series["temp_c"][climate.month_index(2017, 3)], 0.01), 400.0 - 273.15, atol=0.01)


def test_longitude_shift_and_thinning(tmp_path):
    # GRIB has longitudes 0 to 360; value = original column / 100
    values = np.tile(np.arange(gfs.COLS) / 100.0, (gfs.ROWS, 1))
    path = tmp_path / "a.grib"
    path.write_bytes(message(values, datetime(2020, 3, 1), Layout(north=90.0, west=0.0, step=0.25)))
    ((_, stamp, got),) = climate.read_grib(path)
    assert stamp == 20200301
    assert np.isclose(got[0, 0], 7.20, atol=0.01)  # column 0 is 180 W, which GRIB holds at column 720
    thin = climate.convert("2t", 2020, 3, got)[3] + np.float32(273.15)
    assert thin.shape == (climate.ROWS, climate.COLS) == (361, 720)
    assert np.isclose(thin[0, 1], 7.22, atol=0.01)  # every second node: shifted column 2
    assert np.isclose(thin[0, 360], 0.0, atol=0.01)  # 0 degrees east is the middle


def test_month_not_in_era5_stays_a_gap(tmp_path):
    def reader(_):
        yield from fields(2020, 2)

    series, _, newest = climate.assemble([tmp_path / "x"], (2020, 4), reader)
    assert newest == (2020, 2)
    for name in climate.VARIABLES:
        assert (series[name][climate.month_index(2020, 3) :] == -32768).all()
        assert (series[name][climate.month_index(2020, 2)] != -32768).all()


def test_fetch_resumes_without_downloading_done_chunks(tmp_path):
    cache = tmp_path / "era5"
    cache.mkdir()
    done, queued, fresh = climate.Chunk(1993, 12), climate.Chunk(1994, 12), climate.Chunk(1995, 12)
    (cache / done.file).write_bytes(b"ready")
    (cache / f"{queued.key}.job").write_text("job-earlier")  # submitted by an interrupted run
    cds = FakeCds()
    climate.fetch(cds, cache, [done, queued, fresh], no_sleep)
    assert cds.submitted == ["1995-12"]  # neither the finished year nor the one already in the queue
    assert sorted(cds.downloaded) == ["job-1995-12", "job-earlier"]
    assert (cache / done.file).read_bytes() == b"ready"
    assert not list(cache.glob("*.job"))


def test_fetch_submits_again_after_a_failed_job(tmp_path):
    chunk = climate.Chunk(1993, 12)
    cds = FakeCds(fail={"1993-12": 1})
    assert climate.fetch(cds, tmp_path, [chunk], no_sleep, log=lambda _: None) == []
    assert cds.submitted == ["1993-12", "1993-12"]


def test_one_lost_year_does_not_stop_the_others(tmp_path):
    chunks = [climate.Chunk(y, 12) for y in (1993, 1994, 1995)]
    cds = FakeCds(fail={"1994-12": 99})
    lines: list[str] = []
    lost = climate.fetch(cds, tmp_path, chunks, no_sleep, log=lines.append)
    assert lost == [chunks[1]]
    assert (tmp_path / "1993-12.grib").exists() and (tmp_path / "1995-12.grib").exists()
    assert any("1994-12: job failed: boom" in line for line in lines)  # the reason is in the log
    assert any("1994-12: given up" in line for line in lines)
    assert any("1993-12: downloaded" in line for line in lines)
    grouped = FakeCds(fail={"1993-1994-12": 99})  # the same in a run: the lost years are named, the rest is kept
    with pytest.raises(climate.CdsError, match="1993-1994"):
        climate.run(
            tmp_path / "d", now=datetime(1996, 2, 1, tzinfo=UTC), cds=grouped, reader=fake_reader, sleep=no_sleep
        )
    assert (tmp_path / "d" / "_work" / "era5" / "1995-12.grib").exists()


def test_full_cds_queue_is_not_a_failure_and_lowers_the_number_of_jobs(tmp_path):
    class Limited(FakeCds):
        """CDS accepts two jobs at a time and rejects the rest with its own text."""

        def __init__(self):
            super().__init__()
            self.open: set[str] = set()
            self.rejected = 0

        def submit(self, chunk):
            job = super().submit(chunk)
            if len(self.open) >= 2:
                self.rejected += 1
                return "rejected-" + job
            self.open.add(job)
            return job

        def status(self, job):
            if job.startswith("rejected-"):
                return "failed"
            self.open.discard(job)
            return "successful"

        def reason(self, job):
            return "Maximum number queued requests for this dataset has been reached. Please configure your scripts"

    chunks = [climate.Chunk(y, 12) for y in range(1993, 2003)]
    cds = Limited()
    assert climate.fetch(cds, tmp_path, chunks, no_sleep, log=lambda _: None) == []
    assert cds.rejected >= 1  # CDS did say no, and no year was lost for it
    assert all((tmp_path / c.file).exists() for c in chunks)


def test_fetch_stops_when_the_queue_takes_too_long(tmp_path):
    class Slow(FakeCds):
        def status(self, job):
            return "running"

    with pytest.raises(climate.CdsError, match="again"):
        climate.fetch(Slow(), tmp_path, [climate.Chunk(1993, 12)], no_sleep, poll=10, deadline=30)
    assert (tmp_path / "1993-12.job").exists()  # the next run picks the job up


def test_no_key_is_skipped_and_leaves_current_alone(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "copernicus_key", lambda: "")
    old = tmp_path / "climate" / "runs" / "2026-09"
    old.mkdir(parents=True)
    (tmp_path / "climate" / "current").symlink_to("runs/2026-09")
    assert climate.run(tmp_path, now=NOW).startswith("skipped")
    assert climate.main(["--data", str(tmp_path)]) == 0
    assert "skipped" in capsys.readouterr().out
    assert (tmp_path / "climate" / "current").resolve() == old.resolve()
    assert not (tmp_path / "_work").exists()


def test_run_builds_publishes_and_keeps_two(tmp_path, monkeypatch):
    monkeypatch.setattr(climate, "FIRST_MONTH", (2025, 1))
    monkeypatch.setattr(climate, "NORMAL_YEARS", (2024, 2025))
    cds = FakeCds()
    assert climate.run(tmp_path, now=NOW, cds=cds, reader=fake_reader) == "built"
    assert cds.submitted == ["2024-2025-12", "2026-10"]  # the missing years go in one request
    root = tmp_path / "climate"
    cur = root / "current"
    assert cur.is_symlink() and cur.resolve().name == "2026-10"
    meta = json.loads((cur / "meta.json").read_text())
    assert meta["grid"] == {"lat0": 90.0, "lon0": -180.0, "step": 0.5, "rows": 361, "cols": 720}
    assert meta["first_month"] == "2025-01" and meta["last_month"] == "2026-10" and meta["months"] == 22
    assert "Copernicus" in meta["attribution"]
    temp = np.load(cur / "temp_c.npy")
    assert temp.dtype == np.int16 and temp.shape == (22, 361, 720)
    assert np.allclose(decoded(temp[0], 0.01), 1.0) and np.allclose(decoded(temp[21], 0.01), 10.0)
    rain = np.load(cur / "rain_mm.npy")
    assert np.allclose(decoded(rain[1], 0.2), 28.0)  # February 2025
    normal = np.load(cur / "normal_rain_mm.npy")
    assert normal.shape == (12, 361, 720)
    assert np.allclose(decoded(normal[1], 0.2), 28.5, atol=0.2)  # February 2024 has 29 days, 2025 has 28
    # the same month again: nothing is fetched
    again = FakeCds()
    assert climate.run(tmp_path, now=NOW, cds=again, reader=fake_reader) == "up to date"
    assert not again.submitted
    # later months: only the year in progress is fetched again, and two runs are kept
    for day in (datetime(2026, 12, 10, tzinfo=UTC), datetime(2027, 1, 12, tzinfo=UTC)):
        step = FakeCds()
        assert climate.run(tmp_path, now=day, cds=step, reader=fake_reader) == "built"
    assert sorted(p.name for p in (root / "runs").iterdir()) == ["2026-11", "2026-12"]
    assert cur.resolve().name == "2026-12"
    assert not (tmp_path / "_work" / "era5" / "2026-10.grib").exists()


def test_cds_client_talks_rest(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("PRIVATE-TOKEN")))
        if request.method == "POST":
            body = json.loads(request.content)["inputs"]
            assert body["year"] == ["2020"] and body["month"] == ["01", "02"] and body["data_format"] == "grib"
            return httpx.Response(201, json={"jobID": "abc", "status": "accepted"})
        if request.url.path.endswith("/results"):
            return httpx.Response(200, json={"asset": {"value": {"href": "https://files.example/abc.grib"}}})
        if request.url.host == "files.example":
            return httpx.Response(200, content=b"GRIBDATA")
        return httpx.Response(200, json={"status": "successful"})

    cds = climate.Cds("secret-token", httpx.Client(transport=httpx.MockTransport(handler)))
    assert cds.submit(climate.Chunk(2020, 2)) == "abc"
    assert cds.status("abc") == "successful"
    dest = tmp_path / "a.grib"
    cds.download("abc", dest)
    assert dest.read_bytes() == b"GRIBDATA" and not dest.with_suffix(".part").exists()
    assert all(
        token == ("secret-token" if host != "files.example" else None) for host, token in seen
    )  # token stays with CDS


def test_cds_errors_do_not_leak_the_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403 if request.method == "POST" else 404)

    cds = climate.Cds("secret-token", httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(climate.CdsError, match="licence") as e:
        cds.submit(climate.Chunk(2020, 1))
    assert "secret-token" not in str(e.value)
    assert cds.status("gone") == "failed"


def test_plan_groups_missing_years_and_keeps_cached_ones(tmp_path):
    chunks = climate.plan(NOW)
    assert chunks[0] == climate.Chunk(1993, 12, 2001) and chunks[1] == climate.Chunk(2002, 12, 2010)
    assert chunks[-1] == climate.Chunk(2026, 10)
    assert sum(c.last_year - c.year + 1 for c in chunks) == 2026 - 1993 + 1
    for name in ("1993-12.grib", "1994-12.grib", "2000-2002-12.grib", "2026-09.grib"):
        (tmp_path / name).write_bytes(b"x")
    got = climate.plan(NOW, tmp_path)
    assert got[:3] == [climate.Chunk(1993, 12), climate.Chunk(1994, 12), climate.Chunk(1995, 12, 1999)]
    assert climate.Chunk(2000, 12, 2002) in got and climate.Chunk(2003, 12, 2011) in got
    assert sum(c.last_year - c.year + 1 for c in got) == 2026 - 1993 + 1
    assert got[-1] == climate.Chunk(2026, 10)  # the year in progress is never taken from a shorter file


def test_request_for_several_years_names_them_all():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content)["inputs"])
        return httpx.Response(201, json={"jobID": "j"})

    cds = climate.Cds("k", httpx.Client(transport=httpx.MockTransport(handler)))
    cds.submit(climate.Chunk(2007, 12, 2009))
    assert seen["year"] == ["2007", "2008", "2009"] and len(seen["month"]) == 12


def test_a_waiting_run_reports_and_a_bad_answer_is_logged(tmp_path):
    lines: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    cds = climate.Cds("k", httpx.Client(transport=httpx.MockTransport(handler)), log=lines.append)
    assert cds.status("abc") == "running"
    assert any("HTTP 429" in line for line in lines)

    class Waiting(FakeCds):
        calls = 0

        def status(self, job):
            self.calls += 1
            return "running" if self.calls < 30 else "successful"

    said: list[str] = []
    climate.fetch(Waiting(), tmp_path, [climate.Chunk(1993, 12)], no_sleep, poll=60, log=said.append)
    waits = [line for line in said if line.startswith("waiting")]
    assert 4 <= len(waits) <= 6  # about every five minutes of 29 minutes, not every poll
    assert "1993-12 running" in waits[0]


def test_last_data_month_is_the_newest_month_with_every_variable(tmp_path):
    def reader(_):
        yield from fields(2020, 3)
        yield "2t", 20200401, np.full(FULL, 280.0, np.float32)  # April: temperature published, rain not yet

    series, _, newest = climate.assemble([tmp_path / "x"], (2020, 4), reader)
    assert newest == (2020, 4)
    assert climate.last_with_data(series) == (2020, 3)
    assert climate.last_with_data({n: a[:0] for n, a in series.items()}) is None
