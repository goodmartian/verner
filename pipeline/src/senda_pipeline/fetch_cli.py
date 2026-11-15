"""senda-pipeline fetch --data DIR --year YYYY [--probe]: download one year of FIRMS area API data."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from .config import firms_key, paths
from .firms_api import (
    Budget,
    FirmsError,
    Request,
    data_availability,
    fetch_one,
    is_final,
    mapkey_status,
    plan_requests,
)

PROBE_SOURCES = ["VIIRS_NOAA20_SP", "MODIS_SP"]
COST_PER_DAY = 36  # transactions of one world request per day of data, measured with mapkey_status
HEADROOM = 400


def wait_for_room(client: httpx.Client, key: str, cost: int, sleep=time.sleep) -> None:
    """Sleep until the key's own counter has room for `cost`: the service count survives restarts, ours does not."""
    while True:
        current, limit = mapkey_status(client, key)
        if current + cost <= limit - HEADROOM:
            return
        sleep(30.0)


def _header(path) -> str:
    with path.open() as f:
        return f.readline().strip()


def probe(client: httpx.Client, key: str, year: int, api: Path) -> int:
    api.mkdir(parents=True, exist_ok=True)
    before, limit = mapkey_status(client, key)
    print(f"transactions before: {before} of {limit}")
    avail, raw = data_availability(client, key)
    (api / "availability.csv").write_text(raw)
    for source, (first, last) in sorted(avail.items()):
        print(f"availability {source}: {first} .. {last}")
    start = date(year, 1, 1)
    costs: dict[str, int] = {}
    for source in PROBE_SOURCES:
        spent_before, _ = mapkey_status(client, key)
        res = fetch_one(client, key, Request(source, start, 1), api)
        spent_after, _ = mapkey_status(client, key)
        costs[source] = spent_after - spent_before
        print(f"{source} {start} days=1: status={res.status} rows={res.rows} cost={costs[source]} transactions")
        if res.status == "error":
            print(f"  error: {res.detail}")
            continue
        print(f"  header: {_header(api / source / Request(source, start, 1).name)}")
    after, _ = mapkey_status(client, key)
    print(f"transactions after: {after} of {limit}")
    return 0


def run(client: httpx.Client, key: str, year: int, api: Path) -> int:
    api.mkdir(parents=True, exist_ok=True)
    _, limit = mapkey_status(client, key)
    avail, raw = data_availability(client, key)
    (api / "availability.csv").write_text(raw)
    today = datetime.now(UTC).date()
    reqs = plan_requests(avail, today, year)
    budget = Budget(limit=min(4200, limit - 500))
    bad = 0
    for i, req in enumerate(reqs, 1):
        cost = COST_PER_DAY * req.days
        if not is_final(api / req.source / req.name, req):
            wait_for_room(client, key, cost)
        res = fetch_one(client, key, req, api, budget=budget, cost=cost)
        if res.status == "error":
            bad += 1
        note = f" ({res.detail})" if res.status == "error" else ""
        print(f"[{i}/{len(reqs)}] {req.source} {req.start} x{req.days}: {res.status} rows={res.rows}{note}", flush=True)
    print(f"done: {len(reqs)} requests, {bad} errors")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="senda-pipeline fetch")
    p.add_argument("--data", required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--probe", action="store_true")
    args = p.parse_args(argv)
    key = firms_key()
    try:
        with httpx.Client(timeout=120) as client:
            return (probe if args.probe else run)(client, key, args.year, paths(args.data).api)
    except FirmsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
