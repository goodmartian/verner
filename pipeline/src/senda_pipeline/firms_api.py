"""FIRMS area API client: request plan, one validated download, transaction budget.

The map key sits in every request URL. It is never logged, never put in a file name,
and exceptions from httpx (their text contains the URL) are reduced to their type name.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx

BASE = "https://firms.modaps.eosdis.nasa.gov"
# series sensors and the current period first, the rest of the year after them
SOURCES = [
    "VIIRS_SNPP_SP",
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "MODIS_NRT",
    "VIIRS_NOAA20_SP",
    "MODIS_SP",
]
SNPP_LAST_DAY = date(2026, 11, 2)
WINDOW_DAYS = 5
ATTEMPTS = 3
_WINDOW = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d+)\.csv$")
DATA_HEADER = "latitude,longitude"
LOG_NAME = "log.tsv"
# a window file is final when it was downloaded this long after the end of its last UTC day
NRT_DELAY_H = 6


class FirmsError(RuntimeError):
    """Failure of a service call. The text never contains the URL or the key."""


@dataclass(frozen=True)
class Request:
    source: str
    start: date
    days: int

    @property
    def name(self) -> str:
        return f"{self.start.isoformat()}_{self.days}.csv"

    @property
    def final_after(self) -> float:
        """Epoch seconds from which a download of this window is complete: end of its last UTC day + NRT_DELAY_H."""
        end = datetime.combine(self.start + timedelta(self.days), datetime.min.time(), UTC)
        return (end + timedelta(hours=NRT_DELAY_H)).timestamp()


@dataclass(frozen=True)
class Result:
    status: Literal["ok", "empty", "error"]
    rows: int
    detail: str = ""
    size: int = 0


class Budget:
    """Sliding window of spent transactions: wait(cost) sleeps until `cost` fits under `limit`."""

    def __init__(
        self,
        limit: int = 4200,
        window_s: int = 600,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.limit, self.window_s, self._clock, self._sleep = limit, window_s, clock, sleep
        self._spent: deque[tuple[float, int]] = deque()

    def wait(self, cost: int) -> None:
        if cost > self.limit:
            raise ValueError(f"request cost {cost} is above the budget {self.limit}")
        while True:
            now = self._clock()
            while self._spent and self._spent[0][0] <= now - self.window_s:
                self._spent.popleft()
            if sum(c for _, c in self._spent) + cost <= self.limit:
                self._spent.append((now, cost))
                return
            self._sleep(max(self._spent[0][0] + self.window_s - now, 0.0) + 1.0)


def plan_requests(availability: dict[str, tuple[date, date]], today: date, year: int) -> list[Request]:
    """SP from Jan 1 to the last SP day, NRT from the next day to today (or its last day); 5-day windows."""
    reqs: list[Request] = []
    for source in SOURCES:
        if source not in availability:
            continue
        first, last = availability[source]
        if source.endswith("_SP"):
            start, end = max(date(year, 1, 1), first), min(last, date(year, 12, 31))
        else:
            sp_last = availability.get(source.replace("_NRT", "_SP"), (first, first - timedelta(1)))[1]
            start, end = max(sp_last + timedelta(1), first, date(year, 1, 1)), min(last, today)
        if source.startswith("VIIRS_SNPP"):
            end = min(end, SNPP_LAST_DAY)
        day = start
        while day <= end:
            n = min(WINDOW_DAYS, (end - day).days + 1)
            reqs.append(Request(source, day, n))
            day += timedelta(n)
    return reqs


def scrub(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def _get_text(client: httpx.Client, url: str, key: str) -> str:
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        raise FirmsError(f"request failed: {type(e).__name__}") from None
    if r.status_code != 200:
        raise FirmsError(f"HTTP {r.status_code}")
    return scrub(r.text, key)


def mapkey_status(client: httpx.Client, key: str) -> tuple[int, int]:
    """(current_transactions, transaction_limit) of the key."""
    text = _get_text(client, f"{BASE}/mapserver/mapkey_status/?MAP_KEY={key}", key)
    try:
        data = json.loads(text)
        return int(data["current_transactions"]), int(data["transaction_limit"])
    except (ValueError, KeyError, TypeError):
        raise FirmsError("mapkey_status: unexpected answer") from None


def data_availability(client: httpx.Client, key: str) -> tuple[dict[str, tuple[date, date]], str]:
    """Per source first and last date with data, and the raw CSV (columns data_id, min_date, max_date)."""
    text = _get_text(client, f"{BASE}/api/data_availability/csv/{key}/ALL", key)
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "data_id" not in rows[0]:
        raise FirmsError("data_availability: unexpected answer")
    try:
        avail = {r["data_id"]: (date.fromisoformat(r["min_date"]), date.fromisoformat(r["max_date"])) for r in rows}
    except (ValueError, KeyError):
        raise FirmsError("data_availability: unexpected answer") from None
    return avail, text


def is_final(target: Path, req: Request) -> bool:
    """True when `target` exists and was written (mtime) after the window was complete."""
    return target.exists() and target.stat().st_mtime >= req.final_after


def drop_superseded(folder: Path, req: Request) -> list[str]:
    """Delete files of `folder` whose days all lie inside the window of `req` (and are not that file): the tail window
    grows from one run to the next (11-14 x1, then 11-14 x2), and the older, shorter file is the same days downloaded
    earlier. Two files over one day would count it twice. Files that only partly overlap are left for `scan` to refuse."""
    removed = []
    for f in sorted(folder.glob("*.csv")):
        m = _WINDOW.match(f.name)
        if not m or f.name == req.name:
            continue
        start = date.fromisoformat(m.group(1))
        if req.start <= start and start + timedelta(int(m.group(2))) <= req.start + timedelta(req.days):
            f.unlink()
            removed.append(f.name)
    return removed


def _count_rows(path: Path) -> int:
    lines, last = 0, b""
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            lines += chunk.count(b"\n")
            last = chunk[-1:]
    if last and last != b"\n":
        lines += 1
    return max(lines - 1, 0)


def _log(out_dir: Path, req: Request, res: Result) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / LOG_NAME
    new = not log.exists()
    with log.open("a") as f:
        if new:
            f.write("time\tsource\tstart\tdays\tbytes\trows\tstatus\n")
        f.write(
            f"{datetime.now(UTC).isoformat(timespec='seconds')}\t{req.source}\t{req.start.isoformat()}\t"
            f"{req.days}\t{res.size}\t{res.rows}\t{res.status}\n"
        )


def _download(client: httpx.Client, url: str, key: str, tmp: Path) -> tuple[bool, str, int, int]:
    """Stream a response into `tmp`. Returns (is_csv, detail, bytes, rows). `tmp` stays only for a valid CSV."""
    try:
        with client.stream("GET", url) as r:
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}", 0, 0
            size = 0
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
                    size += len(chunk)
    except httpx.HTTPError as e:
        tmp.unlink(missing_ok=True)
        return False, f"request failed: {type(e).__name__}", 0, 0
    with tmp.open("rb") as f:
        head = f.readline(200).decode("utf-8", "replace")
    if not head.startswith(DATA_HEADER):
        tmp.unlink(missing_ok=True)
        return False, "answer is not a CSV: " + scrub(head.strip(), key)[:60], size, 0
    return True, "", size, _count_rows(tmp)


def fetch_one(
    client: httpx.Client,
    key: str,
    req: Request,
    out_dir: Path,
    *,
    budget: Budget | None = None,
    cost: int = 1,
    sleep: Callable[[float], None] = time.sleep,
) -> Result:
    """Download one window to out_dir/<SOURCE>/<start>_<days>.csv through a temp name; log the outcome.

    A file that is already final (see is_final) is kept; an earlier, incomplete one is downloaded again.
    """
    target = out_dir / req.source / req.name
    if is_final(target, req):
        rows = _count_rows(target)
        return Result("ok" if rows else "empty", rows, "exists", target.stat().st_size)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.part")
    url = f"{BASE}/api/area/csv/{key}/{req.source}/world/{req.days}/{req.start.isoformat()}"
    res = Result("error", 0, "no attempt")
    for attempt in range(ATTEMPTS):
        if attempt:
            sleep(5.0 * attempt)
        if budget:
            budget.wait(cost)
        is_csv, detail, size, rows = _download(client, url, key, tmp)
        if is_csv and rows > 0:
            res = Result("ok", rows, size=size)
            break
        res = Result("empty", 0, "header only", size) if is_csv else Result("error", 0, detail, size)
    old_rows = _count_rows(target) if target.exists() else 0
    if res.status == "error" or (res.status == "empty" and old_rows):
        tmp.unlink(missing_ok=True)  # a failed or empty re-download keeps the earlier file
    else:
        tmp.replace(target)
        if res.status == "ok":
            for name in drop_superseded(target.parent, req):
                print(f"{req.source}: {name} replaced by {req.name}", flush=True)
    _log(out_dir, req, res)
    return res
