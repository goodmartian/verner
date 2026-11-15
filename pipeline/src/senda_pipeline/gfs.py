"""NOAA GFS 0.25 degree from the AWS Open Data bucket: `.idx` byte ranges, GRIB2 messages, world grid.

Each GFS file is about 500 MB, but a small `.idx` beside it lists the byte range of every message,
so only the few messages we need are fetched (`parse_idx`, `cycle_of`, `object_url`, range fetching).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
import numpy as np
from numpy.typing import NDArray

BUCKET_URL = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
CYCLE_HOURS = 6
ROWS, COLS, STEP = 721, 1440, 0.25
ABSENT = (403, 404)
"""What S3 answers for a file that is not there yet."""

MESSAGES = {
    "ugrd": ("UGRD", "10 m above ground"),
    "vgrd": ("VGRD", "10 m above ground"),
    "gust": ("GUST", "surface"),
    "tmp": ("TMP", "2 m above ground"),
    "rh": ("RH", "2 m above ground"),
    "apcp": ("APCP", "surface"),
}


class FetchError(Exception):
    """A request failed. `status` is the HTTP status, None for network problems."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Fetcher(Protocol):
    def get_text(self, url: str) -> str: ...

    def get_range(self, url: str, start: int, length: int) -> bytes: ...


class HttpFetcher:
    """Plain HTTPS with a few retries. Error text holds the exception type only."""

    def __init__(self, retries: int = 3, pause: float = 2.0):
        self.client = httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=True)
        self.retries, self.pause = retries, pause

    def _get(self, url: str, headers: dict[str, str], ok: tuple[int, ...]) -> httpx.Response:
        last: FetchError | None = None
        for attempt in range(self.retries):
            if attempt:
                time.sleep(self.pause * attempt)
            try:
                res = self.client.get(url, headers=headers)
            except httpx.HTTPError as e:
                last = FetchError(f"network error: {type(e).__name__}")
                continue
            if res.status_code in ok:
                return res
            last = FetchError(f"HTTP {res.status_code}", res.status_code)
            if res.status_code in ABSENT:
                break
        assert last is not None
        raise last

    def get_text(self, url: str) -> str:
        return self._get(url, {}, (200,)).text

    def get_range(self, url: str, start: int, length: int) -> bytes:
        data = self._get(url, {"Range": f"bytes={start}-{start + length - 1}"}, (206,)).content
        if len(data) != length:
            raise FetchError("short range answer")
        return data


@dataclass(frozen=True)
class Message:
    """A line of an `.idx` file: where one message lies in the data file."""

    name: str
    level: str
    step: str
    start: int
    end: int | None
    """Exclusive; None for the last message of the file."""


def cycle_of(moment: datetime) -> datetime:
    """The latest cycle at or before the moment."""
    moment = moment.astimezone(UTC)
    return moment.replace(hour=moment.hour // CYCLE_HOURS * CYCLE_HOURS, minute=0, second=0, microsecond=0)


def object_url(cycle: datetime, lead: int) -> str:
    return f"{BUCKET_URL}/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos/gfs.t{cycle:%H}z.pgrb2.0p25.f{lead:03d}"


def parse_idx(text: str) -> list[Message]:
    """The messages of an `.idx` file; each ends where the next one starts."""
    rows = [line.split(":") for line in text.strip().splitlines() if line.strip()]
    return [
        Message(
            name=row[3],
            level=row[4],
            step=row[5],
            start=int(row[1]),
            end=int(rows[i + 1][1]) if i + 1 < len(rows) else None,
        )
        for i, row in enumerate(rows)
    ]


def rain_bucket(lead: int) -> str:
    """Accumulation step of the rain message at a lead. Buckets restart every 6 hours: `0-3`, `0-6`, `6-9`,
    `6-12`, ... (the file also holds `0-N` totals at some leads, which are not used)."""
    return f"{(lead - 1) // 6 * 6}-{lead} hour acc fcst"


def spans(messages: list[Message], lead: int, only: set[str] | None = None) -> dict[str, tuple[int, int]]:
    """Start and length in bytes of the message of each wanted field at a lead."""
    found: dict[str, tuple[int, int]] = {}
    for key, (name, level) in MESSAGES.items():
        if only is not None and key not in only:
            continue
        chosen = next(
            (
                m
                for m in messages
                if (m.name, m.level) == (name, level) and (key != "apcp" or m.step == rain_bucket(lead))
            ),
            None,
        )
        if chosen is None or chosen.end is None:
            raise ValueError(f"{name} {level} is not in the file for lead {lead}")
        found[key] = (chosen.start, chosen.end - chosen.start)
    return found


def decode_grib(grib) -> NDArray[np.float32]:
    """A pygrib message of a regular global lat/lon grid as [rows, cols] float32: row 0 is 90 N, column 0 is
    180 W (GRIB stores longitudes 0 to 360, so the columns are rolled by half the circle). Gaps are NaN."""
    values = np.ma.filled(np.ma.asarray(grib.values).astype(np.float32), np.nan)
    if grib["jScansPositively"]:  # first row is the south
        values = values[::-1]
    step = float(grib["iDirectionIncrementInDegrees"])
    lon0 = float(grib["longitudeOfFirstGridPointInDegrees"])
    return np.roll(values, (round(lon0 / step) + values.shape[1] // 2) % values.shape[1], axis=1)


def decode(message: bytes) -> NDArray[np.float32]:
    """One GRIB2 message of the global 0.25 degree grid as [721, 1440] float32 (see `decode_grib`)."""
    import pygrib  # imported here: the module is only needed when GRIB is read

    values = decode_grib(pygrib.fromstring(message))
    if values.shape != (ROWS, COLS):
        raise ValueError(f"unexpected grid {values.shape}, expected {(ROWS, COLS)}")
    return values
