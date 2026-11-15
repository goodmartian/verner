"""`senda-pipeline weather`: a world weather grid from NOAA GFS 0.25 degree, 3-hourly, 72 h back and 24 h ahead.

Output (under <data>/weather/):
    runs/<run_id>/meta.json and <variable>.npy   int16 [T, 721, 1440], row 0 = 90 N, column 0 = 180 W
    current -> runs/<run_id>                     symlink, swapped atomically; the two newest runs are kept

Past times come from the short forecasts (leads 3 and 6) of consecutive cycles, future times from the latest
cycle. Downloaded messages of leads up to 6 are cached in <data>/_work/gfs/ so the next run fetches only new ones.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from senda_pipeline import config, gfs

SOURCE = "NOAA GFS 0.25 degree"
STEP_H = 3
PAST = timedelta(hours=72)
AHEAD = timedelta(hours=24)
FIRE_WINDOW_DAYS = 3  # live fires show the last three complete days
MARGIN_DAYS = 1
MAX_PAST = timedelta(days=9)
WORKERS = 4
CACHE_MAX_LEAD = 6
"""Leads that a later run reads again (past times use leads 3 and 6); longer leads are held in memory only."""
KEEP_RUNS = 2
RUN_NAME = re.compile(r"(?!.*\.tmp$).+")  # any run folder except an unfinished one
MISSING = -32768
GRID = {"lat0": 90.0, "lon0": -180.0, "step": gfs.STEP, "rows": gfs.ROWS, "cols": gfs.COLS}
VARIABLES = {  # name: (units, scale)
    "wind_u": ("m/s", 0.01),
    "wind_v": ("m/s", 0.01),
    "gust": ("m/s", 0.01),
    "temp_c": ("degC", 0.01),
    "rh": ("%", 0.1),
    "precip": ("mm/h", 0.01),
}

Decoder = Callable[[bytes], NDArray[np.float32]]


@dataclass(frozen=True)
class Slot:
    """Where the weather of one output time comes from."""

    time: datetime
    cycle: datetime
    lead: int


def run_id(cycle: datetime) -> str:
    return f"{cycle:%Y%m%dT%H}Z"


def iso(moment: datetime) -> str:
    return f"{moment.astimezone(UTC):%Y-%m-%dT%H:%M:%S}Z"


def window_start(latest: datetime, last_complete: date | None) -> datetime:
    """00:00 UTC of the first day of the fire window, a day earlier for margin; never later than latest - 72 h
    and never earlier than MAX_PAST. Without data: latest - 72 h."""
    default = latest - PAST
    if last_complete is None:
        return default
    first = last_complete - timedelta(days=FIRE_WINDOW_DAYS - 1 + MARGIN_DAYS)
    start = datetime(first.year, first.month, first.day, tzinfo=UTC)
    return min(max(start, latest - MAX_PAST), default)


def last_complete_date(data_root: Path) -> date | None:
    """`last_complete_date` of the published data version, None when there is none."""
    try:
        text = json.loads((data_root / "current" / "manifest.json").read_text())["last_complete_date"]
        return date.fromisoformat(text)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def plan(latest: datetime, start: datetime | None = None) -> list[Slot]:
    """Times from `start` (default latest - 72 h) to latest + 24 h every 3 h. Up to the latest cycle: the earlier
    cycle at lead 3 or 6. After it: the latest cycle."""
    slots, t, end = [], start or latest - PAST, latest + AHEAD
    while t <= end:
        cycle = gfs.cycle_of(t - timedelta(hours=STEP_H)) if t <= latest else latest
        slots.append(Slot(t, cycle, int((t - cycle) / timedelta(hours=1))))
        t += timedelta(hours=STEP_H)
    return slots


def needs(slots: list[Slot]) -> dict[tuple[datetime, int], set[str]]:
    """Fields to read for each (cycle, lead). Rain at a multiple of 6 h is a 6 h bucket, the 3 h before it is
    taken off, so that lead needs the rain of lead - 3 too."""
    out: dict[tuple[datetime, int], set[str]] = {}
    for s in slots:
        out.setdefault((s.cycle, s.lead), set()).update(gfs.MESSAGES)
        if s.lead % 6 == 0:
            out.setdefault((s.cycle, s.lead - 3), set()).add("apcp")
    return out


def latest_cycle(fetcher: gfs.Fetcher, now: datetime) -> datetime:
    """The newest cycle that has published its last needed lead (24 h)."""
    cycle = gfs.cycle_of(now)
    for _ in range(4):
        try:
            fetcher.get_text(f"{gfs.object_url(cycle, 24)}.idx")
            return cycle
        except gfs.FetchError as e:
            if e.status not in gfs.ABSENT:
                raise
        cycle -= timedelta(hours=gfs.CYCLE_HOURS)
    raise gfs.FetchError("no GFS cycle of the last day has published lead 24")


class Store:
    """Raw GRIB messages: on disk for leads up to CACHE_MAX_LEAD, in memory for the rest."""

    def __init__(self, directory: Path):
        self.dir, self.held = directory, {}

    def _path(self, cycle: datetime, lead: int, key: str) -> Path:
        return self.dir / f"{cycle:%Y%m%d%H}" / f"f{lead:03d}_{key}.grib2"

    def has(self, cycle: datetime, lead: int, key: str) -> bool:
        if lead > CACHE_MAX_LEAD:
            return (cycle, lead, key) in self.held
        return self._path(cycle, lead, key).exists()

    def put(self, cycle: datetime, lead: int, key: str, data: bytes) -> None:
        if lead > CACHE_MAX_LEAD:
            self.held[cycle, lead, key] = data
            return
        path = self._path(cycle, lead, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, cycle: datetime, lead: int, key: str) -> bytes:
        if lead > CACHE_MAX_LEAD:
            return self.held[cycle, lead, key]
        return self._path(cycle, lead, key).read_bytes()

    def prune(self, keep_from: datetime) -> None:
        """Forget cached cycles older than `keep_from`."""
        if not self.dir.exists():
            return
        for folder in self.dir.iterdir():
            if folder.is_dir() and folder.name < f"{keep_from:%Y%m%d%H}":
                shutil.rmtree(folder)


def download(fetcher: gfs.Fetcher, store: Store, wanted: dict[tuple[datetime, int], set[str]]) -> tuple[int, int]:
    """Fetch the messages the store lacks. Returns (messages fetched, bytes fetched)."""
    todo = {k: {f for f in v if not store.has(k[0], k[1], f)} for k, v in wanted.items()}
    todo = {k: v for k, v in todo.items() if v}

    def load(item: tuple[tuple[datetime, int], set[str]]) -> int:
        (cycle, lead), keys = item
        url = gfs.object_url(cycle, lead)
        found = gfs.spans(gfs.parse_idx(fetcher.get_text(f"{url}.idx")), lead, keys)
        total = 0
        for key, (start, length) in found.items():
            store.put(cycle, lead, key, fetcher.get_range(url, start, length))
            total += length
        return total

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        sizes = list(pool.map(load, sorted(todo.items(), key=lambda kv: kv[0])))
    return sum(len(v) for v in todo.values()), sum(sizes)


def encode(values: NDArray[np.floating], scale: float) -> NDArray[np.int16]:
    """Physical value / scale as int16; NaN becomes MISSING."""
    scaled = np.rint(values / scale)
    out = np.clip(np.nan_to_num(scaled), -32767, 32767).astype(np.int16)
    out[np.isnan(values)] = MISSING
    return out


def _field(store: Store, decoder: Decoder, slot: Slot, key: str) -> NDArray[np.float32]:
    return decoder(store.get(slot.cycle, slot.lead, key))


def assemble(slots: list[Slot], store: Store, decoder: Decoder) -> dict[str, NDArray[np.int16]]:
    """Arrays [T, 721, 1440] for each variable."""
    shape = (len(slots), gfs.ROWS, gfs.COLS)
    arrays = {name: np.full(shape, MISSING, dtype=np.int16) for name in VARIABLES}
    rain: dict[tuple[datetime, int], NDArray[np.float32]] = {}

    def bucket(cycle: datetime, lead: int) -> NDArray[np.float32]:
        if (cycle, lead) not in rain:
            rain[cycle, lead] = decoder(store.get(cycle, lead, "apcp"))
        return rain[cycle, lead]

    for i, s in enumerate(slots):
        field = partial(_field, store, decoder, s)
        arrays["wind_u"][i] = encode(field("ugrd"), 0.01)
        arrays["wind_v"][i] = encode(field("vgrd"), 0.01)
        arrays["gust"][i] = encode(field("gust"), 0.01)
        arrays["temp_c"][i] = encode(field("tmp") - 273.15, 0.01)
        arrays["rh"][i] = encode(np.clip(field("rh"), 0, 100), 0.1)
        total = bucket(s.cycle, s.lead)
        step = total if s.lead % 6 == 3 else total - bucket(s.cycle, s.lead - 3)
        arrays["precip"][i] = encode(np.maximum(step, 0) / STEP_H, 0.01)
    return arrays


def swap_current(root: Path, rid: str) -> None:
    """Point <root>/current at runs/<rid> atomically (temporary link, then rename over it)."""
    tmp = root / f".current.{os.getpid()}"
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(Path("runs") / rid)
    os.replace(tmp, root / "current")


def prune_runs(root: Path, keep: set[str]) -> None:
    """Keep the newest KEEP_RUNS runs and every run in `keep`."""
    config.prune_dirs(root / "runs", RUN_NAME, keep, KEEP_RUNS)


def write_run(root: Path, latest: datetime, slots: list[Slot], arrays: dict[str, NDArray[np.int16]]) -> Path:
    rid = run_id(latest)
    runs = root / "runs"
    tmp, final = runs / f"{rid}.tmp", runs / rid
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name, arr in arrays.items():
        np.save(tmp / f"{name}.npy", arr)
    meta = {
        "run_id": rid,
        "built_at": iso(datetime.now(UTC)),
        "source": SOURCE,
        "grid": GRID,
        "times": [iso(s.time) for s in slots],
        "analysis_until": iso(latest),
        "variables": {n: {"units": u, "scale": sc, "file": f"{n}.npy"} for n, (u, sc) in VARIABLES.items()},
    }
    (tmp / "meta.json").write_text(json.dumps(meta, indent=1))
    shutil.rmtree(final, ignore_errors=True)
    tmp.rename(final)
    return final


def built_from(root: Path, rid: str) -> datetime | None:
    """First time of an existing run, None when the run is absent or unreadable."""
    try:
        first = json.loads((root / "runs" / rid / "meta.json").read_text())["times"][0]
        return datetime.fromisoformat(first)
    except (OSError, ValueError, KeyError, IndexError):
        return None


def run(
    data: Path,
    now: datetime | None = None,
    fetcher: gfs.Fetcher | None = None,
    decoder: Decoder = gfs.decode,
) -> str:
    """Build the grid. Returns "built", "up to date", or "skipped: <why>" (network down, cycle not published)."""
    p = config.paths(data)
    root = p.root / "weather"
    now = now or datetime.now(UTC)
    fetcher = fetcher or gfs.HttpFetcher()
    store = Store(p.work / "gfs")
    try:
        latest = latest_cycle(fetcher, now)
        rid = run_id(latest)
        start = window_start(latest, last_complete_date(p.root))
        if built_from(root, rid) is not None and built_from(root, rid) <= start:
            (root / "runs").mkdir(parents=True, exist_ok=True)
            swap_current(root, rid)
            return "up to date"
        slots = plan(latest, start)
        got, size = download(fetcher, store, needs(slots))
        print(f"fetched {got} messages, {size / 1e6:.0f} MB", flush=True)
    except (gfs.FetchError, ValueError) as e:
        return f"skipped: {e}"
    arrays = assemble(slots, store, decoder)
    write_run(root, latest, slots, arrays)
    swap_current(root, rid)
    prune_runs(root, {rid})
    store.prune(slots[0].cycle)
    return "built"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline weather")
    ap.add_argument("--data", required=True, help="data root (contains _work/, weather/)")
    args = ap.parse_args(argv)
    t0 = time.time()
    result = run(Path(args.data))
    print(f"weather: {result} in {time.time() - t0:.0f} s", file=sys.stdout)
    return 0
