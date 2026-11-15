"""A version whose series starts in 2000-11 with MODIS Terra: the months before 2003 are shown, every number of the
baseline (medians, normals, ranks, season, trend, expected error, forecast) is the one of the version without them."""

import csv
import io

import fixture
import oracle
import pytest
from fastapi.testclient import TestClient

from senda_api import areas, export
from senda_api.app import create_app
from senda_api.store import Store

POLYGON = {"bbox": [20.1, 9.1, 21.9, 9.9]}
AREAS = [{"id": "XA"}, {"id": "XA-W"}, POLYGON]


@pytest.fixture(scope="module")
def terra_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("senda-terra") / "v1"
    fixture.build(root, terra=True)
    return root


@pytest.fixture(scope="module")
def terra_store(terra_dir):
    return Store.load(terra_dir)


@pytest.fixture(scope="module")
def terra_client(terra_store):
    return TestClient(create_app(store=terra_store))


def calendar(client, area):
    res = client.post("/api/calendar", json={"area": area})
    assert res.status_code == 200, res.text
    return res.json()


def from_2003(body):
    """The answer without its first month and without the series entries and yearly totals before 2003."""
    out = {k: v for k, v in body.items() if k != "first_month"}
    out["series"] = [e for e in body["series"] if e["month"] >= "2003-01"]
    out["yearly"] = [y for y in body["yearly"] if y["year"] >= 2003]
    return out


def test_loads_terra_and_applies_its_factors(terra_store, terra_dir):
    assert terra_store.first_month == fixture.mi(2000, 11)
    assert terra_store.base_years[0] == 2003 and terra_store.base_years[-1] == 2025
    assert terra_store.SER["modis_terra"].sum() > 0
    daily = oracle.load_daily(terra_dir)
    for y, m in ((2001, 7), (2002, 3)):
        rows = [(c, d, s, a, b) for c, d, s, a, b in daily if (d.year, d.month) == (y, m)]
        assert {s for _, _, s, _, _ in rows} == {"modis_terra"}
        for kgroup in (1, 2):  # each group has its own factor
            cells = [c for c in {r[0] for r in rows} if oracle.kgroup(c) == kgroup]
            got = sum(float(terra_store.H[int(terra_store.cells.row_of[c]), fixture.mi(y, m)]) for c in cells)
            want = sum((a + b) * oracle.k(s, c, d) for c, d, s, a, b in rows if c in cells)
            assert cells and got == pytest.approx(want, rel=1e-5)
            assert want == pytest.approx(sum(a + b for c, _, _, a, b in rows if c in cells) * fixture.TERRA_K[kgroup])


@pytest.mark.parametrize("area", AREAS)
def test_calendar_from_2003_is_unchanged(client, terra_client, area):
    old, new = calendar(client, area), calendar(terra_client, area)
    assert new["first_month"] == "2000-11" and new["series"][0]["month"] == "2000-11"
    assert from_2003(new) == from_2003(old)


def test_terra_months_are_converted_and_named(terra_client):
    body = calendar(terra_client, {"id": "XA"})
    months = {e["month"]: e for e in body["series"]}
    early = months["2001-07"]
    assert early["converted"] is True and early["sensors"] == ["modis_terra"]
    assert early["raw"]["modis_terra"] > 0 and early["raw"]["modis_aqua"] == 0
    assert early["of"] == len(fixture_base_years()) + 1  # ranked among the baseline years, not one of them
    assert months["2002-08"]["sensors"] == ["modis_aqua"]
    yearly = {y["year"]: y for y in body["yearly"]}
    assert yearly[2000]["complete"] is False and yearly[2001]["complete"] is True
    assert yearly[2001]["converted"] is True
    assert all(n["years"] == 23 for n in body["normals"])


def fixture_base_years():
    return range(2003, 2026)


@pytest.mark.parametrize("month", ["2024-06", "2026-11", "2001-07"])
def test_month_rank_counts_the_baseline_years(client, terra_client, month):
    new = terra_client.get("/api/calendar/month", params={"area": "XA", "month": month})
    assert new.status_code == 200, new.text
    new = new.json()
    if month < "2003":  # its own value among the years from 2003 on
        same = client.get("/api/calendar/month", params={"area": "XA", "month": "2024-07"}).json()
        assert new["rank"]["of"] == same["rank"]["of"] + 1
        assert new["normal"] == same["normal"]
        return
    old = client.get("/api/calendar/month", params={"area": "XA", "month": month}).json()
    assert new["years"][0]["year"] == (2000 if month[5:] in ("11", "12") else 2001)  # the early years are shown
    new["years"] = [y for y in new["years"] if y["year"] >= 2003]
    assert new == old


@pytest.mark.parametrize("params", [{}, {"from": "2003-01"}, {"from": "2024-01", "to": "2024-12"}])
def test_provinces_unchanged(client, terra_client, params):
    old = client.get("/api/calendar/provinces", params={"area": "XA", **params}).json()
    new = terra_client.get("/api/calendar/provinces", params={"area": "XA", **params}).json()
    assert new == old


def test_whole_archive_from_the_first_month_is_whole(terra_client):
    body = terra_client.get("/api/calendar/provinces", params={"area": "XA", "from": "2000-11", "to": "2026-10"})
    assert body.status_code == 200 and body.json()["whole"] is True


@pytest.mark.parametrize("params", [{}, {"ids": "XA", "years": "2019"}])
def test_world_unchanged(client, terra_client, params):
    assert terra_client.get("/api/world/countries", params=params).json() == \
        client.get("/api/world/countries", params=params).json()


def test_hotspot_export_names_terra_and_weights_it(terra_store):
    area = areas.parse({"id": "XA"}, terra_store)
    text = b"".join(export.hotspots(terra_store, area, "2001-07", "2001-07")).decode()
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    assert rows
    assert {r["sensor"] for r in rows} == {"modis_terra"}
    assert {r["harmonized_weight"] for r in rows} == {"4.5000", "6.0000"}
    assert {r["confidence"] for r in rows} == {"80"}
