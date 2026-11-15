"""NOAA GFS weather on a global 0.25 degree grid, read from memory-mapped files.

The files are made by `senda-pipeline weather` (see `Weather` for the layout). Nothing is loaded whole: the
interpolated plane of an hour is a few MB, a point is read as a handful of scattered values. `WeatherSource`
looks at the published run once a minute and switches to a new one without a restart.

Here: the PNG writer, painting, Web Mercator rows, wind picture coding, arrows by zoom, point and series
sampling, all on a global lattice read from files: hours between the three-hourly steps are interpolated
linearly in time, points bilinearly in space.
"""

from __future__ import annotations

import json
import math
import struct
import threading
import time
import zlib
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .errors import ApiError
from .weather_legend import DRYNESS, RAIN, WIND, LayerLegend, rgb, vpd_kpa

Floats = NDArray[np.float64]
HOUR_MS = 3_600_000
MISSING = -32768
WIND_RANGE = 40.0
"""m/s: what the 0 to 255 of the wind field picture stands for, from -40 to 40."""
MAX_LAT = 85.0511287798
"""The north and south edge of a Web Mercator map; the layer pictures end there."""
PIXELS_PER_CELL = 1
WIND_BLOCK = 4
"""The wind picture has one pixel per BLOCK x BLOCK cells (their mean): 1 degree, about 100 KB for the world."""
PICTURES_KEPT = 48
ARROW_STRIDES = ((3, 16), (4, 8))
"""Up to a zoom level, keep every N-th row and column of the grid; beyond the last, every 8th (the request has no
frame of the map, so the whole world is thinned by the same step)."""
ARROW_LAT = 80.0
RECHECK_S = 60.0
VARIABLES = ("wind_u", "wind_v", "gust", "temp_c", "rh", "precip")


# --- the picture ---


def png(rgba: NDArray[np.uint8]) -> bytes:
    """An RGBA picture as a PNG file."""
    height, width, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[row].tobytes() for row in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def paint(legend: LayerLegend, values: Floats, width: int, height: int) -> bytes:
    """The picture of a layer: the colour of each value's band, clear for the first band when the layer says so."""
    palette = np.array([(*rgb(b.color), 255) for b in legend.bands], dtype=np.uint8)
    if legend.clear_first_band:
        palette[0, 3] = 0
    out = palette[legend.band_of(np.nan_to_num(values))]
    out[np.isnan(values), 3] = 0  # no value: nothing is drawn
    return png(out.reshape(height, width, 4))


def resample(plane: NDArray[np.float32], lat0: float, lon0: float, step: float, width: int, height: int) -> NDArray[np.float64]:
    """A global grid `[row, col]` onto a Web Mercator picture (rows spaced in Mercator y), bilinear; a gap (NaN)
    spreads to the pixels around it. Flat, row by row."""
    rows, cols = plane.shape
    lon = -180.0 + (np.arange(width) + 0.5) / width * 360.0
    y = mercator_y(MAX_LAT) - (np.arange(height) + 0.5) / height * 2 * mercator_y(MAX_LAT)
    lat = np.degrees(np.arctan(np.sinh(y)))
    fx = (lon - lon0) / step
    x0 = np.floor(fx).astype(np.int64)
    tx = (fx - x0).astype(np.float32)
    x0, x1 = x0 % cols, (x0 + 1) % cols
    fy = np.clip((lat0 - lat) / step, 0, rows - 1)
    y0 = np.minimum(np.floor(fy).astype(np.int64), rows - 2)
    ty = (fy - y0).astype(np.float32)
    y1 = y0 + 1
    top = plane[np.ix_(y0, x0)] * (1 - tx) + plane[np.ix_(y0, x1)] * tx
    bottom = plane[np.ix_(y1, x0)] * (1 - tx) + plane[np.ix_(y1, x1)] * tx
    return (top * (1 - ty)[:, None] + bottom * ty[:, None]).astype(np.float64).ravel()


def mercator_y(lat: float) -> float:
    return math.asinh(math.tan(math.radians(lat)))


# --- one run ---


@dataclass
class Weather:
    """One run of the weather files:

    `meta.json` gives `run_id`, `built_at`, `source`, `grid` (`lat0` and `lon0` of cell (0, 0), `step`, `rows`,
    `cols`), `times` (UTC, three hours apart), `analysis_until` and `variables` (`scale`, `file`). Each file is int16
    `[time, row, col]`, row 0 at `lat0` (the north), value = quantity / scale, -32768 for a gap (read as 0).
    """

    run_id: str
    built_at: datetime
    analysis_until: datetime
    source: str
    lat0: float
    lon0: float
    step: float
    rows: int
    cols: int
    times: NDArray[np.int64]  # ms
    arrays: dict[str, tuple[Any, float]]
    _pictures: OrderedDict[tuple[str, int], bytes] = field(default_factory=OrderedDict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def open(cls, folder: Path) -> Weather:
        meta = json.loads((folder / "meta.json").read_text())
        grid = meta["grid"]
        times = np.array([int(datetime.fromisoformat(t).timestamp() * 1000)
                          for t in meta["times"]], dtype=np.int64)
        if len(times) < 2 or np.any(np.diff(times) <= 0):
            raise ValueError("times must grow")
        arrays = {}
        for name in VARIABLES:
            spec = meta["variables"][name]
            data = np.load(folder / spec["file"], mmap_mode="r")
            if data.shape != (len(times), grid["rows"], grid["cols"]) or data.dtype != np.int16:
                raise ValueError(f"{name}: unexpected shape or type {data.shape} {data.dtype}")
            arrays[name] = (data, float(spec["scale"]))

        def when(text: str) -> datetime:
            return datetime.fromisoformat(text).astimezone(UTC)

        return cls(str(meta["run_id"]), when(meta["built_at"]), when(meta["analysis_until"]), str(meta["source"]),
                   float(grid["lat0"]), float(grid["lon0"]), float(grid["step"]), int(grid["rows"]),
                   int(grid["cols"]), times, arrays)

    # time

    @property
    def start(self) -> datetime:
        return datetime.fromtimestamp(int(self.times[0]) / 1000, UTC)

    @property
    def end(self) -> datetime:
        return datetime.fromtimestamp(int(self.times[-1]) / 1000, UTC)

    @property
    def hours(self) -> int:
        return int((self.times[-1] - self.times[0]) // HOUR_MS) + 1

    def hour_ms(self, moment: datetime | None) -> int:
        """The time asked for in ms; without one, the present hour (kept inside the data). Outside the data: 422."""
        if moment is None:
            now = int(time.time() * 1000) // HOUR_MS * HOUR_MS
            return int(min(max(now, self.times[0]), self.times[-1]))
        ms = int(moment.astimezone(UTC).timestamp() * 1000)
        if not self.times[0] <= ms <= self.times[-1]:
            raise ApiError(422, "validation_error",
                           f"time: the weather is there from {self.start:%Y-%m-%d %H:%M} to {self.end:%Y-%m-%d %H:%M} UTC")
        return ms

    def hourly(self) -> NDArray[np.int64]:
        return self.times[0] + np.arange(self.hours, dtype=np.int64) * HOUR_MS

    def _bracket(self, ms: NDArray[np.int64]) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
        """Step before each time and how far (0 to 1) the time is towards the next step."""
        i = np.clip(np.searchsorted(self.times, ms, side="right") - 1, 0, len(self.times) - 2)
        return i, (ms - self.times[i]) / (self.times[i + 1] - self.times[i])

    # whole planes

    def _plane(self, name: str, step: int) -> NDArray[np.float32]:
        data, scale = self.arrays[name]
        raw = np.asarray(data[step])
        out = raw.astype(np.float32) * np.float32(scale)
        out[raw == MISSING] = 0
        return out

    def field(self, name: str, ms: int) -> NDArray[np.float32]:
        """A variable over the whole grid at a time, `[row, col]`."""
        i, w = self._bracket(np.array([ms], dtype=np.int64))
        step, weight = int(i[0]), float(w[0])
        plane = self._plane(name, step)
        if weight > 0:
            plane = plane * np.float32(1 - weight) + self._plane(name, step + 1) * np.float32(weight)
        return plane

    def layer_values(self, layer: str, ms: int) -> NDArray[np.float32]:
        if layer == "rain":
            return self.field("precip", ms)
        return vpd_kpa(self.field("temp_c", ms), self.field("rh", ms)).astype(np.float32)

    # pictures

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return -180.0, -MAX_LAT, 180.0, MAX_LAT

    def picture_size(self) -> tuple[int, int]:
        width = self.cols * PIXELS_PER_CELL
        height = round(width * (mercator_y(MAX_LAT) * 2) / (2 * math.pi))
        return width, height

    def picture(self, layer: str, ms: int) -> bytes:
        """The PNG of the rain or dryness layer at a time, rows spaced in Web Mercator, one pixel per cell."""
        key = (layer, ms)
        with self._lock:
            if key in self._pictures:
                self._pictures.move_to_end(key)
                return self._pictures[key]
        width, height = self.picture_size()
        values = resample(self.layer_values(layer, ms), self.lat0, self.lon0, self.step, width, height)
        data = paint(RAIN if layer == "rain" else DRYNESS, values, width, height)
        with self._lock:
            self._pictures[key] = data
            while len(self._pictures) > PICTURES_KEPT:
                self._pictures.popitem(last=False)
        return data

    def field_rows(self) -> tuple[int, int]:
        """First and last row of the cells of the wind picture: those whose centre lies within the map's latitudes,
        cut to whole blocks."""
        first = max(math.ceil((self.lat0 - MAX_LAT) / self.step), 0)
        last = min(math.floor((self.lat0 + MAX_LAT) / self.step), self.rows - 1)
        return first, first + (last - first + 1) // WIND_BLOCK * WIND_BLOCK - 1

    def field_size(self) -> tuple[int, int]:
        """Width and height in pixels of the wind picture."""
        first, last = self.field_rows()
        return self.cols // WIND_BLOCK, (last - first + 1) // WIND_BLOCK

    def wind_field(self, ms: int) -> bytes:
        """The wind as a picture, rows from the north: red is the eastward and green the northward wind, 0 to 255 for
        -40 to 40 m/s, the mean over blocks of cells."""
        key = ("wind-field", ms)
        with self._lock:
            if key in self._pictures:
                self._pictures.move_to_end(key)
                return self._pictures[key]
        first, last = self.field_rows()
        width, height = self.field_size()
        pixels = np.zeros((height, width, 4), dtype=np.uint8)
        for channel, name in ((0, "wind_u"), (1, "wind_v")):
            plane = self.field(name, ms)[first:last + 1, :width * WIND_BLOCK]
            mean = plane.reshape(height, WIND_BLOCK, width, WIND_BLOCK).mean(axis=(1, 3))
            pixels[..., channel] = np.clip(np.rint((mean + WIND_RANGE) / (2 * WIND_RANGE) * 255), 0, 255)
        pixels[..., 3] = 255
        data = png(pixels)
        with self._lock:
            self._pictures[key] = data
            while len(self._pictures) > PICTURES_KEPT:
                self._pictures.popitem(last=False)
        return data

    # arrows

    def wind_cells(self, ms: int, zoom: float) -> list[dict[str, Any]]:
        """The wind of the cells to draw at a map zoom: every N-th row and column of the grid."""
        stride = next((n for limit, n in ARROW_STRIDES if zoom <= limit), ARROW_STRIDES[-1][1])
        rows = np.array([r for r in range(0, self.rows, stride) if abs(self.lat0 - r * self.step) <= ARROW_LAT],
                        dtype=np.int64)
        cols = np.arange(0, self.cols, stride)
        ix = np.ix_(rows, cols)
        u, v = self.field("wind_u", ms)[ix].astype(np.float64), self.field("wind_v", ms)[ix].astype(np.float64)
        gust = self.field("gust", ms)[ix].astype(np.float64)
        speed = np.hypot(u, v) * 3.6
        gust = np.maximum(gust * 3.6, speed)
        direction = np.degrees(np.arctan2(-u, -v)) % 360
        band = WIND.band_of(speed)
        lon = self._lon(cols)
        lat = self.lat0 - rows * self.step
        return [{"position": (float(lon[j]), float(lat[i])), "speed_kmh": round(float(speed[i, j]), 1),
                 "gust_kmh": round(float(gust[i, j]), 1), "from_deg": round(float(direction[i, j])) % 360,
                 "category": int(band[i, j]), "color": WIND.bands[int(band[i, j])].color}
                for i in range(len(rows)) for j in range(len(cols))]

    def _lon(self, cols: NDArray[np.int64]) -> Floats:
        lon = self.lon0 + cols * self.step
        return np.where(lon > 180, lon - 360, lon)

    # points

    def series(self, lon: Floats, lat: Floats, ms: NDArray[np.int64]) -> dict[str, Floats]:
        """The weather at points over times, bilinear in space and linear in time: each value is `[point, time]`.

        Only the four cells around each point are read from the files.
        """
        lon, lat = np.atleast_1d(np.asarray(lon, dtype=np.float64)), np.atleast_1d(np.asarray(lat, dtype=np.float64))
        n = len(lon)
        fx = (lon - self.lon0) / self.step
        x0 = np.floor(fx).astype(np.int64)
        tx = fx - x0
        fy = np.clip((self.lat0 - lat) / self.step, 0, self.rows - 1)
        y0 = np.minimum(np.floor(fy).astype(np.int64), self.rows - 2)
        ty = fy - y0
        x0, x1 = x0 % self.cols, (x0 + 1) % self.cols
        rr = np.concatenate([y0, y0, y0 + 1, y0 + 1])
        cc = np.concatenate([x0, x1, x0, x1])
        weight = np.stack([(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty])  # [4, n]
        step, along = self._bracket(np.asarray(ms, dtype=np.int64))

        def read(name: str) -> NDArray[np.float64]:
            data, scale = self.arrays[name]
            raw = np.asarray(data[:, rr, cc])  # [steps, 4n]
            values = np.where(raw == MISSING, 0.0, raw * scale)
            mixed = values[step] * (1 - along)[:, None] + values[step + 1] * along[:, None]
            return mixed.reshape(len(ms), 4, n)  # [time, corner, point]

        u, v, gust, temp, rh, rain = (read(k) for k in VARIABLES)
        speed = np.hypot(u, v) * 3.6

        def blend(a: NDArray[np.float64]) -> Floats:
            return np.einsum("kcn,cn->nk", a, weight)

        east, north = blend(u), blend(v)
        return {"speed": blend(speed), "gust": blend(np.maximum(gust * 3.6, speed)), "rain": blend(rain),
                "humidity": blend(rh), "temperature": blend(temp), "vpd": blend(vpd_kpa(temp, rh)),
                "direction": np.degrees(np.arctan2(-east, -north)) % 360, "u": east, "v": north}


# --- the runs on disk ---


class WeatherSource:
    """The newest published run of a folder (`current`), checked at most once a minute."""

    def __init__(self, folder: Path | None, opener: Callable[[Path], Any] | None = None):
        self.folder = folder
        self.opener = opener or Weather.open
        self._weather: Weather | None = None
        self._checked = -RECHECK_S
        self._lock = threading.Lock()

    def current(self) -> Weather | None:
        if self.folder is None:
            return None
        with self._lock:
            now = time.monotonic()
            if now - self._checked >= RECHECK_S:
                self._checked = now
                self._refresh()
            return self._weather

    def _refresh(self) -> None:
        assert self.folder is not None
        try:
            run = json.loads((self.folder / "meta.json").read_text())["run_id"]
        except (OSError, ValueError, KeyError):
            self._weather = None
            return
        if self._weather is not None and self._weather.run_id == str(run):
            return
        try:
            self._weather = self.opener(self.folder)
        except (OSError, ValueError, KeyError, TypeError):
            pass  # a half-written run: keep the one we have, look again in a minute
