"""Synthetic WorldCover tiles and a fetcher that answers from them, without the network."""

import re
import struct
import zlib
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from senda_api.landcover import FetchError


@dataclass
class Level:
    """One resolution level of a synthetic GeoTIFF."""

    pixels: NDArray[np.uint8]
    pixel_deg: float
    tile: int = 64


def make_cog(levels: list[Level], origin: tuple[float, float]) -> bytes:
    """A little-endian classic GeoTIFF with deflate tiles and horizontal differencing."""
    packed: list[list[bytes]] = []
    for level in levels:
        h, w = level.pixels.shape
        t = level.tile
        padded = np.zeros((-(-h // t) * t, -(-w // t) * t), dtype=np.uint8)
        padded[:h, :w] = level.pixels
        tiles = []
        for ty in range(0, padded.shape[0], t):
            for tx in range(0, padded.shape[1], t):
                block = padded[ty : ty + t, tx : tx + t].astype(np.int16)
                diff = np.concatenate([block[:, :1], np.diff(block, axis=1) % 256], axis=1)
                tiles.append(zlib.compress(diff.astype(np.uint8).tobytes()))
        packed.append(tiles)
    entries = 10
    ifd_size = 2 + entries * 12 + 4
    out_of_line = [8 + ifd_size * len(levels)]
    blobs: list[bytes] = []

    def place(data: bytes) -> int:
        offset = out_of_line[0]
        blobs.append(data)
        out_of_line[0] += len(data)
        return offset

    level_tags = []
    for i, level in enumerate(levels):
        h, w = level.pixels.shape
        counts = [len(x) for x in packed[i]]
        tile_offsets = []
        for tile in packed[i]:
            tile_offsets.append(place(tile))
        offsets_at = place(struct.pack(f"<{len(tile_offsets)}I", *tile_offsets))
        counts_at = place(struct.pack(f"<{len(counts)}I", *counts))
        scale_at = place(struct.pack("<3d", level.pixel_deg, level.pixel_deg, 0))
        tie_at = place(struct.pack("<6d", 0, 0, 0, origin[0], origin[1], 0))
        n = len(counts)
        level_tags.append(
            [
                (256, 4, 1, w),
                (257, 4, 1, h),
                (317, 3, 1, 2),
                (322, 4, 1, level.tile),
                (323, 4, 1, level.tile),
                (324, 4, n, offsets_at),
                (325, 4, n, counts_at),
                (33550, 12, 3, scale_at),
                (33922, 12, 6, tie_at),
                (259, 3, 1, 8),
            ]
        )
    ifds = b""
    for i, tags in enumerate(level_tags):
        following = 8 + ifd_size * (i + 1) if i + 1 < len(levels) else 0
        body = b"".join(struct.pack("<HHII", *t) for t in sorted(tags))
        ifds += struct.pack("<H", len(tags)) + body + struct.pack("<I", following)
    return b"II*\x00" + struct.pack("<I", 8) + ifds + b"".join(blobs)


def land_cover_pattern(x: int, y: int, shift: int = 0) -> int:
    """The WorldCover class code of the synthetic map at pixel (x, y): blocks of four classes."""
    return ((x // 50 + y // 50 + shift) % 4 + 1) * 10


def land_cover_cog(origin: tuple[float, float], shift: int = 0, size: int = 750) -> bytes:
    """A synthetic 3 degree WorldCover tile: 750 pixels of 0.004 degrees plus an overview."""
    y, x = np.mgrid[0:size, 0:size]
    pixels = (((x // 50 + y // 50 + shift) % 4 + 1) * 10).astype(np.uint8)
    overview = pixels[::2, ::2].copy()
    return make_cog([Level(pixels, 3 / size), Level(overview, 6 / size)], origin)


def origin_of(name: str) -> tuple[float, float]:
    """North-west corner of the tile named by its south-west corner, such as N09E018 or S30W057."""
    ns, lat, ew, lon = re.fullmatch(r"([NS])(\d{2})([EW])(\d{3})", name).groups()
    return (int(lon) * (1 if ew == "E" else -1), int(lat) * (1 if ns == "N" else -1) + 3.0)


class FakeFetcher:
    """Serves range requests of tiles: those in `cogs`, else (with `any_tile`) a synthetic tile of the name asked for."""

    def __init__(self, cogs: dict[str, bytes] | None = None, any_tile: bool = False, failing: bool = False) -> None:
        self.cogs = dict(cogs or {})
        self.any_tile = any_tile
        self.failing = failing
        self.requests: list[str] = []

    def get_range(self, url: str, start: int, length: int) -> bytes:
        self.requests.append(f"{url}@{start}")
        if self.failing:
            raise FetchError("no network")
        name = re.search(r"v200_(\w+)_Map", url).group(1)
        if name not in self.cogs and self.any_tile:
            self.cogs[name] = land_cover_cog(origin_of(name), 0)
        if name not in self.cogs:
            raise FetchError(f"{url}: HTTP 404", 404)
        return self.cogs[name][start:start + length]
