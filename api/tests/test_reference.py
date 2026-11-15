"""The reference files shipped in the package: a missing or emptied file must fail here, not in the names of regions."""

from senda_api import regions as names


def label(region_id):
    return names.type_labels()[0][names.type_of(region_id)]


def test_reference_files_are_in_the_package_and_full():
    assert len(names.country_names()) >= 240
    assert len(names.region_names()) >= 4000
    labels, by_region = names.type_labels()
    assert len(by_region) >= 4000 and "Province" in labels and "State" in labels


def test_buenos_aires_province_and_city_are_told_apart():
    assert label("AR-B")["en"]["one"] == "Province"
    assert label("AR-C")["en"]["one"] == "Federal district"
    assert names.region_names()["AR-C"]["en"] == "Ciudad de Buenos Aires"
    assert "en" not in names.region_names()["AR-B"]  # the province keeps its English name from the region table


def test_territories_do_not_take_the_name_of_their_country():
    found = {k: names.country_names()[k]["en"] for k in ("AU", "FR", "KZ", "BR")}
    assert found == {"AU": "Australia", "FR": "France", "KZ": "Kazakhstan", "BR": "Brazil"}
    assert names.country_names()["BR"]["ru"] == "Бразилия"


def test_moscow_and_altai_follow_their_polygons():
    found = names.region_names()
    assert (found["RU-MOW"]["en"], found["RU-MOS"]["en"]) == ("Moscow Oblast", "Moscow")
    assert (found["RU-ALT"]["en"], found["RU-AL"]["en"]) == ("Altai Krai", "Altai Republic")
    assert found["RU-ALT"]["ru"] == "Алтайский край" and found["GB-WRL"]["en"] == "Wirral"
    assert [label(k)["en"]["one"] for k in ("RU-MOW", "RU-MOS", "RU-ALT", "RU-AL")] == [
        "Oblast", "Federal city", "Krai", "Republic"]
    assert label("RU-MOW")["ru"]["one"] == "Область"
    assert label("RU-ALT")["ru"]["one"] == "Край"


def test_every_type_has_labels_in_four_languages():
    labels, by_region = names.type_labels()
    assert {v for v in by_region.values() if v not in labels} == set()
    assert all(set(v) == {"en", "fr", "es", "ru"} and all(x["one"] and x["other"] for x in v.values())
               for v in labels.values())
