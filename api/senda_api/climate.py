"""Monthly climate of the world from ERA5: temperature and rain on a 0.5 degree grid, read from memory-mapped files.

The files are made by `senda-pipeline climate`: `meta.json` (`run_id`, `grid`, `first_month`, `last_data_month`,
`normal` years, `variables` with `scale` and `file`) and int16 arrays `[month, row, col]` from the first month
(row 0 at `lat0`, column 0 at `lon0`, -32768 for a gap) with a normal `[12, row, col]` of each variable.

The layers show the deviation from the normal of the calendar month: degrees for temperature, a ratio for rain.
Pictures are drawn like the weather layers (`weather.resample`, `weather.paint`).
"""

from __future__ import annotations

import json
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from numpy.typing import NDArray

from .areas import Area
from .weather import MAX_LAT, MISSING, PICTURES_KEPT, mercator_y, paint, resample
from .weather_legend import Band, LayerLegend, Names

PIXELS_PER_CELL = 1
RAIN_NORMAL_MIN_MM = 5.0  # a normal this small or smaller gives no ratio
AREAS_KEPT = 64

TEMPERATURE = LayerLegend(
    layer="temperature",
    unit="°C",
    name=Names("Temperature", "Температура", "Temperatura"),
    description=Names(
        "How much warmer or colder the month was than its normal (1993-2016)",
        "Насколько месяц был теплее или холоднее своей нормы (1993-2016)",
        "Cuánto más cálido o frío fue el mes que su normal (1993-2016)",
    ),
    bands=(
        Band(0, -100, Names("Much colder", "Намного холоднее", "Mucho más frío"), "#2c5aa0"),
        Band(1, -3, Names("Colder", "Холоднее", "Más frío"), "#7fa6d9"),
        Band(2, -1, Names("Normal", "Норма", "Normal"), "#f3f1e7"),
        Band(3, 1, Names("Warmer", "Теплее", "Más cálido"), "#f2b36b"),
        Band(4, 3, Names("Much warmer", "Намного теплее", "Mucho más cálido"), "#d9602b"),
        Band(5, 5, Names("Extremely warmer", "Аномально теплее", "Extremadamente más cálido"), "#a8201a"),
    ),
    opacity=0.6,
)

RAIN = LayerLegend(
    layer="rain",
    unit="×",
    name=Names("Rain", "Осадки", "Lluvia"),
    description=Names(
        "Rain of the month against its normal (1993-2016); where the normal is 5 mm or less nothing is drawn",
        "Осадки месяца относительно нормы (1993-2016); где норма не больше 5 мм, ничего не рисуется",
        "Lluvia del mes respecto a su normal (1993-2016); donde la normal es de 5 mm o menos no se dibuja nada",
    ),
    bands=(
        Band(0, 0, Names("Much drier", "Намного суше", "Mucho más seco"), "#a8741a"),
        Band(1, 0.5, Names("Drier", "Суше", "Más seco"), "#e0b872"),
        Band(2, 0.8, Names("Normal", "Норма", "Normal"), "#f3f1e7"),
        Band(3, 1.25, Names("Wetter", "Влажнее", "Más húmedo"), "#8fc3e8"),
        Band(4, 2, Names("Much wetter", "Намного влажнее", "Mucho más húmedo"), "#3b7fc4"),
    ),
    opacity=0.6,
)

LAYERS = {"temperature": TEMPERATURE, "rain": RAIN}
VARIABLE = {"temperature": "temp_c", "rain": "rain_mm"}


@dataclass
class Climate:
    run_id: str
    built_at: str
    source: str
    attribution: str
    first_year: int
    first_month: int
    last_year: int
    last_month: int  # the newest month with data
    normal_years: tuple[int, int]
    lat0: float
    lon0: float
    step: float
    rows: int
    cols: int
    series: dict[str, tuple[Any, float]]  # name: ([month, row, col] int16, scale)
    normals: dict[str, tuple[Any, float]]  # name: ([12, row, col] int16, scale)
    _pictures: OrderedDict[tuple[str, str], bytes] = field(default_factory=OrderedDict, repr=False)
    _areas: OrderedDict[tuple, tuple[NDArray, NDArray, NDArray]] = field(default_factory=OrderedDict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def open(cls, folder: Path) -> Climate:
        meta = json.loads((folder / "meta.json").read_text())
        grid = meta["grid"]
        fy, fm = (int(x) for x in meta["first_month"].split("-"))
        ly, lm = (int(x) for x in meta["last_data_month"].split("-"))
        months = int(meta["months"])
        series, normals = {}, {}
        for name, spec in meta["variables"].items():
            data = np.load(folder / spec["file"], mmap_mode="r")
            norm = np.load(folder / spec["normal_file"], mmap_mode="r")
            if data.shape != (months, grid["rows"], grid["cols"]) or data.dtype != np.int16:
                raise ValueError(f"{name}: unexpected shape or type {data.shape} {data.dtype}")
            if norm.shape != (12, grid["rows"], grid["cols"]) or norm.dtype != np.int16:
                raise ValueError(f"{name}: unexpected normal {norm.shape} {norm.dtype}")
            series[name] = (data, float(spec["scale"]))
            normals[name] = (norm, float(spec["scale"]))
        normal = meta["normal"]
        return cls(str(meta["run_id"]), str(meta["built_at"]), str(meta["source"]), str(meta["attribution"]), fy, fm, ly,
                   lm, (int(normal["first_year"]), int(normal["last_year"])), float(grid["lat0"]), float(grid["lon0"]),
                   float(grid["step"]), int(grid["rows"]), int(grid["cols"]), series, normals)

    # months

    @property
    def first_label(self) -> str:
        return f"{self.first_year:04d}-{self.first_month:02d}"

    @property
    def last_label(self) -> str:
        return f"{self.last_year:04d}-{self.last_month:02d}"

    def index(self, label: str) -> int | None:
        """The month's place in the arrays; None outside the months with data."""
        year, month = int(label[:4]), int(label[5:7])
        i = (year - self.first_year) * 12 + month - self.first_month
        last = (self.last_year - self.first_year) * 12 + self.last_month - self.first_month
        return i if 0 <= i <= last else None

    # planes

    def plane(self, variable: str, i: int) -> NDArray[np.float32]:
        """A variable over the grid in a month, `[row, col]`; NaN for a gap."""
        data, scale = self.series[variable]
        raw = np.asarray(data[i])
        out = raw.astype(np.float32) * np.float32(scale)
        out[raw == MISSING] = np.nan
        return out

    def normal_plane(self, variable: str, month: int) -> NDArray[np.float32]:
        data, scale = self.normals[variable]
        raw = np.asarray(data[month - 1])
        out = raw.astype(np.float32) * np.float32(scale)
        out[raw == MISSING] = np.nan
        return out

    def deviation(self, layer: str, label: str) -> NDArray[np.float32] | None:
        """What a layer shows: degrees above the normal, or the ratio to the normal rain (NaN where it is too dry)."""
        i = self.index(label)
        if i is None:
            return None
        variable, month = VARIABLE[layer], int(label[5:7])
        value, normal = self.plane(variable, i), self.normal_plane(variable, month)
        if layer == "temperature":
            return value - normal
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(normal > RAIN_NORMAL_MIN_MM, value / normal, np.nan).astype(np.float32)

    # pictures

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return -180.0, -MAX_LAT, 180.0, MAX_LAT

    def picture_size(self) -> tuple[int, int]:
        width = self.cols * PIXELS_PER_CELL
        return width, round(width * (mercator_y(MAX_LAT) * 2) / (2 * math.pi))

    def picture(self, layer: str, label: str) -> bytes | None:
        key = (layer, label)
        with self._lock:
            if key in self._pictures:
                self._pictures.move_to_end(key)
                return self._pictures[key]
        plane = self.deviation(layer, label)
        if plane is None:
            return None
        width, height = self.picture_size()
        data = paint(LAYERS[layer], resample(plane, self.lat0, self.lon0, self.step, width, height), width, height)
        with self._lock:
            self._pictures[key] = data
            while len(self._pictures) > PICTURES_KEPT:
                self._pictures.popitem(last=False)
        return data

    # areas

    def cells_of(self, area: Area) -> tuple[NDArray, NDArray, NDArray]:
        """Rows, columns and weights (cos of the latitude) of the grid nodes inside an area; the node nearest to
        its centre when no node falls inside."""
        key = (area.id or area.slug, round(area.area_km2, 3))
        with self._lock:
            if key in self._areas:
                self._areas.move_to_end(key)
                return self._areas[key]
        west, south, east, north = area.bbox
        r0 = max(0, int(np.floor((self.lat0 - north) / self.step)))
        r1 = min(self.rows - 1, int(np.ceil((self.lat0 - south) / self.step)))
        c0, c1 = int(np.floor((west - self.lon0) / self.step)), int(np.ceil((east - self.lon0) / self.step))
        rows = np.arange(r0, r1 + 1)
        cols = np.arange(max(0, c0), min(self.cols - 1, c1) + 1)
        rr, cc = np.meshgrid(rows, cols, indexing="ij")
        lat = self.lat0 - rr.ravel() * self.step
        lon = self.lon0 + cc.ravel() * self.step
        inside = shapely.contains_xy(area.geometry, lon, lat)
        if not inside.any():
            centre = area.geometry.centroid
            rr = np.array([[min(self.rows - 1, max(0, round((self.lat0 - centre.y) / self.step)))]])
            cc = np.array([[min(self.cols - 1, max(0, round((centre.x - self.lon0) / self.step)))]])
            inside = np.array([True])
            lat = self.lat0 - rr.ravel() * self.step
        found = (rr.ravel()[inside], cc.ravel()[inside], np.cos(np.radians(lat[inside])))
        with self._lock:
            self._areas[key] = found
            while len(self._areas) > AREAS_KEPT:
                self._areas.popitem(last=False)
        return found

    def area_series(self, variable: str, area: Area) -> NDArray[np.float64]:
        """The mean of a variable over an area for every month of the arrays, weighted by cell size; NaN for a gap."""
        r, c, w = self.cells_of(area)
        data, scale = self.series[variable]
        raw = np.asarray(data[:, r, c], dtype=np.float64)
        ok = raw != MISSING
        weight = np.where(ok, w[None, :], 0.0)
        total = weight.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(total > 0, (np.where(ok, raw, 0.0) * weight).sum(axis=1) / total, np.nan)
        return mean * scale

    def area_normal(self, variable: str, month: int, area: Area) -> float | None:
        r, c, w = self.cells_of(area)
        data, scale = self.normals[variable]
        raw = np.asarray(data[month - 1, r, c], dtype=np.float64)
        ok = raw != MISSING
        if not ok.any():
            return None
        return float((raw[ok] * w[ok]).sum() / w[ok].sum() * scale)
