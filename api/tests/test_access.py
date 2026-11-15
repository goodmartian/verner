import json
import logging
from datetime import timedelta
from pathlib import Path

import pytest
from fakes import ScriptedModel, call, parse_sse, say
from fastapi.testclient import TestClient
from test_fire_plan import west
from test_fires import live  # noqa: F401
from weather_files import START, write

from senda_api import access, contracts
from senda_api.access import Access, AccessError, Clock, osrm_route, overpass_stations
from senda_api.app import create_app
from senda_api.chat.verify import unverified
from senda_api.settings import Settings

DATA = Path(__file__).parent / "data"
OUTLINE = [[20.44, 9.50], [20.46, 9.50], [20.46, 9.54], [20.44, 9.54], [20.44, 9.50]]
PLACE = {"name": "Westville", "distance_km": 5.0, "location": [20.45, 9.52], "direction": 0}
KEY = "test-key-123"


def osm(name, lon, lat):
    return {"type": "node", "lon": lon, "lat": lat, "tags": {"amenity": "fire_station", "name": name}}


def gplace(name, lon, lat):
    return {"displayName": {"text": name}, "location": {"longitude": lon, "latitude": lat}}


class FakeHttp:
    """Overpass, OSRM, Google Places and Google Routes made up for the places of the test. A service set to None is down.
    Every request is written down as (service, timeout); the key is only ever seen in headers."""

    def __init__(self, overpass=(), places=(), osrm=True, routes=True, spend=0.0, clock=None):
        self.overpass, self.places, self.osrm, self.routes = overpass, places, osrm, routes
        self.requests: list[tuple[str, float]] = []
        self.urls: list[str] = []
        self.spend, self.clock = spend, clock

    def _use(self, service, url, timeout, up):
        self.requests.append((service, timeout))
        self.urls.append(url)
        if self.clock is not None:
            self.clock[0] += self.spend if not up else 0.1
        if not up:
            raise AccessError(f"{service} down")

    def services(self):
        return [s for s, _ in self.requests]

    def post_form(self, url, form, timeout):
        self._use("overpass", url, timeout, self.overpass is not None)
        assert "fire_station" in form["data"]
        return {"elements": list(self.overpass)}

    def get_json(self, url, timeout):
        self._use("osrm", url, timeout, self.osrm)
        start, end = (tuple(float(v) for v in part.split(",")) for part in url.split("/driving/")[1].split("?")[0].split(";"))
        stop = [end[0] - 0.01, end[1]]
        return {"code": "Ok", "routes": [{"duration": 1800, "distance": 32100.0,
                                          "geometry": {"coordinates": [list(start), stop]}}],
                "waypoints": [{"location": list(start)}, {"location": stop}]}

    def post_json(self, url, body, headers, timeout):
        assert headers["X-Goog-Api-Key"] == KEY and KEY not in url
        if url == access.PLACES_URL:
            assert body["includedTypes"] == ["fire_station"] and body["maxResultCount"] == 3
            assert body["locationRestriction"]["circle"]["radius"] == 50000
            self._use("places", url, timeout, self.places is not None)
            return {"places": list(self.places)}
        assert url == access.ROUTES_URL and body["travelMode"] == "DRIVE"
        self._use("routes", url, timeout, self.routes)
        end = body["destination"]["location"]["latLng"]
        return {"routes": [{"distanceMeters": 24800, "duration": "1952s",
                            "legs": [{"endLocation": {"latLng": {"latitude": end["latitude"], "longitude": end["longitude"] - 0.01}}}]}]}


def reader(tmp_path=None, key=KEY, **kwargs):
    return Access(None if tmp_path is None else tmp_path / "access", FakeHttp(**kwargs), key)


# the parts, on recorded answers

def test_stations_are_read_from_a_recorded_overpass_answer():
    class Recorded(FakeHttp):
        def post_form(self, url, form, timeout):
            return json.loads((DATA / "overpass_places.json").read_text())

    found = overpass_stations(Recorded(), (-56.95, -29.35, -55.45, -27.85), Clock())
    assert len(found) == 9 and all(s[0] for s in found) and any("Bomberos" in s[0] for s in found)


def test_a_recorded_osrm_answer_is_read():
    recorded = json.loads((DATA / "osrm_route.json").read_text())

    class Osrm(FakeHttp):
        def get_json(self, url, timeout):
            return recorded

    out = osrm_route(Osrm(), (-56.0495, -28.5508), (-56.1, -28.55), Clock())
    assert out["drive_s"] == recorded["routes"][0]["duration"] and out["drive_m"] == recorded["routes"][0]["distance"]
    assert out["path"][0] == pytest.approx(recorded["routes"][0]["geometry"]["coordinates"][0], abs=1e-5)


def test_no_route_when_the_router_says_no():
    class No(FakeHttp):
        def get_json(self, url, timeout):
            return {"code": "NoRoute"}

    with pytest.raises(AccessError):
        osrm_route(No(), (0, 0), (1, 1), Clock())


# Overpass: mirrors, time, memory of a failure

def test_mirrors_are_tried_in_turn_and_the_third_waits_when_two_are_silent():
    now = [0.0]
    http = FakeHttp(overpass=None, spend=4.0, clock=now)
    with pytest.raises(AccessError):
        overpass_stations(http, (0, 0, 1, 1), Clock(now=lambda: now[0]))
    assert [t for _, t in http.requests] == [4.0, 2.0]  # 4 s, then the 2 s left of 6; the third mirror is not touched
    assert now[0] == 8.0


def test_a_quick_failure_goes_on_to_the_next_mirror():
    class FirstDown(FakeHttp):
        def post_form(self, url, form, timeout):
            if url == access.OVERPASS_URLS[0]:
                self.urls.append(url)
                raise AccessError("502")
            return super().post_form(url, form, timeout)

    http = FirstDown(overpass=[osm("A", 20.5, 9.5)])
    assert overpass_stations(http, (0, 0, 1, 1), Clock())[0][0] == "A"
    assert http.urls[:2] == list(access.OVERPASS_URLS[:2])


def test_a_failed_overpass_is_not_asked_again_for_ten_minutes():
    now = [1000.0]
    way = Access(None, FakeHttp(overpass=None), None, now=lambda: now[0])
    way.of_outline(OUTLINE, PLACE)
    asked = way.http.services().count("overpass")
    assert asked >= 1
    other = [[x + 1.0, y] for x, y in OUTLINE]  # another fire, another cache key
    way.of_outline(other, {**PLACE, "location": [21.45, 9.52]})
    assert way.http.services().count("overpass") == asked
    now[0] += access.OVERPASS_PAUSE_S + 1
    way.of_outline([[x + 2.0, y] for x, y in OUTLINE], PLACE)
    assert way.http.services().count("overpass") > asked


# the order of the sources

def test_overpass_first_and_google_never_touched_when_it_answers():
    way = reader(overpass=[osm("Far", 20.9, 9.9), osm("Near", 20.55, 9.52)])
    out = way.of_outline(OUTLINE, PLACE)
    contracts.AccessRoute.model_validate(out)
    assert out["origin_source"] == "osm" and out["route_source"] == "osrm" and out["origin_kind"] == "station"
    assert out["station_name"] == "Near" and out["station_location"] == [20.55, 9.52]
    assert out["road_path"][0] == [20.55, 9.52] and out["road_end_point"] and out["attribution"] == access.OSM_ATTRIBUTION
    assert way.http.services() == ["overpass", "osrm"]


@pytest.mark.parametrize("overpass", [None, []])
def test_google_places_when_overpass_is_silent_or_empty(overpass):
    way = reader(overpass=overpass, places=[gplace("Bomberos Voluntarios", 20.5, 9.52)])
    out = way.of_outline(OUTLINE, PLACE)
    contracts.AccessRoute.model_validate(out)
    assert out["origin_source"] == "google" and out["origin_kind"] == "station" and out["station_name"] == "Bomberos Voluntarios"
    assert out["station_location"] is None  # Google's point is not put on our map
    assert out["route_source"] == "osrm" and out["road_path"]  # the line is OSRM's: ours to draw
    assert "Google Maps" in out["attribution"] and "OpenStreetMap" in out["attribution"]
    assert way.http.services().count("places") == 1


def test_no_station_anywhere_starts_at_the_nearest_place():
    out = reader(overpass=None, places=[]).of_outline(OUTLINE, PLACE)
    assert out["origin_kind"] == "place" and out["origin_source"] == "place" and out["station_name"] == "Westville"
    assert out["station_location"] == [20.45, 9.52] and "GeoNames" in out["attribution"] and "Google" not in out["attribution"]
    out = reader(overpass=None, key=None).of_outline(OUTLINE, PLACE)  # no key: Google is skipped
    assert out["origin_source"] == "place"


def test_no_station_and_no_place_is_an_error():
    with pytest.raises(AccessError):
        reader(overpass=[], places=[]).of_outline(OUTLINE, None)


def test_osrm_down_google_routes_gives_numbers_without_a_line():
    way = reader(overpass=[osm("Near", 20.55, 9.52)], osrm=False)
    out = way.of_outline(OUTLINE, PLACE)
    contracts.AccessRoute.model_validate(out)
    assert out["route_source"] == "google" and out["drive_km"] == 24.8 and out["drive_min"] == 33
    assert out["road_path"] is None and out["road_end_point"] is None and out["walk_km"] > 0
    assert out["origin_source"] == "osm" and "Google Maps" in out["attribution"]
    assert way.http.services().count("routes") == 1


@pytest.mark.parametrize("key,routes", [(None, True), (KEY, False)])
def test_without_osrm_and_google_the_way_is_an_error(key, routes):
    with pytest.raises(AccessError):
        reader(key=key, overpass=[osm("Near", 20.55, 9.52)], osrm=False, routes=routes).of_outline(OUTLINE, PLACE)


def test_google_has_a_ceiling_a_day_and_none_without_a_key(monkeypatch):
    monkeypatch.setattr(access, "GOOGLE_PER_DAY", 2)
    day = ["2026-11-14"]
    way = Access(None, FakeHttp(overpass=None, places=[gplace("B", 20.5, 9.5)], osrm=False), KEY, today=lambda: day[0])
    way.of_outline(OUTLINE, PLACE)  # Places and Routes: 2 calls
    assert way.http.services().count("places") == 1 and way.http.services().count("routes") == 1
    far = [[x + 5.0, y] for x, y in OUTLINE]
    with pytest.raises(AccessError):  # above the ceiling Google is not there; OSRM is down too
        way.of_outline(far, {**PLACE, "location": [25.45, 9.52]})
    assert way.http.services().count("places") == 1 and way.http.services().count("routes") == 1
    day[0] = "2026-11-15"  # a new day, a new count
    way.of_outline(far, {**PLACE, "location": [25.45, 9.52]})
    assert way.http.services().count("places") == 2


def test_every_answer_is_cached_google_ones_too_and_a_growing_fire_hits_them(tmp_path):
    way = reader(tmp_path, overpass=[], places=[gplace("B", 20.5, 9.52)], osrm=False)
    way.of_outline(OUTLINE, PLACE)
    asked = len(way.http.requests)
    way.of_outline([[x + 0.0003, y] for x, y in OUTLINE], PLACE)
    assert len(way.http.requests) == asked
    again = Access(tmp_path / "access", FakeHttp(overpass=None, places=None, osrm=False, routes=False), KEY)
    out = again.of_outline(OUTLINE, PLACE)
    assert out["origin_source"] == "google" and out["route_source"] == "google" and again.http.requests == []
    assert list((tmp_path / "access").glob("*.json"))


def test_the_log_names_the_source_and_never_the_key(caplog):
    with caplog.at_level(logging.INFO):
        reader(overpass=None, places=[gplace("B", 20.5, 9.52)]).of_outline(OUTLINE, PLACE)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "start from google, route from osrm" in text and KEY not in text


def test_the_whole_way_keeps_to_twelve_seconds():
    now = [0.0]
    way = Access(None, FakeHttp(overpass=None, places=None, osrm=False, routes=False, spend=5.0, clock=now), KEY,
                 now=lambda: now[0])
    with pytest.raises(AccessError):
        way.of_outline(OUTLINE, None)
    assert now[0] <= access.TOTAL_S + 5.0  # the last request may start at 12 s less 0.5 at the latest
    assert all(t <= 5.0 for _, t in way.http.requests)


# the route, the card and the chat

def app_with(store, tmp_path, http, *steps, key=KEY, **settings):
    folder = write(tmp_path / "weather" / "current", start=START + timedelta(days=1))
    app = create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=folder, **settings),
                     chat_model=ScriptedModel(*steps) if steps else None)
    app.state.access = Access(tmp_path / "access", http, key)
    return app


def test_the_route_answers_the_form_and_still_answers_when_overpass_is_down(store, tmp_path, live):  # noqa: F811
    client = TestClient(app_with(store, tmp_path, FakeHttp(overpass=None, places=[]), database_url=None))
    res = client.get(f"/api/fires/{west(client)}/access-route")
    assert res.status_code == 200, res.text
    contracts.AccessRoute.model_validate(res.json())
    assert res.json()["origin_kind"] == "place" and res.json()["station_name"] in {"Westville", "Eastford"}


def test_the_route_is_404_when_the_router_does_not_answer(store, tmp_path, live):  # noqa: F811
    down = TestClient(app_with(store, tmp_path, FakeHttp(osrm=False, routes=False), database_url=None))
    res = down.get(f"/api/fires/{west(down)}/access-route")
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found" and res.json()["error"]["message"]
    assert down.get("/api/fires/nope/access-route").status_code == 404


def test_the_card_does_not_wait_for_the_network(store, tmp_path, live):  # noqa: F811
    http = FakeHttp([osm("Bomberos", 20.6, 9.5)])
    client = TestClient(app_with(store, tmp_path, http, database_url=None))
    assert client.get(f"/api/fires/{west(client)}").status_code == 200 and http.requests == []


def test_the_chat_card_says_where_a_crew_would_start(store, tmp_path, live, database):  # noqa: F811
    fire = live.fires[0]
    app = app_with(store, tmp_path, FakeHttp([osm("Bomberos", fire.lon + 0.1, fire.lat)]),
                   call("get_fire", {"fire_id": fire.id}), say("Done."))
    model = app.state.chat_model
    parse_sse(TestClient(app).post("/api/chats/new/messages", json={"text": "How do we get there?"}).text)
    out = json.loads(model.tool_results(1)[0]["content"])
    way = out["access"]
    assert way["from"] == "Bomberos" and way["from_kind"] == "station" and way["drive_min"] == 30
    text = f"From Bomberos: {way['drive_km']} km, {way['drive_min']} min by road, then {way['walk_km']} km on foot."
    assert unverified(text, [out], []) == []
    assert unverified("It takes 777 min.", [out], []) != []
    app.state.access = Access(None, FakeHttp(osrm=False, routes=False), None)
    app.state.chat_model = model = ScriptedModel(call("get_fire", {"fire_id": fire.id}), say("Done."))
    TestClient(app).post("/api/chats/new/messages", json={"text": "Again"})
    assert json.loads(model.tool_results(1)[0]["content"])["access"] is None
