import polars as pl

from senda_pipeline import mask


def sc(*rows):
    return pl.DataFrame(rows, schema={"sensor": pl.String, "year": pl.Int32, "cell01": pl.Int64, "n": pl.Int64}, orient="row")


def test_mask_two_of_three_years():
    df = sc(
        ("viirs_snpp", 2023, 1, 5), ("viirs_snpp", 2025, 1, 2),  # two of the last three years: in
        ("viirs_snpp", 2025, 2, 9),  # one year only: out
        ("viirs_snpp", 2021, 3, 4), ("viirs_snpp", 2022, 3, 4),  # old years: out
        ("viirs_snpp", 2024, 4, 1), ("viirs_snpp", 2025, 4, 1),
    )  # fmt: skip
    out = mask.build(df)
    assert out.columns == ["sensor", "cell01"]
    assert out["cell01"].to_list() == [1, 4]


def test_mask_is_per_sensor():
    df = sc(("viirs_snpp", 2024, 7, 1), ("modis_aqua", 2025, 7, 1), ("viirs_snpp", 2025, 8, 1), ("viirs_snpp", 2024, 8, 1))
    out = mask.build(df)
    assert out.to_dicts() == [{"sensor": "viirs_snpp", "cell01": 8}]


def test_mask_empty():
    assert mask.build(sc()).is_empty()
