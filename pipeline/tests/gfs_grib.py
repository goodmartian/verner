"""A small GRIB2 writer for tests: one message of a lat/lon grid with simple packing.

Real GFS messages are about a megabyte each, so tests build their own: the same sections, the same
template numbers for the grid (3.0) and the packing (5.0), read by the same decoder.
"""

import struct
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray


def _signed(value: float) -> int:
    """GRIB's sign-and-magnitude integer of micro-degrees."""
    micro = round(abs(value) * 1_000_000)
    return micro | 0x80000000 if value < 0 else micro


def _section(number: int, body: bytes) -> bytes:
    return struct.pack(">IB", len(body) + 5, number) + body


@dataclass(frozen=True)
class Layout:
    """Where the grid lies: the first cell (north-west) and the distance between cells, degrees."""

    north: float
    west: float
    step: float


def message(
    values: NDArray[np.float64], cycle: datetime, layout: Layout, decimal: int = 2
) -> bytes:
    """A GRIB2 message of a grid with rows from the north."""
    north, west, step = layout.north, layout.west, layout.step
    rows, columns = values.shape
    scaled = np.rint(values * 10**decimal)
    reference = float(scaled.min())
    packed = (scaled - reference).astype(">u2").tobytes()
    identification = struct.pack(
        ">HHBBBHBBBBBBB", 7, 0, 2, 1, 1, cycle.year, cycle.month, cycle.day, cycle.hour, 0, 0, 0, 1
    )
    grid = struct.pack(
        ">BIBBHBBIBIBIIIIIIIBIIIIB",
        0, rows * columns, 0, 0, 0,
        6, 0, 0, 0, 0, 0, 0,
        columns, rows, 0, 0xFFFFFFFF,
        _signed(north), _signed(west), 48,
        _signed(north - (rows - 1) * step), _signed(west + (columns - 1) * step),
        round(step * 1_000_000), round(step * 1_000_000), 0,
    )  # fmt: skip
    product = struct.pack(
        ">HHBBBBBHBBIBBIBBI", 0, 0, 2, 2, 2, 0, 0, 0, 0, 1, 0, 103, 0, 0, 255, 0, 0
    )
    representation = struct.pack(">IHfHHBB", rows * columns, 0, reference, 0, decimal, 16, 0)
    sections = (
        _section(1, identification)
        + _section(3, grid)
        + _section(4, product)
        + _section(5, representation)
        + _section(6, b"\xff")
        + _section(7, packed)
    )
    total = 16 + len(sections) + 4
    return b"GRIB" + struct.pack(">HBBQ", 0, 0, 2, total) + sections + b"7777"
