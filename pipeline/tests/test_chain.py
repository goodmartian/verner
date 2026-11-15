from datetime import date, timedelta

import numpy as np
import polars as pl

from senda_pipeline import chain


def dr(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def raw(sensor: str, start: date, n: int, rows=1000, overrides=None, source="sp") -> pl.DataFrame:
    overrides = overrides or {}
    ds = dr(start, n)
    return pl.DataFrame(
        {
            "utc_date": ds,
            "sensor": sensor,
            "source": source,
            "rows": [overrides.get(d, rows) for d in ds],
        },
        schema={"utc_date": pl.Date, "sensor": pl.String, "source": pl.String, "rows": pl.Int64},
    )


def days(*rows: tuple[date, str, bool], source="sp") -> pl.DataFrame:
    return pl.DataFrame(
        [{"utc_date": d, "sensor": s, "rows": 1000, "ok": ok, "source": source} for d, s, ok in rows]
    )


def chosen(df: pl.DataFrame) -> dict:
    return {r["utc_date"]: r["sensor"] for r in df.filter(pl.col("chosen")).to_dicts()}


def test_low_day_flagged():
    d = date(2018, 5, 1)
    out = chain.mark_ok(raw("viirs_noaa20", date(2018, 4, 1), 60, overrides={d: 300}))
    assert out.filter(~pl.col("ok"))["utc_date"].to_list() == [d]


def test_zero_rows_inside_life_are_low_and_outside_life_not_ok():
    # S-NPP: no row on 2022-08-02 inside its life -> rows 0, not ok; rows after retirement -> not ok
    base = raw("viirs_snpp", date(2022, 7, 1), 60)
    base = base.filter(pl.col("utc_date") != date(2022, 8, 2))
    out = chain.mark_ok(base).filter(pl.col("utc_date").is_between(date(2022, 7, 1), date(2022, 8, 29)))
    assert out.filter(~pl.col("ok"))["utc_date"].to_list() == [date(2022, 8, 2)]
    late = chain.mark_ok(raw("viirs_snpp", date(2026, 10, 20), 20))
    assert late.filter(pl.col("utc_date") >= date(2026, 11, 2))["ok"].sum() == 0
    assert late.filter(pl.col("utc_date") == date(2026, 11, 1))["ok"][0]


def test_few_neighbours_ok_when_rows_positive():
    out = chain.mark_ok(raw("modis_aqua", date(2002, 7, 4), 5))
    assert out["ok"].all()


def test_chain_before_2012_is_aqua():
    d = date(2011, 12, 1)
    out = chain.choose(days((d, "modis_aqua", True), (d, "viirs_snpp", True)))
    assert chosen(out) == {d: "modis_aqua"}


def test_terra_only_before_the_first_aqua_date():
    before, first = chain.AQUA_START - timedelta(days=1), chain.AQUA_START
    out = chain.choose(days((before, "modis_terra", True), (first, "modis_terra", True), (first, "modis_aqua", True)))
    assert chosen(out) == {before: "modis_terra", first: "modis_aqua"}
    # Terra never stands in for a low sensor from that date on
    later = [date(2002, 7, 4), date(2008, 3, 1), date(2015, 5, 5), date(2026, 11, 5)]
    out = chain.choose(days(*[(d, s, s == "modis_terra") for d in later for s in ("modis_terra", "modis_aqua", "viirs_snpp", "viirs_noaa20")]))
    assert chosen(out) == {}


def test_terra_life_and_chain_after_aqua_unchanged():
    rows = pl.concat([raw("modis_terra", date(2000, 11, 1), 700), raw("modis_aqua", date(2002, 7, 4), 400)])
    out = chain.choose(chain.mark_ok(rows))
    got = chosen(out)
    assert min(got) == date(2000, 11, 1) == chain.SERIES_START
    assert {s for d, s in got.items() if d < chain.AQUA_START} == {"modis_terra"}
    assert {s for d, s in got.items() if d >= chain.AQUA_START} == {"modis_aqua"}
    # the same dates without Terra: the same choice from the first Aqua date
    alone = chosen(chain.choose(chain.mark_ok(raw("modis_aqua", date(2002, 7, 4), 400))))
    assert {d: s for d, s in got.items() if d >= chain.AQUA_START} == alone


def test_chain_prefers_snpp():
    d = date(2020, 6, 1)
    out = chain.choose(days((d, "modis_aqua", True), (d, "viirs_noaa20", True), (d, "viirs_snpp", True)))
    assert chosen(out) == {d: "viirs_snpp"}


def test_chain_falls_to_noaa20_when_snpp_low():
    d = date(2022, 8, 1)
    out = chain.choose(days((d, "modis_aqua", True), (d, "viirs_noaa20", True), (d, "viirs_snpp", False)))
    assert chosen(out) == {d: "viirs_noaa20"}


def test_chain_falls_to_aqua_before_noaa20():
    d = date(2015, 5, 5)
    rows = pl.concat(
        [
            raw("viirs_snpp", date(2015, 4, 5), 60, overrides={d: 100}),
            raw("viirs_noaa20", date(2015, 4, 5), 60),  # before the life of NOAA-20: never ok
            raw("modis_aqua", date(2015, 4, 5), 60, rows=300),
        ]
    )
    out = chain.choose(chain.mark_ok(rows))
    got = chosen(out)
    assert got[d] == "modis_aqua"
    assert got[d + timedelta(days=1)] == "viirs_snpp"


def test_snpp_not_chosen_from_retirement():
    ds = dr(date(2026, 10, 28), 8)
    forced = days(*[(d, s, True) for d in ds for s in ("viirs_snpp", "viirs_noaa20", "modis_aqua")])
    got = chosen(chain.choose(forced))
    assert got[date(2026, 11, 1)] == "viirs_snpp"
    assert all(got[d] == "viirs_noaa20" for d in ds if d >= date(2026, 11, 2))
    aqua_only = days(*[(d, s, True) for d in ds for s in ("viirs_snpp", "modis_aqua")])
    assert chosen(chain.choose(aqua_only))[date(2026, 11, 3)] == "modis_aqua"


def test_gap_when_all_low():
    ds = dr(date(2020, 6, 1), 10)
    bad = date(2020, 6, 5)
    df = days(*[(d, s, d != bad) for d in ds for s in ("viirs_snpp", "viirs_noaa20", "modis_aqua")])
    out = chain.choose(df)
    assert chain.gap_dates(out) == [bad]
    assert chain.incomplete_months(out, date(2020, 6, 1), date(2020, 6, 10)) == ["2020-06"]


def test_month_complete_needs_edge_days():
    ds = [d for d in dr(date(2025, 4, 1), 154) if d != date(2025, 6, 30)]  # through 2025-09-01
    out = chain.choose(days(*[(d, "viirs_snpp", True) for d in ds]))
    assert chain.incomplete_months(out, date(2025, 5, 1), date(2025, 8, 31)) == ["2025-06", "2025-07"]
    # May needs 2025-04-30, which exists here; June and July both touch the missing 06-30
    assert chain.gap_dates(out) == [date(2025, 6, 30)]


def test_last_nrt_date_is_partial():
    ds = dr(date(2026, 1, 1), 5)
    out = chain.choose(days(*[(d, "viirs_noaa20", True) for d in ds], source="nrt"))
    assert max(chosen(out)) == date(2026, 1, 4)
    assert chain.last_complete_date(out) == date(2026, 1, 3)
    sp = chain.choose(days(*[(d, "viirs_noaa20", True) for d in ds], source="sp"))
    assert max(chosen(sp)) == date(2026, 1, 5)


def test_one_chosen_per_date():
    rng = np.random.default_rng(7)
    ds = dr(date(2013, 1, 1), 200)
    rows = [
        (d, s, bool(rng.random() < 0.6)) for d in ds for s in ("viirs_snpp", "viirs_noaa20", "modis_aqua")
    ]
    out = chain.choose(days(*rows))
    per_date = out.group_by("utc_date").agg(pl.col("chosen").sum().alias("n"), pl.col("ok").any().alias("any_ok"))
    assert per_date["n"].max() == 1
    # every date with an ok sensor in its chain has one
    assert per_date.filter(pl.col("any_ok") & (pl.col("n") == 0)).is_empty()
    assert out.filter(pl.col("chosen") & ~pl.col("ok")).is_empty()


def test_days_cli_drops_masked_nrt_and_writes_files(tmp_path):
    from senda_pipeline import days_cli

    work = tmp_path
    d1, d2, d3 = date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)
    pl.DataFrame(
        {"utc_date": [d1, d2, d3], "sensor": "viirs_noaa20", "source": ["sp", "nrt", "nrt"], "rows": [100, 100, 100]}
    ).write_parquet(work / "days_raw.parquet")
    pl.DataFrame(
        {"sensor": ["viirs_noaa20"] * 2, "year": [2025, 2024], "cell01": [7, 7], "n": [1, 1]}
    ).write_parquet(work / "static_counts.parquet")
    pl.DataFrame({"utc_date": [d2], "sensor": "viirs_noaa20", "cell01": [7], "n": [30]}).write_parquet(
        work / "nrt_cells.parquet"
    )
    days_cli.run(work)
    days = pl.read_parquet(work / "days.parquet")
    assert days.columns == ["utc_date", "sensor", "rows", "ok", "chosen", "source"]
    assert days.schema["rows"] == pl.Int32
    assert days.filter(pl.col("utc_date") == d2)["rows"][0] == 70
    assert d3 not in days["utc_date"].to_list()  # the open last day is not published
    assert pl.read_parquet(work / "static_mask.parquet").to_dicts() == [{"sensor": "viirs_noaa20", "cell01": 7}]
    assert (work / "days_report.json").exists()
