import csv
import io
from datetime import date

import numpy as np
import polars as pl
import pyarrow.parquet as pq

from senda_api import areas, export

HEADER = "latitude,longitude,acq_datetime_utc,local_solar_date,sensor,frp_mw,confidence,daynight,source,harmonized_weight"
MONTHLY_HEADER = ("month,count,median,mean,ratio,level,partial,converted,expected_error,lo,hi,modis_aqua,viirs_snpp,"
                  "viirs_noaa20,sensors")
TWO_CELLS = {"bbox": [20.0, 9.75, 20.5, 10.0]}
POLYGON = {"polygon": {"type": "Polygon", "coordinates": [[[20.0, 9.75], [20.1, 9.75], [20.1, 9.85], [20.0, 9.85],
                                                          [20.0, 9.75]]]}}


class Csv:
    """The hotspot file of an area, as the export writes it."""

    def __init__(self, store, area, **kw):
        self.area = areas.parse(area, store)
        self.text = b"".join(export.hotspots(store, self.area, kw.get("from"), kw.get("to"))).decode()


def post_csv(store, _path, area, **kw):
    return Csv(store, area, **kw)


def parse(res):
    return list(csv.DictReader(io.StringIO(res.text, newline="")))


def truth_rows(data_dir, bbox, first: date, last: date) -> pl.DataFrame:
    w, s, e, n = bbox
    df = pl.read_parquet(data_dir / "rows" / "year=*" / "tile=*" / "part-0.parquet")
    return df.filter(
        (pl.col("local_date") >= first) & (pl.col("local_date") <= last)
        & (pl.col("lon") >= w) & (pl.col("lon") <= e) & (pl.col("lat") >= s) & (pl.col("lat") <= n)
    )


def test_hotspots_csv_header_and_rows(store, data_dir):
    res = post_csv(store, "hotspots.csv", TWO_CELLS, **{"from": "2015-07", "to": "2016-06"})
    assert res.text.split("\r\n")[0] == HEADER
    rows = parse(res)
    area = areas.parse(TWO_CELLS, store)
    assert len(rows) == export.count_rows(store, area, "2015-07", "2016-06")
    truth = truth_rows(data_dir, TWO_CELLS["bbox"], date(2015, 7, 1), date(2016, 6, 30))
    assert len(rows) == len(truth) > 0
    assert res.text.endswith("\r\n") and "\n" not in res.text.replace("\r\n", "")
    first = rows[0]
    assert len(first["acq_datetime_utc"]) == 20 and first["acq_datetime_utc"].endswith("Z")
    assert len(first["latitude"].split(".")[1]) == 5 and len(first["harmonized_weight"].split(".")[1]) == 4
    assert [r["acq_datetime_utc"] for r in rows] == sorted(r["acq_datetime_utc"] for r in rows)


def test_point_in_area_not_cell(store):
    res = post_csv(store, "hotspots.csv", POLYGON, **{"from": "2005-07", "to": "2005-07"})
    rows = parse(res)
    assert len(rows) == 3  # 3 of the 15 fires of cell A lie inside the polygon, the rest only inside the cell
    assert {(r["latitude"], r["longitude"]) for r in rows} == {("9.80000", "20.05000")}


def test_weight_one_for_snpp_and_k_for_aqua(store):
    old = parse(post_csv(store, "hotspots.csv", {"bbox": [20.0, 9.75, 20.25, 10.0]}, **{"from": "2005-07", "to": "2005-07"}))
    assert len(old) == 15 and {r["sensor"] for r in old} == {"modis_aqua"}
    assert {r["harmonized_weight"] for r in old} == {"4.0000"}
    snpp = parse(post_csv(store, "hotspots.csv", {"bbox": [20.0, 9.75, 20.25, 10.0]}, **{"from": "2015-07", "to": "2015-07"}))
    assert len(snpp) == 7 and {r["sensor"] for r in snpp} == {"viirs_snpp"} and {r["harmonized_weight"] for r in snpp} == {"1.0000"}
    recent = parse(post_csv(store, "hotspots.csv", {"bbox": [20.0, 9.75, 20.25, 10.0]}, **{"from": "2022-03", "to": "2022-03"}))
    assert {r["harmonized_weight"] for r in recent if r["sensor"] == "modis_aqua"} == {"3.0000"}  # the recent window


def test_noaa20_weight_by_kgroup(store):
    rows = parse(post_csv(store, "hotspots.csv", {"id": "XA"}, **{"from": "2026-11", "to": "2026-11"}))
    noaa = [r for r in rows if r["sensor"] == "viirs_noaa20"]
    assert noaa and {r["sensor"] for r in rows} == {"viirs_snpp", "viirs_noaa20"}
    for r in noaa:
        assert r["harmonized_weight"] == ("0.8750" if float(r["longitude"]) < 21.25 else "1.1250")


def test_weights_sum_to_calendar_count(client, store):
    cal = client.post("/api/calendar", json={"area": TWO_CELLS}).json()
    rows = parse(post_csv(store, "hotspots.csv", TWO_CELLS))
    sums: dict[str, float] = {}
    for r in rows:
        sums[r["local_solar_date"][:7]] = sums.get(r["local_solar_date"][:7], 0.0) + float(r["harmonized_weight"])
    for e in [e for e in cal["series"] if e["kind"] != "forecast"]:
        assert abs(sums.get(e["month"], 0.0) - e["count"]) <= 0.5 + 1e-6, e["month"]


def test_empty_area_gives_header_only(store):
    res = post_csv(store, "hotspots.csv", {"bbox": [22.25, 9.0, 22.5, 9.25]})
    assert res.text == HEADER + "\r\n"


def test_count_rows_reads_only_needed_files(store, monkeypatch):
    seen = []
    real = export._files

    def spy(*a, **k):
        out = real(*a, **k)
        seen.extend(out)
        return out

    monkeypatch.setattr(export, "_files", spy)
    export.count_rows(store, areas.parse(TWO_CELLS, store), "2015-07", "2015-08")
    assert seen and all("year=2015" in str(p) for p in seen)


def test_a_count_past_its_limit_stops_and_one_under_it_is_exact(store, monkeypatch):
    area = areas.parse({"id": "XA"}, store)
    exact = export.count_rows(store, area, None, None)
    files = len(export._files(store, area, *export._date_range(store, None, None)))
    assert files > 1 and exact > 1
    assert export.count_rows(store, area, None, None, stop_over=exact) == exact  # at the limit: counted to the end
    read = []
    real = export._chunks

    def spy(*args, **kwargs):
        for df in real(*args, **kwargs):
            read.append(len(df))
            yield df

    monkeypatch.setattr(export, "_chunks", spy)
    period = export._date_range(store, None, None)
    first = next(df for df in real(store, area, *period, ["lat", "lon", "local_date"]) if len(df)).height
    stopped = export.count_rows(store, area, None, None, stop_over=0)
    assert stopped == first < exact and len(read) < files  # it stopped at the first file past the limit


def _no_footers(*_, **__):
    raise AssertionError("the footers were read")


def test_the_world_over_many_years_is_refused_from_the_footers_alone(store, monkeypatch):
    world = areas.parse({"id": areas.WORLD_ID}, store)
    first, last = export._date_range(store, None, None)
    assert last.year - first.year >= 2  # the fixture has inner years
    inner = sum(pq.read_metadata(p).num_rows
                for p in export._files(store, world, date(first.year + 1, 1, 1), date(last.year - 1, 12, 31)))
    assert inner > 1

    def no_data(*_, **__):
        raise AssertionError("the data were read")

    monkeypatch.setattr(export, "_chunks", no_data)
    got = export.count_rows(store, world, None, None, stop_over=inner - 1)
    assert inner - 1 < got <= inner  # a lower bound past the limit, and no file's data was read


def test_the_world_of_one_or_two_years_and_a_country_are_counted_from_the_data(store, monkeypatch):
    world = areas.parse({"id": areas.WORLD_ID}, store)
    year = export._date_range(store, None, None)[0].year + 1
    periods = [(f"{year}-01", f"{year}-12"), (f"{year}-01", f"{year + 1}-12")]
    exact = [export.count_rows(store, world, *p) for p in periods]
    monkeypatch.setattr(export.pq, "read_metadata", _no_footers)
    assert [export.count_rows(store, world, *p, stop_over=10**9) for p in periods] == exact  # no inner year
    assert all(n > 0 for n in exact)
    export.count_rows(store, areas.parse({"id": "XA"}, store), None, None, stop_over=0)  # a country: no footers


def test_no_nan_in_hotspot_rows(store):
    text = post_csv(store, "hotspots.csv", {"id": "XA"}, **{"from": "2010-01", "to": "2010-12"}).text
    assert "nan" not in text.lower() and "inf" not in text.lower()
    assert np.isfinite([float(r["harmonized_weight"]) for r in csv.DictReader(io.StringIO(text))]).all()


def test_file_name_has_the_area_the_period_and_the_data_version(store):
    def name(area, first, last):
        return export.file_name(store, areas.parse(area, store), first, last)

    assert name({"id": "XA"}, 12 * 5 + 6, 12 * 5 + 6).startswith("verner_xa_")
    assert name({"id": "XA-W"}, 36, 40).isascii()
    assert name(POLYGON, 36, 40).startswith("verner_drawn-")
    assert name({"point": {"lat": 9.5, "lon": 21.0}, "radius_km": 30}, 36, 40).startswith("verner_pt-9.5_21_r30km_")
    assert name({"id": "XA"}, 36, 40).endswith("_test-1.csv")
