
from senda_api import regions


def test_region_search_prefix_first(store):
    res = regions.find(store, "x", 20)
    assert [r["id"] for r in res] == ["XA", "XA-W"]  # name prefix beats a later word prefix
    assert set(res[0]) == {"id", "kind", "country_id", "country_name", "name", "bbox"}
    assert res[1]["country_name"] == "Xland" and res[1]["name"] == "West Xland"


def test_search_exact_and_id(store):
    assert regions.find(store, "west xland", 5)[0]["id"] == "XA-W"
    assert regions.find(store, "xa-w", 5)[0]["id"] == "XA-W"
    assert regions.find(store, "zzz", 5) == []


def test_search_ignores_case_and_diacritics(store):
    assert regions.find(store, "XLÁND", 5)[0]["id"] == "XA"


def test_empty_query_lists_countries_first(store):
    assert [r["id"] for r in regions.find(store, "", 10)] == ["XA", "XA-W"]
    assert len(regions.find(store, "", 1)) == 1
