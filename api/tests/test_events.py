import pytest

from senda_api import events


def definition(**kw):
    return {"id": "e", "region_id": "XA", "region_name": "Xland", "month": "2010-08", "era": "MODIS",
            "source_url": None, **kw}


@pytest.mark.parametrize(
    "ratio,rank,expected",
    [(2.0, 1, True), (3.5, 3, True), (3.5, 4, False), (1.99, 1, False), (None, 1, False), (5.0, None, False)],
)
def test_found_rule(ratio, rank, expected):
    assert events.is_found(ratio, rank) is expected


def test_compute_fills_fields_from_the_calendar(store, client):
    [e] = events.compute(store, [definition()])
    month = next(m for m in client.post("/api/calendar", json={"area": {"id": "XA"}}).json()["series"]
                 if m["month"] == "2010-08")
    for key in ("count", "median", "ratio", "rank", "of"):
        assert e[key] == month[key]
    assert e["found"] is events.is_found(month["ratio"], month["rank"])
    assert set(e) == {"id", "region_id", "region_name", "month", "era", "count", "median", "ratio", "rank", "of",
                      "found", "source_url"}


def test_unknown_region_names_the_event(store):
    with pytest.raises(ValueError, match="event bad-one"):
        events.compute(store, [definition(id="bad-one", region_id="ZZ")])


def test_events_list_has_the_twelve_events():
    items = events.load_list()
    assert len(items) == 12 and len({e["id"] for e in items}) == 12
    assert [e["month"] for e in items][:2] == ["2003-08", "2006-10"]
    assert all((e["source_url"] is None or e["source_url"].startswith("http")) and e["era"] in ("MODIS", "VIIRS") for e in items)
