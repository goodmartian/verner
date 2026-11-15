from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from senda_pipeline.firms_api import Budget, Request, fetch_one, plan_requests

FIX = Path(__file__).parent / "fixtures" / "api"
KEY = "SECRETKEY0123456789"
REQ = Request("MODIS_SP", date(2026, 1, 1), 5)


def avail():
    return {
        "VIIRS_NOAA20_SP": (date(2018, 4, 1), date(2026, 8, 31)),
        "VIIRS_NOAA20_NRT": (date(2026, 8, 1), date(2026, 11, 14)),
        "VIIRS_SNPP_SP": (date(2012, 1, 20), date(2026, 8, 31)),
        "VIIRS_SNPP_NRT": (date(2026, 8, 1), date(2026, 11, 14)),
        "MODIS_SP": (date(2000, 11, 1), date(2026, 8, 31)),
        "MODIS_NRT": (date(2026, 8, 1), date(2026, 11, 14)),
    }


def days_of(reqs):
    out = []
    for r in reqs:
        assert 1 <= r.days <= 5
        out += [r.start + timedelta(d) for d in range(r.days)]
    return out


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_plan_splits_sp_and_nrt():
    reqs = plan_requests(avail(), date(2026, 11, 14), 2026)
    sp = days_of([r for r in reqs if r.source == "MODIS_SP"])
    nrt = days_of([r for r in reqs if r.source == "MODIS_NRT"])
    assert sp == [date(2026, 1, 1) + timedelta(d) for d in range((date(2026, 8, 31) - date(2026, 1, 1)).days + 1)]
    assert nrt == [date(2026, 9, 1) + timedelta(d) for d in range((date(2026, 11, 14) - date(2026, 9, 1)).days + 1)]
    assert reqs[0].source == "VIIRS_SNPP_SP"


def test_plan_stops_snpp_at_retirement():
    reqs = plan_requests(avail(), date(2026, 11, 14), 2026)
    snpp = days_of([r for r in reqs if r.source.startswith("VIIRS_SNPP")])
    assert snpp and max(snpp) == date(2026, 11, 2)
    assert max(days_of([r for r in reqs if r.source.startswith("MODIS")])) == date(2026, 11, 14)


def test_error_text_with_200_is_error(tmp_path):
    res = fetch_one(
        client(lambda r: httpx.Response(200, text="Invalid MAP_KEY.")), KEY, REQ, tmp_path, sleep=lambda s: None
    )
    assert res.status == "error"
    assert not list(tmp_path.rglob("*.csv"))
    assert not list(tmp_path.rglob("*.part"))


def test_header_only_is_empty_not_ok(tmp_path):
    body = (FIX / "viirs_header_only.csv").read_text()
    res = fetch_one(client(lambda r: httpx.Response(200, text=body)), KEY, REQ, tmp_path, sleep=lambda s: None)
    assert res.status == "empty" and res.rows == 0


def test_ok_writes_file_and_log(tmp_path):
    body = (FIX / "modis_sample.csv").read_text()
    res = fetch_one(client(lambda r: httpx.Response(200, text=body)), KEY, REQ, tmp_path)
    assert res.status == "ok" and res.rows == 2
    assert (tmp_path / "MODIS_SP" / "2026-01-01_5.csv").read_text() == body
    fields = (tmp_path / "log.tsv").read_text().splitlines()[-1].split("\t")
    assert fields[1:] == ["MODIS_SP", "2026-01-01", "5", str(len(body.encode())), "2", "ok"]


def test_existing_file_is_skipped(tmp_path):
    body = (FIX / "modis_sample.csv").read_text()
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text=body)

    c = client(handler)
    assert fetch_one(c, KEY, REQ, tmp_path).status == "ok"
    second = fetch_one(c, KEY, REQ, tmp_path)
    assert second.status == "ok" and second.rows == 2
    assert len(calls) == 1


def test_key_not_in_log(tmp_path):
    def boom(request):
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    for handler in (boom, lambda r: httpx.Response(200, text=f"Invalid MAP_KEY {KEY}"), lambda r: httpx.Response(500)):
        res = fetch_one(client(handler), KEY, REQ, tmp_path, sleep=lambda s: None)
        assert res.status == "error"
        assert KEY not in res.detail
    assert KEY not in (tmp_path / "log.tsv").read_text()
    assert not any(KEY in p.name for p in tmp_path.rglob("*"))


def test_retries_three_times(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text="Invalid MAP_KEY.")

    fetch_one(client(handler), KEY, REQ, tmp_path, sleep=lambda s: None)
    assert len(calls) == 3


def test_budget_waits():
    now = [0.0]
    pauses = []

    def sleep(s):
        pauses.append(s)
        now[0] += s

    b = Budget(limit=10, window_s=600, clock=lambda: now[0], sleep=sleep)
    b.wait(6)
    assert pauses == []
    now[0] = 100.0
    b.wait(6)  # 12 > 10 inside the window
    assert pauses and sum(pauses) >= 500
    assert now[0] >= 600


def test_budget_rejects_cost_over_limit():
    with pytest.raises(ValueError):
        Budget(limit=5).wait(6)


def _csv_handler(calls):
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="latitude,longitude\n1,2\n")

    return handler


def _stamp(path, when):
    import os

    os.utime(path, (when, when))


def test_final_window_is_kept_and_open_one_is_downloaded_again(tmp_path):
    req = Request("MODIS_NRT", date(2026, 11, 9), 1)
    target = tmp_path / "MODIS_NRT" / req.name
    target.parent.mkdir(parents=True)
    target.write_text("latitude,longitude\n")
    calls: list[str] = []
    _stamp(target, req.final_after + 60)  # written after the window was complete
    fetch_one(client(_csv_handler(calls)), KEY, req, tmp_path, sleep=lambda s: None)
    assert calls == []
    _stamp(target, req.final_after - 3600)  # written too early: the tail of the day is missing
    res = fetch_one(client(_csv_handler(calls)), KEY, req, tmp_path, sleep=lambda s: None)
    assert len(calls) == 1 and res.rows == 1
    assert target.stat().st_mtime >= req.final_after - 3600 and target.read_text().count("\n") == 2


def test_final_after_is_day_end_plus_delay():
    from senda_pipeline.firms_api import NRT_DELAY_H

    req = Request("MODIS_NRT", date(2026, 11, 9), 2)
    assert req.final_after == datetime(2026, 11, 11, NRT_DELAY_H, tzinfo=UTC).timestamp()


def test_failed_redownload_keeps_the_earlier_file(tmp_path):
    req = Request("MODIS_NRT", date(2026, 11, 9), 1)
    target = tmp_path / "MODIS_NRT" / req.name
    target.parent.mkdir(parents=True)
    target.write_text("latitude,longitude\n5,6\n")
    _stamp(target, req.final_after - 3600)
    res = fetch_one(client(lambda r: httpx.Response(500)), KEY, req, tmp_path, sleep=lambda s: None)
    assert res.status == "error" and target.read_text() == "latitude,longitude\n5,6\n"


def test_longer_tail_window_replaces_the_shorter_file_of_the_same_days(tmp_path):
    folder = tmp_path / "VIIRS_NOAA20_NRT"
    folder.mkdir()
    short = folder / "2026-11-14_1.csv"
    short.write_text("latitude,longitude\n1,2\n")
    other = folder / "2026-11-09_5.csv"
    other.write_text("latitude,longitude\n3,4\n")
    req = Request("VIIRS_NOAA20_NRT", date(2026, 11, 14), 2)
    res = fetch_one(client(_csv_handler([])), KEY, req, tmp_path, sleep=lambda s: None)
    assert res.status == "ok"
    assert sorted(p.name for p in folder.glob("*.csv")) == ["2026-11-09_5.csv", "2026-11-14_2.csv"]


def test_partly_overlapping_files_are_kept_for_scan_to_refuse(tmp_path):
    from senda_pipeline.firms_api import drop_superseded

    folder = tmp_path / "MODIS_NRT"
    folder.mkdir()
    for name in ("2026-11-09_5.csv", "2026-11-12_3.csv", "2026-11-14_2.csv"):
        (folder / name).write_text("latitude,longitude\n")
    removed = drop_superseded(folder, Request("MODIS_NRT", date(2026, 11, 14), 5))
    assert removed == ["2026-11-14_2.csv"]  # 11-12 x3 reaches before the window: not subsumed
    assert (folder / "2026-11-12_3.csv").exists() and (folder / "2026-11-09_5.csv").exists()


def test_a_failed_download_keeps_the_shorter_file(tmp_path):
    folder = tmp_path / "MODIS_NRT"
    folder.mkdir()
    (folder / "2026-11-14_1.csv").write_text("latitude,longitude\n1,2\n")
    res = fetch_one(
        client(lambda r: httpx.Response(500)), KEY, Request("MODIS_NRT", date(2026, 11, 14), 2), tmp_path,
        sleep=lambda s: None,
    )
    assert res.status == "error" and (folder / "2026-11-14_1.csv").exists()
