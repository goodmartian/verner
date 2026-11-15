from datetime import UTC, datetime

import polars as pl

from senda_pipeline import grid


def _ev(expr: pl.Expr, **cols) -> list:
    return pl.DataFrame(cols).select(expr.alias("x"))["x"].to_list()


def test_cell_id_corners():
    ids = _ev(grid.cell_id(pl.col("lat"), pl.col("lon")), lat=[89.9, -27.4, -90.0], lon=[-179.9, -58.8, 180.0])
    assert ids[0] == 0
    assert ids[1] == 469 * 1440 + 484 == 675844
    assert ids[2] == 719 * 1440 + 1439  # poles and the 180 meridian clamp into the last cell


def test_cell_id_dtype():
    df = pl.DataFrame({"lat": [1.0], "lon": [2.0]}).select(grid.cell_id(pl.col("lat"), pl.col("lon")))
    assert df.schema["cell_id"] == pl.Int32


def test_cell01():
    v = _ev(grid.cell01(pl.col("lat"), pl.col("lon")), lat=[89.995, -27.4], lon=[-179.995, -58.8])
    assert v[0] == 0
    assert v[1] == int((90 + 27.4) * 100) * 36000 + int((180 - 58.8) * 100)


def test_local_solar_shifts_date():
    df = pl.DataFrame({"t": [datetime(2025, 3, 31, 20, 0, tzinfo=UTC)], "lon": [150.0]}).with_columns(
        pl.col("t").dt.cast_time_unit("ms")
    )
    out = df.select(grid.local_dt(pl.col("t"), pl.col("lon")).alias("l"))["l"][0]
    assert (out.year, out.month, out.day, out.hour) == (2025, 4, 1, 6)
    assert grid.month_index(2025, 4) == 25 * 12 + 3
    m = pl.DataFrame({"d": [out.date()]}).select(grid.month_expr(pl.col("d")))["d"][0]
    assert m == grid.month_index(2025, 4)


def test_tile_name():
    v = _ev(grid.tile(pl.col("lat"), pl.col("lon")), lat=[-27.4, 10.0, 0.0], lon=[-58.8, 20.0, -0.1])
    assert v == ["-30_-60", "10_20", "0_-10"]
