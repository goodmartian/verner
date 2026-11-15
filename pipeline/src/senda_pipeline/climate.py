"""Monthly climate grid from ERA5 (Copernicus Climate Data Store): `senda-pipeline climate`.

Two fields, 2 m temperature and total precipitation, as monthly means on a 0.5 degree grid, plus one
normal per calendar month (mean of the years 1993-2016). Output is `data/climate/runs/<last month>/`:
`temp_c.npy` and `rain_mm.npy` are int16 [months from 2003-01, 361, 720]; `normal_*.npy` are [12, 361, 720].
Row 0 is 90 N, column 0 is 180 W, a gap is -32768 (same layout as the weather grid). A month ERA5 has not
published yet stays a gap. `climate/current` points at the newest run; two runs are kept.

CDS is queried over its REST API (submit, poll, download): one request per year, all submitted up front.
A finished year is kept in `_work/era5/` and never fetched again; a job id is kept next to it, so a run
interrupted while waiting in the CDS queue picks the same job up again.
"""

from __future__ import annotations

import argparse
import calendar
import json
import shutil
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
from numpy.typing import NDArray

from senda_pipeline import config, gfs, weather

API = "https://cds.climate.copernicus.eu/api/retrieve/v1"
DATASET = "reanalysis-era5-single-levels-monthly-means"
SOURCE = "ERA5 monthly averaged data on single levels, 2 m temperature and total precipitation"
ATTRIBUTION = "Generated using Copernicus Climate Change Service information"
FIRST_MONTH = (2003, 1)
NORMAL_YEARS = (1993, 2016)
LAG_DAYS = 7  # ERA5 publishes month M about the 5th to 7th of M+1
STRIDE = 2  # 0.25 degree to 0.5 degree: every second node
ROWS, COLS, STEP = (gfs.ROWS - 1) // STRIDE + 1, gfs.COLS // STRIDE, gfs.STEP * STRIDE
GRID = {"lat0": 90.0, "lon0": -180.0, "step": STEP, "rows": ROWS, "cols": COLS}
SHORT_NAMES = {"2t": "temp_c", "tp": "rain_mm"}
VARIABLES = {"temp_c": ("degC", 0.01), "rain_mm": ("mm", 0.2)}  # name: (units, int16 scale)
MAX_QUEUED = 4
GROUP = 9  # missing years per CDS request
REPORT_S = 300.0  # how often a waiting run says so
POLL_S = 60.0
WAIT_H = 12.0
FAILURES = 2  # a year whose job fails more often than this stops the run


class CdsError(RuntimeError):
    """A CDS problem told in words; never carries the key."""


@dataclass(frozen=True)
class Chunk:
    """Whole years `year` to `last` (default: the one year), the last of them only to month `months`."""

    year: int
    months: int
    last: int | None = None

    @property
    def last_year(self) -> int:
        return self.last or self.year

    @property
    def key(self) -> str:
        return (
            f"{self.year}-{self.months:02d}"
            if self.last_year == self.year
            else f"{self.year}-{self.last_year}-{self.months:02d}"
        )

    @property
    def file(self) -> str:
        return f"{self.key}.grib"


class Cds:
    """Three REST calls of the CDS API with a personal token."""

    def __init__(self, key: str, client: httpx.Client | None = None, log: Callable[[str], None] | None = None):
        self.log = log or say
        self.client = client or httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=True)
        self.headers = {"PRIVATE-TOKEN": key}

    def submit(self, chunk: Chunk) -> str:
        inputs = {
            "product_type": ["monthly_averaged_reanalysis"],
            "variable": ["2m_temperature", "total_precipitation"],
            "year": [str(y) for y in range(chunk.year, chunk.last_year + 1)],
            "month": [f"{m:02d}" for m in range(1, 13 if chunk.last_year > chunk.year else chunk.months + 1)],
            "time": ["00:00"],
            "data_format": "grib",
            "download_format": "unarchived",
        }
        try:
            res = self.client.post(
                f"{API}/processes/{DATASET}/execution", json={"inputs": inputs}, headers=self.headers
            )
        except httpx.HTTPError as e:
            raise CdsError(f"CDS unreachable: {type(e).__name__}") from e
        if res.status_code in (401, 403):
            raise CdsError(
                f"CDS refused the request (HTTP {res.status_code}): check the token and accept the ERA5 licence"
            )
        if res.status_code not in (200, 201):
            raise CdsError(f"CDS rejected the request: HTTP {res.status_code}")
        return str(res.json()["jobID"])

    def status(self, job: str) -> str:
        """accepted, running, successful, failed (also for a job CDS no longer knows). Network trouble reads as running."""
        try:
            res = self.client.get(f"{API}/jobs/{job}", headers=self.headers)
        except httpx.HTTPError as e:
            self.log(f"CDS not reachable for job {job}: {type(e).__name__}, will ask again")
            return "running"
        if res.status_code == 404:
            return "failed"
        if res.status_code in (401, 403):
            raise CdsError(f"CDS refused the request (HTTP {res.status_code}): check the token")
        if res.status_code != 200:
            self.log(f"CDS answered HTTP {res.status_code} for job {job}, will ask again")
            return "running"
        state = str(res.json().get("status", "running"))
        return "failed" if state in ("failed", "dismissed", "rejected") else state

    def reason(self, job: str) -> str:
        """Why CDS ended a job: the text of its error answer, or just its state. Never the token."""
        try:
            res = self.client.get(f"{API}/jobs/{job}/results", headers=self.headers)
            body = res.json()
            text = body.get("traceback") or body.get("title") or body.get("detail") or f"HTTP {res.status_code}"
        except (httpx.HTTPError, ValueError, AttributeError):
            return "no reason given"
        return str(text).replace(self.headers["PRIVATE-TOKEN"], "***")[:500]

    def download(self, job: str, dest: Path) -> None:
        try:
            res = self.client.get(f"{API}/jobs/{job}/results", headers=self.headers)
            res.raise_for_status()
            href = res.json()["asset"]["value"]["href"]
            tmp = dest.with_suffix(".part")
            with self.client.stream("GET", href) as body:
                body.raise_for_status()
                with tmp.open("wb") as out:
                    for block in body.iter_bytes(1 << 20):
                        out.write(block)
        except (httpx.HTTPError, KeyError) as e:
            raise CdsError(f"download failed: {type(e).__name__}") from e
        tmp.replace(dest)


def last_available(now: datetime) -> tuple[int, int]:
    """The newest (year, month) ERA5 has published by `now`."""
    day = (now - timedelta(days=LAG_DAYS)).date().replace(day=1) - timedelta(days=1)
    return day.year, day.month


def last_calendar(now: datetime) -> tuple[int, int]:
    day = now.date().replace(day=1) - timedelta(days=1)
    return day.year, day.month


def cached_years(cache: Path) -> dict[int, Chunk]:
    """The whole years that downloaded files of `cache` hold, each with its chunk."""
    found: dict[int, Chunk] = {}
    for path in cache.glob("*.grib"):
        parts = path.stem.split("-")
        if len(parts) not in (2, 3) or not all(x.isdigit() for x in parts) or int(parts[-1]) != 12:
            continue  # a year in progress is fetched again
        first, last = int(parts[0]), int(parts[-2])
        chunk = Chunk(first, 12, last if last > first else None)
        found.update({y: chunk for y in range(first, last + 1)})
    return found


def plan(now: datetime, cache: Path | None = None) -> list[Chunk]:
    """Chunks from the first normal year to the newest published month. A year already in `cache` is its own
    chunk; the years still missing go together, GROUP years to a request: one big request waits in the CDS
    queue once, many small ones wait one after the other."""
    ly, lm = last_available(now)
    chunks: list[Chunk] = []
    run: list[int] = []

    def flush() -> None:
        for i in range(0, len(run), GROUP):
            part = run[i : i + GROUP]
            chunks.append(Chunk(part[0], 12, part[-1] if len(part) > 1 else None))
        run.clear()

    have = cached_years(cache) if cache is not None else {}
    for y in range(NORMAL_YEARS[0], ly):
        if y in have:
            flush()
            if have[y] not in chunks:
                chunks.append(have[y])
        else:
            run.append(y)
    flush()
    chunks.append(Chunk(ly, lm))
    return chunks


def say(message: str) -> None:
    """One line of progress with the time, flushed so that a log file shows movement."""
    print(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S} climate: {message}", flush=True)


def fetch(
    cds: Cds,
    cache: Path,
    chunks: list[Chunk],
    sleep: Callable[[float], None] = time.sleep,
    poll: float = POLL_S,
    deadline: float = WAIT_H * 3600,
    log: Callable[[str], None] = say,
) -> list[Chunk]:
    """Make every chunk a file in `cache`; returns the chunks that could not be had.

    Submits up to `cap` jobs (it starts at MAX_QUEUED and drops to what CDS accepted when CDS says its
    queue for the dataset is full; that refusal is not a failure of the year), polls, downloads as jobs
    finish. A year whose job fails more than FAILURES times is given up on; the others go on."""
    cache.mkdir(parents=True, exist_ok=True)
    todo = [c for c in chunks if not (cache / c.file).exists()]
    jobs: dict[Chunk, str] = {}
    failed: dict[Chunk, int] = {}
    lost: list[Chunk] = []
    cap = MAX_QUEUED
    for c in todo:  # a job from an interrupted run
        saved = cache / f"{c.key}.job"
        if saved.exists():
            jobs[c] = saved.read_text().strip()
            log(f"{c.key}: picked up job {jobs[c]}")
    queue = [c for c in todo if c not in jobs]
    waited = reported = 0.0
    states: dict[str, str] = {}

    def drop(c: Chunk) -> None:
        (cache / f"{c.key}.job").unlink(missing_ok=True)
        del jobs[c]

    def fail(c: Chunk, why: str, count: bool = True) -> None:
        if count:
            failed[c] = failed.get(c, 0) + 1
        if failed.get(c, 0) > FAILURES:
            lost.append(c)
            log(f"{c.key}: given up after {failed[c]} failures ({why})")
        else:
            queue.append(c)

    while queue or jobs:
        while queue and len(jobs) < cap:
            c = queue.pop(0)
            jobs[c] = cds.submit(c)
            (cache / f"{c.key}.job").write_text(jobs[c])
            log(f"{c.key}: submitted ({len(jobs)} in the queue)")
        for c, job in list(jobs.items()):
            state = states[c.key] = cds.status(job)
            if state == "successful":
                log(f"{c.key}: ready")
                try:
                    cds.download(job, cache / c.file)
                except CdsError as e:
                    log(f"{c.key}: {e}")
                    drop(c)
                    fail(c, str(e))
                    continue
                drop(c)
                log(f"{c.key}: downloaded ({(cache / c.file).stat().st_size / 1e6:.0f} MB)")
            elif state == "failed":
                why = cds.reason(job)
                drop(c)
                if "queued requests" in why:  # CDS holds too many of our jobs for this dataset
                    cap = max(1, len(jobs))
                    log(f"{c.key}: refused, CDS queue is full; at most {cap} jobs in the queue from now on")
                    fail(c, why, count=False)
                else:
                    log(f"{c.key}: job failed: {why}")
                    fail(c, why)
        for key in [k for k in states if k not in {c.key for c in jobs}]:
            del states[key]
        if jobs and waited >= reported:
            log(
                f"waiting: {len(jobs)} jobs, {len(queue)} not sent yet; "
                + ", ".join(f"{k} {v}" for k, v in states.items())
            )
            reported = waited + REPORT_S
        if queue or jobs:
            if waited >= deadline:
                raise CdsError("CDS queue did not finish in time; run the command again to continue")
            sleep(poll)
            waited += poll
    return lost


Field = tuple[str, int, int, NDArray[np.float32]]  # variable, year, month, [361, 720] in physical units


def read_grib(path: Path) -> Iterator[tuple[str, int, NDArray[np.float32]]]:
    """(shortName, dataDate, [721, 1440] values) of every message of a file."""
    import pygrib  # imported here: the module is only needed when GRIB is read

    with pygrib.open(str(path)) as grbs:
        for grb in grbs:
            yield str(grb.shortName), int(grb.dataDate), gfs.decode_grib(grb)


Reader = Callable[[Path], Iterator[tuple[str, int, NDArray[np.float32]]]]


def convert(short: str, year: int, month: int, values: NDArray[np.float32]) -> Field | None:
    """Thin to 0.5 degree and to physical units: temperature in degC, precipitation in mm of the month.
    ERA5 gives K and metres per day (mean over the month), so rain is x1000 x days of the month."""
    name = SHORT_NAMES.get(short)
    if name is None:
        return None
    if values.shape != (gfs.ROWS, gfs.COLS):
        raise ValueError(f"unexpected grid {values.shape}, expected {(gfs.ROWS, gfs.COLS)}")
    thin = values[::STRIDE, ::STRIDE]
    if name == "temp_c":
        return name, year, month, thin - np.float32(273.15)
    return name, year, month, np.maximum(thin * np.float32(1000 * calendar.monthrange(year, month)[1]), 0)


def month_index(year: int, month: int) -> int:
    return (year - FIRST_MONTH[0]) * 12 + month - FIRST_MONTH[1]


def assemble(
    files: list[Path], last: tuple[int, int], reader: Reader = read_grib
) -> tuple[dict[str, NDArray[np.int16]], dict[str, NDArray[np.int16]], tuple[int, int] | None]:
    """Series [months to `last`, ROWS, COLS], normals [12, ROWS, COLS] and the newest month with data."""
    months = month_index(*last) + 1
    series = {n: np.full((months, ROWS, COLS), weather.MISSING, np.int16) for n in VARIABLES}
    total = {n: np.zeros((12, ROWS, COLS)) for n in VARIABLES}
    count = {n: np.zeros((12, ROWS, COLS), np.int32) for n in VARIABLES}
    newest: tuple[int, int] | None = None
    for path in files:
        for short, stamp, values in reader(path):
            year, month = stamp // 10000, stamp // 100 % 100
            field = convert(short, year, month, values)
            if field is None:
                continue
            name, _, _, data = field
            if NORMAL_YEARS[0] <= year <= NORMAL_YEARS[1]:
                ok = ~np.isnan(data)
                total[name][month - 1] += np.where(ok, data, 0)
                count[name][month - 1] += ok
            if 0 <= (i := month_index(year, month)) < months:
                series[name][i] = weather.encode(data, VARIABLES[name][1])
                newest = max(newest or (year, month), (year, month))
    normals = {}
    for name, (_, scale) in VARIABLES.items():
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(count[name] > 0, total[name] / count[name], np.nan)
        normals[f"normal_{name}"] = weather.encode(mean.astype(np.float32), scale)
    return series, normals, newest


def month_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def last_with_data(series: dict[str, NDArray[np.int16]]) -> tuple[int, int] | None:
    """The newest month in which every variable has values (ERA5 may publish the temperature before the rain)."""
    for i in range(min(a.shape[0] for a in series.values()) - 1, -1, -1):
        if all((a[i] != weather.MISSING).any() for a in series.values()):
            return FIRST_MONTH[0] + (FIRST_MONTH[1] - 1 + i) // 12, (FIRST_MONTH[1] - 1 + i) % 12 + 1
    return None


def write_run(
    root: Path, rid: str, first: str, last: str, data_last: str, arrays: dict[str, NDArray[np.int16]]
) -> Path:
    runs = root / "runs"
    tmp, final = runs / f"{rid}.tmp", runs / rid
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name, arr in arrays.items():
        np.save(tmp / f"{name}.npy", arr)
    meta = {
        "run_id": rid,
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE,
        "attribution": ATTRIBUTION,
        "grid": GRID,
        "first_month": first,
        "last_month": last,  # the series ends here; months ERA5 has not published stay gaps
        "last_data_month": data_last,  # the newest month in which every variable has values
        "months": arrays["temp_c"].shape[0],
        "normal": {"first_year": NORMAL_YEARS[0], "last_year": NORMAL_YEARS[1], "months": 12},
        "variables": {
            n: {"units": u, "scale": sc, "file": f"{n}.npy", "normal_file": f"normal_{n}.npy"}
            for n, (u, sc) in VARIABLES.items()
        },
    }
    (tmp / "meta.json").write_text(json.dumps(meta, indent=1))
    shutil.rmtree(final, ignore_errors=True)
    tmp.rename(final)
    return final


def run(
    data: Path,
    refresh: bool = False,
    now: datetime | None = None,
    cds: Cds | None = None,
    reader: Reader = read_grib,
    sleep: Callable[[float], None] = time.sleep,
    poll: float = POLL_S,
    deadline: float = WAIT_H * 3600,
) -> str:
    """Build the grid. Returns "built", "up to date", or "skipped: <why>"; `current` is touched only on success."""
    if cds is None:
        key = config.copernicus_key()
        if not key:
            return "skipped: COPERNICUS_API_KEY is not set (put it into .env)"
        cds = Cds(key)
    p = config.paths(data)
    root, cache = p.root / "climate", p.work / "era5"
    now = now or datetime.now(UTC)
    rid = month_label(*last_available(now))
    if not refresh and (root / "runs" / rid / "meta.json").exists():
        weather.swap_current(root, rid)
        return "up to date"
    if refresh:
        shutil.rmtree(cache, ignore_errors=True)
    chunks = plan(now, cache)
    lost = fetch(cds, cache, chunks, sleep, poll, deadline)
    if lost:
        raise CdsError(
            "no data for " + ", ".join(c.key for c in lost) + "; the rest is downloaded, run the command again"
        )
    files = [cache / c.file for c in chunks]
    last = last_calendar(now)
    series, normals, newest = assemble(files, last, reader)
    if newest is None:
        return "skipped: no usable messages in the downloaded files"
    data_last = last_with_data(series)
    if data_last is None:
        return "skipped: no month has both temperature and rain"
    rid = month_label(*newest)
    write_run(root, rid, month_label(*FIRST_MONTH), month_label(*last), month_label(*data_last), {**series, **normals})
    weather.swap_current(root, rid)
    weather.prune_runs(root, {rid})
    keep = {c.file for c in chunks}
    for old in cache.glob("*.grib"):
        if old.name not in keep:  # a shorter chunk of a year that is now complete
            old.unlink()
    return "built"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline climate")
    ap.add_argument("--data", required=True, help="data root (contains _work/, climate/)")
    ap.add_argument("--refresh", action="store_true", help="fetch everything again and rebuild")
    ap.add_argument("--wait-hours", type=float, default=WAIT_H, help="how long to wait for the CDS queue")
    args = ap.parse_args(argv)
    t0 = time.time()
    try:
        result = run(Path(args.data), refresh=args.refresh, deadline=args.wait_hours * 3600)
    except CdsError as e:
        say(f"stopped: {e}")
        return 1
    say(f"{result} in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
