"""A small climate run in the layout `senda-pipeline climate` publishes, for tests: a 15 degree grid, months from
2024-01 to 2025-06. The temperature is the normal of its month (10 + month) plus half a degree in 2024 and one in 2025.
Rain is 25 mm everywhere against a normal of 50 mm, except 2025-06 with 100 mm."""

import json
from pathlib import Path

import numpy as np

ROWS, COLS, MONTHS = 13, 24, 18
SCALES = {"temp_c": 0.01, "rain_mm": 0.2}


def write(folder: Path, run_id: str = "2025-06", gap_month: int | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    month = np.arange(MONTHS) % 12 + 1
    year = 2024 + np.arange(MONTHS) // 12
    shape = (MONTHS, ROWS, COLS)
    temp = np.broadcast_to((10 + month + 0.5 * (year - 2023))[:, None, None], shape)
    rain = np.broadcast_to(np.where(np.arange(MONTHS) == MONTHS - 1, 100.0, 25.0)[:, None, None], shape)
    normal_temp = np.broadcast_to((10 + np.arange(1, 13))[:, None, None], (12, ROWS, COLS))
    normal_rain = np.full((12, ROWS, COLS), 50.0)
    for name, series, normal in (("temp_c", temp, normal_temp), ("rain_mm", rain, normal_rain)):
        data = np.rint(series / SCALES[name]).astype(np.int16)
        if gap_month is not None:
            data[gap_month] = -32768
        np.save(folder / f"{name}.npy", data)
        np.save(folder / f"normal_{name}.npy", np.rint(normal / SCALES[name]).astype(np.int16))
    meta = {"run_id": run_id, "built_at": "2025-07-10T08:00:00Z", "source": "test", "attribution": "ERA5 test",
            "grid": {"lat0": 90.0, "lon0": -180.0, "step": 15.0, "rows": ROWS, "cols": COLS},
            "first_month": "2024-01", "last_month": "2025-06", "last_data_month": "2025-06", "months": MONTHS,
            "normal": {"first_year": 1993, "last_year": 2016, "months": 12},
            "variables": {n: {"units": "x", "scale": s, "file": f"{n}.npy", "normal_file": f"normal_{n}.npy"}
                          for n, s in SCALES.items()}}
    (folder / "meta.json").write_text(json.dumps(meta))
    return folder
