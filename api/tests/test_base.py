from shapes import check

from senda_api.contracts import Regions

NAMES = {"en", "fr", "es", "ru"}


def test_health_shape(client):
    body = client.get("/api/health").json()
    check("Health", {k: body[k] for k in ("status", "database", "schema_revision", "artifacts")})
    assert body["status"] == "ok" and body["data_version"] == "test-1"


def test_config(client):
    body = client.get("/api/config").json()
    check("Config", body)
    assert body["languages"] == ["en", "fr", "es", "ru"]
    assert body["archive_years"][0] == 2003 and body["archive_years"][-1] == 2026
    assert [c["id"] for c in body["covered_countries"]] == ["XA"]
    assert body["default_area"] in {"AR", "XA"}


def test_regions_search_and_shape(client):
    body = client.get("/api/regions", params={"q": "west"}).json()
    Regions.model_validate(body)
    assert [r["id"] for r in body["regions"]] == ["XA-W"]
    region = body["regions"][0]
    assert set(region["names"]) == NAMES and region["country_id"] == "XA" and region["covered"] is True
    assert isinstance(region["timezone"], str) and region["fires_now"] == 0
    assert region["bbox"] == [20.0, 9.0, 21.25, 10.0] and "type_label" not in region


def test_regions_start_with_the_countries_and_a_country_brings_its_regions(client):
    assert [r["id"] for r in client.get("/api/regions").json()["regions"]] == ["XA"]
    body = client.get("/api/regions", params={"country": "XA"}).json()
    assert [r["id"] for r in body["regions"]] == ["XA", "XA-W"]
    assert set(body["types"]) == {r["type"] for r in body["regions"] if r["type"]}


def test_region_bbox_has_three_decimals_and_types_are_sent_once(client):
    body = client.get("/api/regions", params={"country": "XA"}).json()
    assert all(round(v, 3) == v for r in body["regions"] for v in r["bbox"])
    assert all(set(label) == {"en", "fr", "es", "ru"} for label in body["types"].values())


def test_regions_country_first_and_filters(client):
    ids = [r["id"] for r in client.get("/api/regions", params={"country": "XA"}).json()["regions"]]
    assert ids == ["XA", "XA-W"]
    assert [r["id"] for r in client.get("/api/regions", params={"kind": "region"}).json()["regions"]] == ["XA-W"]
    assert [r["id"] for r in client.get("/api/regions", params={"country": "XA", "limit": 1}).json()["regions"]] == ["XA"]
    assert client.get("/api/regions", params={"q": "xland", "lang": "ru"}).json()["regions"][0]["id"] == "XA"
    res = client.get("/api/regions", params={"lang": "zz"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "validation_error"
    assert client.get("/api/regions", params={"q": "nothing"}).json()["regions"] == []


def test_region_geometry(client):
    body = client.get("/api/regions/XA-W/geometry").json()
    check("RegionGeometry", body)
    assert body["bbox"] == [20.0, 9.0, 21.25, 10.0] and body["covered"] is True
    res = client.get("/api/regions/ZZ/geometry")
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"


def test_world_countries_list(client):
    body = client.get("/api/world/countries").json()
    check("WorldCountries", body)
    assert body["first_year"] == 2003 and body["last_year"] == 2025
    country = body["countries"][0]
    assert country["id"] == "XA" and country["bbox"] is None and country["cells"] is None
    assert len(country["yearly"]) == 23 and len(country["seasonal"]) == 12
    assert abs(sum(y["total"] for y in country["yearly"]) / 23 - country["average_per_year"]) < 1e-6
    assert country["peak_month"] == country["seasonal"].index(max(country["seasonal"])) + 1


def test_world_countries_numbers_match_the_calendar(client):
    cal = client.post("/api/calendar", json={"area": {"id": "XA"}}).json()
    by_year = {y["year"]: y["count"] for y in cal["yearly"]}
    country = client.get("/api/world/countries").json()["countries"][0]
    for y in country["yearly"]:
        assert y["total"] == by_year[y["year"]], y["year"]


def test_world_countries_by_id_and_year(client):
    body = client.get("/api/world/countries", params={"ids": "XA", "years": "2019,1990"}).json()
    check("WorldCountries", body)
    assert body["missing_years"] == [1990] and body["cells_year"] == 2019
    country = body["countries"][0]
    assert country["bbox"] and country["geometry"]["type"] in ("Polygon", "MultiPolygon")
    year = country["years"][0]
    assert year["year"] == 2019 and len(year["monthly"]) == 12 and year["total"] == sum(year["monthly"])
    assert all(c["value"] >= 1 for c in country["cells"])
    values = [c["value"] for c in country["cells"]]
    assert values == sorted(values)
    assert abs(sum(values) - year["total"]) < 0.01 * year["total"] + 1


def test_world_countries_errors(client):
    assert client.get("/api/world/countries", params={"ids": "ZZ"}).status_code == 404
    assert client.get("/api/world/countries", params={"years": "abc"}).status_code == 422


def test_country_names_belong_to_their_own_country():
    from senda_api.regions import country_names

    names = country_names()
    assert [names[k]["en"] for k in ("AU", "FR", "KZ", "BR")] == ["Australia", "France", "Kazakhstan", "Brazil"]


def test_known_seasons_carry_the_names_of_their_region(client):
    examples = client.get("/api/meta").json()["examples"]
    assert examples and all(set(e["names"]) == {"en", "fr", "es", "ru"} and "region_name" not in e for e in examples)
    assert {e["region_id"]: e["names"]["en"] for e in examples}["XA"] == "Xland"
