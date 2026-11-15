import json
import os
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

import numpy as np
import pytest
from gfs_grib import Layout, message

from senda_pipeline import gfs, weather

NOW = datetime(2026, 11, 14, 8, 30, tzinfo=UTC)  # latest cycle is 06Z when lead 24 of it is published
LATEST = datetime(2026, 11, 14, 6, tzinfo=UTC)

IDX_REAL = """\
14:6400384:d=2026111318:GUST:surface:3 hour fcst:
106:76557654:d=2026111318:TMP:2 mb:3 hour fcst:
581:406716082:d=2026111318:TMP:2 m above ground:3 hour fcst:
584:409711194:d=2026111318:RH:2 m above ground:3 hour fcst:
588:412765231:d=2026111318:UGRD:10 m above ground:3 hour fcst:
589:413726410:d=2026111318:VGRD:10 m above ground:3 hour fcst:
596:417897722:d=2026111318:APCP:surface:6-9 hour acc fcst:
597:418207208:d=2026111318:APCP:surface:0-9 hour acc fcst:
598:418500000:d=2026111318:CAPE:surface:9 hour fcst:
"""


def test_parse_idx_and_spans():
    msgs = gfs.parse_idx(IDX_REAL)
    assert msgs[0].end == 76557654 and msgs[-1].end is None
    # the last message is not asked for, so a missing end is not met
    got = gfs.spans(msgs, 9)
    assert got["tmp"] == (406716082, 409711194 - 406716082)  # "2 m above ground", not "2 mb"
    assert got["gust"] == (6400384, 76557654 - 6400384)
    assert got["apcp"] == (417897722, 418207208 - 417897722)  # bucket 6-9, not the 0-9 total
    assert gfs.spans(msgs, 9, only={"ugrd"}) == {"ugrd": (412765231, 413726410 - 412765231)}
    with pytest.raises(ValueError, match="APCP"):
        gfs.spans(msgs, 12, only={"apcp"})  # no 6-12 bucket in this file


def test_rain_buckets():
    assert [gfs.rain_bucket(n) for n in (3, 6, 9, 12, 24)] == [
        "0-3 hour acc fcst", "0-6 hour acc fcst", "6-9 hour acc fcst", "6-12 hour acc fcst", "18-24 hour acc fcst",
    ]  # fmt: skip


def test_object_url_and_cycle():
    assert gfs.cycle_of(datetime(2026, 11, 14, 8, 30, tzinfo=UTC)) == LATEST
    assert gfs.object_url(LATEST, 3).endswith("/gfs.20261114/06/atmos/gfs.t06z.pgrb2.0p25.f003")


def test_decode_shifts_longitude_and_keeps_north_first():
    values = np.zeros((721, 1440))
    values[0, 0] = 5.0  # 90 N, 0 E
    values[360, 0] = 7.0  # equator, 0 E
    values[360, 1] = 8.0  # equator, 0.25 E
    values[400, 720] = 9.0  # 10 S, 180 E in GFS longitudes
    msg = message(values, LATEST, Layout(north=90.0, west=0.0, step=0.25), decimal=1)
    out = gfs.decode(msg)
    assert out.shape == (721, 1440) and out.dtype == np.float32
    assert out[360, 720] == pytest.approx(7.0)  # 0 E lands in column 720
    assert out[360, 721] == pytest.approx(8.0)
    assert out[0, 720] == pytest.approx(5.0)  # row 0 stays 90 N
    assert out[400, 0] == pytest.approx(9.0)  # 180 E -> column 0 (180 W)


# ---- a fake bucket: idx text and byte ranges served from memory --------------------------------------------

class FakeFetcher:
    def __init__(self, cycles, down=False):
        self.newest, self.down, self.ranges = max(cycles, default=None), down, []

    def _parse(self, url):
        cyc = datetime.strptime(url.split("gfs.")[1][:8] + url.split("/")[-3], "%Y%m%d%H").replace(tzinfo=UTC)
        return cyc, int(url.split(".f")[-1].split(".")[0])

    def _lines(self, lead):
        steps = [(n, lv, f"{lead} hour fcst") for n, lv in gfs.MESSAGES.values() if n != "APCP"]
        steps.insert(1, ("TMP", "2 mb", f"{lead} hour fcst"))
        s = (lead - 1) // 6 * 6
        steps += [("APCP", "surface", f"{s}-{lead} hour acc fcst"), ("APCP", "surface", f"0-{lead} hour acc fcst")]
        return steps

    def get_text(self, url):
        if self.down:
            raise gfs.FetchError("network error: ConnectError")
        cyc, lead = self._parse(url)
        if self.newest is None or cyc > self.newest:  # published: the newest cycle and every older one
            raise gfs.FetchError("HTTP 404", 404)
        return "\n".join(
            f"{i + 1}:{i * 100}:d={cyc:%Y%m%d%H}:{n}:{lv}:{st}:" for i, (n, lv, st) in enumerate(self._lines(lead))
        ) + f"\n{len(self._lines(lead)) + 1}:{len(self._lines(lead)) * 100}:d=x:LAST:surface:x:\n"

    def get_range(self, url, start, length):
        cyc, lead = self._parse(url)
        self.ranges.append((cyc, lead, start))
        assert length == 100
        n, lv, st = self._lines(lead)[start // 100]
        return f"{n}|{lv}|{st}|{lead}".encode()


def fake_decode(raw: bytes) -> np.ndarray:
    n, _, st, lead = raw.decode().split("|")
    lead = int(lead)
    value = {"UGRD": lead, "VGRD": -lead, "GUST": 2 * lead, "TMP": 283.15, "RH": 50.0}.get(n)
    if n == "APCP":  # 1 mm per hour everywhere, except the 6 h bucket of lead 6 holds 9 mm
        a, b = st.split(" ")[0].split("-")
        value = 9.0 if (a, b) == ("0", "6") else (int(b) - int(a)) * 1.0
    return np.full((721, 1440), value, dtype=np.float32)


def build(tmp_path, now=NOW, cycles=(LATEST,), fetcher=None):
    f = fetcher or FakeFetcher(cycles)
    return weather.run(tmp_path, now=now, fetcher=f, decoder=fake_decode), f


def test_plan_order_and_analysis_boundary():
    slots = weather.plan(LATEST)
    assert len(slots) == 33
    assert slots[0].time == LATEST - timedelta(hours=72) and slots[-1].time == LATEST + timedelta(hours=24)
    assert all(b.time - a.time == timedelta(hours=3) for a, b in pairwise(slots))
    assert [s.lead for s in slots[:25]] == [6, 3] * 12 + [6]  # past: leads 3 and 6 of the previous cycles
    assert slots[24].time == LATEST and slots[24].cycle == LATEST - timedelta(hours=6)
    assert [s.lead for s in slots[25:]] == [3, 6, 9, 12, 15, 18, 21, 24]
    assert all(s.cycle == LATEST for s in slots[25:])


def test_build_writes_contract(tmp_path):
    out, _ = build(tmp_path)
    assert out == "built"
    cur = tmp_path / "weather" / "current"
    assert cur.is_symlink() and os.readlink(cur) == "runs/20261114T06Z"
    meta = json.loads((cur / "meta.json").read_text())
    assert meta["run_id"] == "20261114T06Z" and meta["analysis_until"] == "2026-11-14T06:00:00Z"
    assert meta["grid"] == {"lat0": 90.0, "lon0": -180.0, "step": 0.25, "rows": 721, "cols": 1440}
    assert meta["times"][0] == "2026-11-11T06:00:00Z" and meta["times"][-1] == "2026-11-15T06:00:00Z"
    assert meta["times"] == sorted(meta["times"]) and len(meta["times"]) == 33
    assert set(meta["variables"]) == {"wind_u", "wind_v", "gust", "temp_c", "rh", "precip"}
    assert meta["variables"]["wind_u"] == {"units": "m/s", "scale": 0.01, "file": "wind_u.npy"}
    u = np.load(cur / "wind_u.npy", mmap_mode="r")
    assert u.dtype == np.int16 and u.shape == (33, 721, 1440)
    leads = [6, 3] * 12 + [6, 3, 6, 9, 12, 15, 18, 21, 24]
    assert [int(u[i, 0, 0]) for i in range(33)] == [lead * 100 for lead in leads]  # value / scale
    t = np.load(cur / "temp_c.npy", mmap_mode="r")
    assert int(t[0, 5, 5]) == 1000  # 283.15 K = 10 C at scale 0.01
    assert int(np.load(cur / "rh.npy", mmap_mode="r")[0, 0, 0]) == 500


def test_precip_is_mm_per_hour_of_the_step(tmp_path):
    build(tmp_path)
    p = np.load(tmp_path / "weather" / "current" / "precip.npy", mmap_mode="r")
    leads = [6, 3] * 12 + [6, 3, 6, 9, 12, 15, 18, 21, 24]
    # 3 h buckets are 3 mm -> 1 mm/h; lead 6 is a 9 mm 6 h bucket minus the 3 mm of lead 3 -> 2 mm/h
    expect = {3: 100, 6: 200, 9: 100, 12: 100, 15: 100, 18: 100, 21: 100, 24: 100}
    # leads 12, 18, 24 are 6 h buckets of 6 mm minus 3 mm of the lead before: 1 mm/h
    assert [int(p[i, 3, 3]) for i in range(33)] == [expect[lead] for lead in leads]


def test_encode_missing_and_scale():
    out = weather.encode(np.array([np.nan, 1.234, -400.0]), 0.01)
    assert out.dtype == np.int16 and out.tolist() == [-32768, 123, -32767]


def test_skipped_when_network_is_down_keeps_current(tmp_path):
    build(tmp_path)
    before = os.readlink(tmp_path / "weather" / "current")
    out, _ = build(tmp_path, fetcher=FakeFetcher([], down=True))
    assert out.startswith("skipped")
    assert os.readlink(tmp_path / "weather" / "current") == before


def test_skipped_when_no_cycle_is_published(tmp_path):
    out, _ = build(tmp_path, cycles=())
    assert out.startswith("skipped") and not (tmp_path / "weather").exists()


def test_falls_back_to_previous_cycle(tmp_path):
    old = LATEST - timedelta(hours=6)
    out, _ = build(tmp_path, cycles=(old,))
    assert out == "built" and os.readlink(tmp_path / "weather" / "current") == "runs/20261114T00Z"


def test_second_run_fetches_only_new_and_keeps_two_runs(tmp_path):
    _, f1 = build(tmp_path)
    n1 = len(f1.ranges)
    assert n1 == 33 * 6 + 1  # every lead, plus the rain of lead 3 of the cycle before the window
    _, f1b = build(tmp_path)  # same cycle: nothing to fetch
    assert f1b.ranges == []
    nxt = LATEST + timedelta(hours=6)
    _, f2 = build(tmp_path, now=nxt + timedelta(hours=2), cycles=(LATEST, nxt))
    assert len(f2.ranges) == 8 * 6 and {c for c, _, _ in f2.ranges} == {nxt}  # leads up to 6 of earlier cycles are cached
    build(tmp_path, now=nxt + timedelta(hours=8), cycles=(LATEST, nxt, nxt + timedelta(hours=6)))
    runs = sorted(p.name for p in (tmp_path / "weather" / "runs").iterdir())
    assert runs == ["20261114T12Z", "20261114T18Z"]
    assert os.readlink(tmp_path / "weather" / "current") == "runs/20261114T18Z"
    leftovers = [p.name for p in (tmp_path / "weather").iterdir()]
    assert sorted(leftovers) == ["current", "runs"]  # no temporary links


def test_swap_current_is_replace_of_a_link(tmp_path):
    (tmp_path / "runs" / "a").mkdir(parents=True)
    (tmp_path / "runs" / "b").mkdir()
    weather.swap_current(tmp_path, "a")
    weather.swap_current(tmp_path, "b")
    assert os.readlink(tmp_path / "current") == "runs/b" and (tmp_path / "current").resolve().name == "b"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["current", "runs"]


def test_window_covers_the_first_day_of_the_fire_window():
    last_complete = date(2026, 11, 12)  # fires show 11-10 .. 11-12
    start = weather.window_start(datetime(2026, 11, 14, 6, tzinfo=UTC), last_complete)
    assert start == datetime(2026, 11, 9, tzinfo=UTC) <= datetime(2026, 11, 10, tzinfo=UTC)
    slots = weather.plan(datetime(2026, 11, 14, 6, tzinfo=UTC), start)
    assert slots[0].time == start and slots[-1].time == datetime(2026, 11, 15, 6, tzinfo=UTC)
    assert all(b.time - a.time == timedelta(hours=3) for a, b in pairwise(slots))


def test_window_falls_back_and_is_capped():
    latest = datetime(2026, 11, 14, 6, tzinfo=UTC)
    assert weather.window_start(latest, None) == latest - timedelta(hours=72)
    assert weather.window_start(latest, date(2026, 11, 14)) == datetime(2026, 11, 11, tzinfo=UTC)
    assert weather.window_start(latest, date(2026, 11, 20)) == latest - timedelta(hours=72)  # never shorter
    assert weather.window_start(latest, date(2026, 1, 1)) == latest - weather.MAX_PAST


def test_run_reads_the_start_from_published_data_and_extends_an_old_run(tmp_path):
    assert build(tmp_path)[0] == "built"  # no data version: 72 h
    meta = tmp_path / "weather" / "current" / "meta.json"
    assert json.loads(meta.read_text())["times"][0] == weather.iso(LATEST - timedelta(hours=72))
    (tmp_path / "current").mkdir()
    (tmp_path / "current" / "manifest.json").write_text(json.dumps({"last_complete_date": "2026-11-12"}))
    res, f = build(tmp_path)
    assert res == "built"  # the earlier run began too late for the fire window
    times = json.loads(meta.read_text())["times"]
    assert times[0] == "2026-11-09T00:00:00Z" and len(f.ranges) > 0
    assert build(tmp_path)[0] == "up to date"
