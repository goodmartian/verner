"""Land cover under a fire from ESA WorldCover 2021 (10 m, from Sentinel-1 and Sentinel-2).

The maps are cloud-optimized GeoTIFFs on AWS, free and without a key. Only the needed tiles are read, with HTTP range
requests, from the overview level closest to 80 m, with `httpx` for the network.
A box is read once: the grid is kept in memory and as a small JSON file, the opened tile headers in memory.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import struct
import threading
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np
import shapely
from numpy.typing import NDArray

ATTRIBUTION = "Land cover: ESA WorldCover 2021 © ESA, CC BY 4.0."
NETWORK_TIMEOUT_S = 10.0
MAX_PARALLEL = 4
MAX_BOX_DEG = 3.0
SNAP_DEG = 0.05
"""Boxes are rounded outwards to this grid: a growing fire hits the same cached box."""
MEMORY_GRIDS = 64
MEMORY_TILES = 24
LAND_CLASSES = (
    (0, ("No data", "Нет данных", "Sin datos", "Pas de données"), "#a3a3a3"),
    (1, ("Forest", "Лес", "Bosque", "Forêt"), "#2e7d32"),
    (2, ("Shrubs", "Кустарник", "Arbustos", "Arbustes"), "#c49a22"),
    (3, ("Grass", "Трава", "Pasto", "Herbe"), "#a8c256"),
    (4, ("Crops", "Поля", "Cultivos", "Cultures"), "#d98bd0"),
    (5, ("Built-up", "Застройка", "Urbano", "Zone bâtie"), "#c0392b"),
    (6, ("Bare", "Голая земля", "Suelo desnudo", "Sol nu"), "#a8a29e"),
    (7, ("Snow", "Снег", "Nieve", "Neige"), "#e7e5e4"),
    (8, ("Water", "Вода", "Agua", "Eau"), "#3b82c4"),
    (9, ("Marsh", "Болото", "Bañado", "Marais"), "#138a8a"),
    (10, ("Moss", "Мох", "Musgo", "Mousse"), "#d6c58a"),
)


class FetchError(Exception):
    """A request failed: the service refused it (`status`) or could not be reached (`status` None)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Fetcher(Protocol):
    def get_range(self, url: str, start: int, length: int) -> bytes:
        """GET `length` bytes of a file from byte `start`."""
        ...


class HttpFetcher:
    """Range requests over httpx: 10 s each, at most 4 at a time."""

    def __init__(self, timeout: float = NETWORK_TIMEOUT_S, parallel: int = MAX_PARALLEL) -> None:
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "senda-api/0.1"})
        self._slots = threading.BoundedSemaphore(parallel)

    def get_range(self, url: str, start: int, length: int) -> bytes:
        with self._slots:
            try:
                res = self._client.get(url, headers={"Range": f"bytes={start}-{start + length - 1}"})
            except httpx.HTTPError as error:
                raise FetchError(f"{url}: {error.__class__.__name__}") from error
        if res.status_code == 200:  # the server ignored the range: take the part asked for
            return res.content[start:start + length]
        if res.status_code != 206:
            raise FetchError(f"{url}: HTTP {res.status_code}", res.status_code)
        return res.content


URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
)
TARGET_PIXEL_DEG = 0.0008
HEADER_BYTES = 1 << 20

# TIFF tags
WIDTH, HEIGHT, TILE_WIDTH, TILE_HEIGHT = 256, 257, 322, 323
TILE_OFFSETS, TILE_COUNTS, PREDICTOR = 324, 325, 317
PIXEL_SCALE, TIEPOINT = 33550, 33922
TYPE_FORMATS = {1: "B", 3: "H", 4: "I", 12: "d"}

Tags = dict[int, tuple[float, ...]]


@dataclass(frozen=True)
class LandCoverGrid:
    """Class numbers of a grid of cells, row by row from the north-west corner."""

    width: int
    height: int
    bbox: tuple[float, float, float, float]
    classes: str


class Cog:
    """A cloud-optimized GeoTIFF read through range requests."""

    def __init__(self, fetcher: Fetcher, url: str) -> None:
        self._fetcher = fetcher
        self._url = url
        self._head = fetcher.get_range(url, 0, HEADER_BYTES)
        if self._head[:4] != b"II*\x00":
            raise ValueError(f"{url} is not a little-endian classic TIFF")
        self.levels: list[Tags] = []
        offset = struct.unpack("<I", self._head[4:8])[0]
        while offset:
            tags, offset = self._read_ifd(offset)
            self.levels.append(tags)

    def _read(self, start: int, length: int) -> bytes:
        if start + length <= len(self._head):
            return self._head[start : start + length]
        return self._fetcher.get_range(self._url, start, length)

    def _read_ifd(self, offset: int) -> tuple[Tags, int]:
        count = struct.unpack("<H", self._read(offset, 2))[0]
        raw = self._read(offset + 2, count * 12 + 4)
        tags: Tags = {}
        for i in range(count):
            entry = raw[i * 12 : (i + 1) * 12]
            tag, kind, n = struct.unpack("<HHI", entry[:8])
            if kind not in TYPE_FORMATS:
                continue
            size = struct.calcsize(TYPE_FORMATS[kind]) * n
            data = (
                entry[8 : 8 + size]
                if size <= 4
                else self._read(struct.unpack("<I", entry[8:12])[0], size)
            )
            tags[tag] = struct.unpack(f"<{n}{TYPE_FORMATS[kind]}", data)
        return tags, struct.unpack("<I", raw[count * 12 : count * 12 + 4])[0]

    def window(self, level: int, x0: int, y0: int, width: int, height: int) -> NDArray[np.uint8]:
        """The pixels of a window of one level, as rows."""
        tags = self.levels[level]
        image_width = int(tags[WIDTH][0])
        tile_w, tile_h = int(tags[TILE_WIDTH][0]), int(tags[TILE_HEIGHT][0])
        offsets, counts = tags[TILE_OFFSETS], tags[TILE_COUNTS]
        per_row = math.ceil(image_width / tile_w)
        horizontal_differencing = tags.get(PREDICTOR, (1,))[0] == 2
        out = np.zeros((height, width), dtype=np.uint8)
        for ty in range(y0 // tile_h, (y0 + height - 1) // tile_h + 1):
            for tx in range(x0 // tile_w, (x0 + width - 1) // tile_w + 1):
                k = ty * per_row + tx
                if k >= len(offsets) or not counts[k]:
                    continue
                packed = self._fetcher.get_range(self._url, int(offsets[k]), int(counts[k]))
                tile = np.frombuffer(zlib.decompress(packed), dtype=np.uint8).reshape(
                    tile_h, tile_w
                )
                if horizontal_differencing:
                    tile = np.cumsum(tile, axis=1, dtype=np.uint8)
                top, left = ty * tile_h - y0, tx * tile_w - x0
                rows = slice(max(0, top), min(height, top + tile_h))
                cols = slice(max(0, left), min(width, left + tile_w))
                out[rows, cols] = tile[
                    rows.start - top : rows.stop - top, cols.start - left : cols.stop - left
                ]
        return out


TILE_DEG = 3
MISSING_TILE_STATUSES = frozenset({403, 404})
"""S3 answers 403 or 404 for a tile that does not exist: WorldCover has none over open sea."""


def tile_name(south_west_lat: int, south_west_lon: int) -> str:
    """Name of the WorldCover tile with the given south-west corner, such as S30W057 or N09E012."""
    ns, ew = "N" if south_west_lat >= 0 else "S", "E" if south_west_lon >= 0 else "W"
    return f"{ns}{abs(south_west_lat):02d}{ew}{abs(south_west_lon):03d}"


def _open(fetcher: Fetcher, name: str, cogs: dict[str, Cog | None]) -> Cog | None:
    """The tile, opened once; None when WorldCover has no such tile."""
    if name not in cogs:
        try:
            cogs[name] = Cog(fetcher, URL.format(tile=name))
        except FetchError as error:
            if error.status not in MISSING_TILE_STATUSES:
                raise
            cogs[name] = None
    return cogs[name]


def read_land_cover(
    fetcher: Fetcher, box: tuple[float, float, float, float], cogs: dict[str, Cog | None]
) -> LandCoverGrid:
    """Land cover inside a box (west, south, east, north); `cogs` keeps opened tiles between calls.

    A box that crosses the edge of a 3 degree tile is stitched from the neighbouring tiles. Cells of
    a tile that does not exist (open sea) have class 0, no data.
    """
    west, south, east, north = box
    lons = range(
        math.floor(west / TILE_DEG) * TILE_DEG, math.ceil(east / TILE_DEG) * TILE_DEG, TILE_DEG
    )
    lats = range(
        math.ceil(north / TILE_DEG) * TILE_DEG - TILE_DEG,
        math.floor(south / TILE_DEG) * TILE_DEG - TILE_DEG,
        -TILE_DEG,
    )
    tiles = {(lat, lon): _open(fetcher, tile_name(lat, lon), cogs) for lat in lats for lon in lons}
    reference = next((cog for cog in tiles.values() if cog is not None), None)
    if reference is None:
        raise ValueError(f"WorldCover has no tile for the box {box}")
    base = reference.levels[0]
    level = min(
        range(len(reference.levels)),
        key=lambda i: abs(
            base[WIDTH][0] / reference.levels[i][WIDTH][0] * base[PIXEL_SCALE][0] - TARGET_PIXEL_DEG
        ),
    )
    tile_w, tile_h = int(reference.levels[level][WIDTH][0]), int(reference.levels[level][HEIGHT][0])
    px, py = TILE_DEG / tile_w, TILE_DEG / tile_h
    origin_x, origin_y = float(lons[0]), float(lats[0] + TILE_DEG)
    x0, y0 = int((west - origin_x) / px), int((origin_y - north) / py)
    width = min(int((east - west) / px), len(lons) * tile_w - x0)
    height = min(int((north - south) / py), len(lats) * tile_h - y0)
    grid = np.zeros((height, width), dtype=np.uint8)
    for row, lat in enumerate(lats):
        for col, lon in enumerate(lons):
            cog = tiles[lat, lon]
            left, right = max(x0, col * tile_w), min(x0 + width, (col + 1) * tile_w)
            top, bottom = max(y0, row * tile_h), min(y0 + height, (row + 1) * tile_h)
            if cog is None or left >= right or top >= bottom:
                continue
            grid[top - y0 : bottom - y0, left - x0 : right - x0] = cog.window(
                level, left - col * tile_w, top - row * tile_h, right - left, bottom - top
            )
    classes = (np.minimum(grid, 100) // 10 + 48).astype(np.uint8).tobytes().decode("ascii")
    bbox = (
        origin_x + x0 * px,
        origin_y - (y0 + height) * py,
        origin_x + (x0 + width) * px,
        origin_y - y0 * py,
    )
    return LandCoverGrid(width=width, height=height, bbox=bbox, classes=classes)


def snapped_box(outline: list, pad: float = SNAP_DEG) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    return (
        round(math.floor((min(xs) - pad) / SNAP_DEG) * SNAP_DEG, 2),
        round(math.floor((min(ys) - pad) / SNAP_DEG) * SNAP_DEG, 2),
        round(math.ceil((max(xs) + pad) / SNAP_DEG) * SNAP_DEG, 2),
        round(math.ceil((max(ys) + pad) / SNAP_DEG) * SNAP_DEG, 2),
    )


def shares(grid: dict, outline: list) -> list[dict]:
    """Class, share of the cells inside the outline that have data, in percent; the biggest first."""
    west, south, east, north = grid["bbox"]
    width, height = grid["width"], grid["height"]
    cells = np.frombuffer(grid["classes"].encode("ascii"), dtype=np.uint8).reshape(height, width) - 48
    x = west + (np.arange(width) + 0.5) * (east - west) / width
    y = north - (np.arange(height) + 0.5) * (north - south) / height
    inside = shapely.contains_xy(shapely.Polygon(outline), *np.meshgrid(x, y)) & (cells > 0)
    counts = np.bincount(cells[inside], minlength=len(LAND_CLASSES))
    total = int(counts.sum())
    order = sorted(range(1, len(counts)), key=lambda i: -counts[i])
    return [{"id": i, "share_pct": round(100 * int(counts[i]) / total, 1)} for i in order if counts[i]] if total else []


def along(grid: dict, line: list, top: int = 2) -> list[dict]:
    """The `top` classes a line crosses most, as shares of its points that have data, in percent."""
    west, south, east, north = grid["bbox"]
    width, height = grid["width"], grid["height"]
    cells = np.frombuffer(grid["classes"].encode("ascii"), dtype=np.uint8).reshape(height, width) - 48
    step_x, step_y = (east - west) / width, (north - south) / height
    points = np.asarray(line, dtype=float)
    counts = np.zeros(len(LAND_CLASSES), dtype=int)
    for a, b in itertools.pairwise(points):
        n = max(2, int(max(abs(b[0] - a[0]) / step_x, abs(b[1] - a[1]) / abs(step_y))) + 1)
        xs, ys = np.linspace(a[0], b[0], n), np.linspace(a[1], b[1], n)
        col, row = ((xs - west) / step_x).astype(int), ((north - ys) / abs(step_y)).astype(int)
        ok = (col >= 0) & (col < width) & (row >= 0) & (row < height)
        found = cells[row[ok], col[ok]]
        counts += np.bincount(found[found > 0], minlength=len(LAND_CLASSES))
    total = int(counts.sum())
    order = sorted(range(1, len(counts)), key=lambda i: -counts[i])[:top]
    return [{"id": i, "share_pct": round(100 * int(counts[i]) / total, 1)} for i in order if counts[i]] if total else []


class LandError(Exception):
    """There is no land cover for this place now: no network, no tile, an unreadable file."""


class LandCover:
    """Reads the land cover of boxes; `folder` keeps the grids as JSON between runs (None: memory only)."""

    def __init__(self, folder: Path | None = None, fetcher: Fetcher | None = None) -> None:
        self.folder = folder
        self.fetcher = fetcher or HttpFetcher()
        self._grids: OrderedDict[str, dict] = OrderedDict()
        self._tiles: dict[str, Cog | None] = {}
        self._lock = threading.Lock()

    def read(self, box: tuple[float, float, float, float]) -> dict:
        key = "_".join(f"{v:.2f}" for v in box)
        with self._lock:
            found = self._grids.get(key)
            if found is not None:
                self._grids.move_to_end(key)
                return found
        found = self._from_disk(key)
        if found is None:
            if box[2] - box[0] > MAX_BOX_DEG or box[3] - box[1] > MAX_BOX_DEG:
                raise LandError("The fire is too large for a land cover map.")
            try:
                grid = read_land_cover(self.fetcher, box, self._tiles_kept())
            except FetchError as error:
                raise LandError("The land cover service cannot be reached now.") from error
            except (ValueError, zlib.error, struct.error, IndexError, KeyError) as error:
                raise LandError("There is no land cover here: open sea or an unreadable map.") from error
            found = {"width": grid.width, "height": grid.height, "bbox": list(grid.bbox), "classes": grid.classes}
            self._to_disk(key, found)
        with self._lock:
            self._grids[key] = found
            while len(self._grids) > MEMORY_GRIDS:
                self._grids.popitem(last=False)
        return found

    def _tiles_kept(self) -> dict[str, Cog | None]:
        with self._lock:
            while len(self._tiles) > MEMORY_TILES:
                self._tiles.pop(next(iter(self._tiles)))
            return self._tiles

    def _from_disk(self, key: str) -> dict | None:
        if self.folder is None:
            return None
        try:
            return json.loads((self.folder / f"{key}.json").read_text())
        except (OSError, ValueError):
            return None

    def _to_disk(self, key: str, grid: dict) -> None:
        if self.folder is None:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.folder / f".{key}.{os.getpid()}.tmp"
            tmp.write_text(json.dumps(grid, separators=(",", ":")))
            tmp.replace(self.folder / f"{key}.json")
        except OSError:
            pass  # the cache is a convenience: the answer does not depend on it

    def of_outline(self, outline: list) -> dict:
        """The grid for a fire outline with its legend, shares and source, as the route answers."""
        grid = self.read(snapped_box(outline))
        return {"bbox": grid["bbox"], "width": grid["width"], "height": grid["height"], "data": grid["classes"],
                "classes": [{"id": i, "name": dict(zip(("en", "ru", "es", "fr"), names, strict=True)), "color": color}
                            for i, names, color in LAND_CLASSES],
                "shares": shares(grid, outline), "attribution": ATTRIBUTION}
