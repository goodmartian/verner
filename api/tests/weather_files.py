"""A small weather run in the layout `senda-pipeline weather` publishes, for tests: a 15 degree grid, hourly steps."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

LAT0, LON0, STEP, ROWS, COLS = 90.0, -180.0, 15.0, 13, 24
START = datetime(2026, 11, 10, 0, tzinfo=UTC)
STEPS = 9  # 0 .. 24 hours, three apart
SCALES = {"wind_u": 0.01, "wind_v": 0.01, "gust": 0.01, "temp_c": 0.01, "rh": 0.01, "precip": 0.001}


def lon_of(col):
    return LON0 + col * STEP


def lat_of(row):
    return LAT0 - row * STEP


def values(step: int) -> dict[str, np.ndarray]:
    """Fields that are linear in space and in the step, so every interpolation has a known answer."""
    row, col = np.meshgrid(np.arange(ROWS), np.arange(COLS), indexing="ij")
    lon, lat = lon_of(col), lat_of(row)
    return {
        "wind_u": 2.0 + lon / 30.0 + step,  # m/s
        "wind_v": -3.0 + lat / 30.0,
        "gust": 9.0 + 0 * lon + step,
        "temp_c": 20.0 + lon / 15.0 + 2 * step,
        "rh": 40.0 + step * 5 + 0 * lat,
        "precip": np.where((step == 4) & (lat > 40), 3.0, 0.0) + 0 * lon,
    }


def write(folder: Path, run_id: str = "run1", gap: bool = False, start: datetime = START) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    cube = {name: np.stack([values(s)[name] for s in range(STEPS)]) for name in SCALES}
    variables = {}
    for name, scale in SCALES.items():
        data = np.rint(cube[name] / scale).astype(np.int16)
        if gap and name == "precip":
            data[:, 0, 0] = -32768
        np.save(folder / f"{name}.npy", data)
        variables[name] = {"units": "x", "scale": scale, "file": f"{name}.npy"}
    meta = {"run_id": run_id, "built_at": "2026-11-10T08:00:00Z", "source": "test",
            "grid": {"lat0": LAT0, "lon0": LON0, "step": STEP, "rows": ROWS, "cols": COLS},
            "times": [(start + timedelta(hours=3 * s)).strftime("%Y-%m-%dT%H:%M:%SZ") for s in range(STEPS)],
            "analysis_until": "2026-11-10T12:00:00Z", "variables": variables}
    (folder / "meta.json").write_text(json.dumps(meta))
    return folder
