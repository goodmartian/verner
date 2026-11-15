import pytest
from fakes import ScriptedModel, say
from fastapi.testclient import TestClient
from test_fires import live  # noqa: F401
from test_weather import folder, wx  # noqa: F401

from senda_api.app import create_app
from senda_api.chat import api as chat_api
from senda_api.settings import Settings


def test_big_json_is_gzipped_and_small_is_not(client):
    big = client.get("/api/regions", headers={"Accept-Encoding": "gzip"})
    assert big.headers.get("content-encoding") == "gzip" or len(big.content) < 1024
    assert client.get("/api/regions", headers={"Accept-Encoding": "identity"}).headers.get("content-encoding") is None
    assert client.get("/api/health", headers={"Accept-Encoding": "gzip"}).headers.get("content-encoding") is None


@pytest.mark.parametrize("path", ["/api/regions", "/api/config", "/api/meta", "/api/regions/XA/geometry",
                                  "/api/calendar/provinces?area=XA", "/api/calendar/month?area=XA&month=2024-06"])
def test_every_answer_is_checked_with_the_server_each_time(client, path):
    first = client.get(path)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-cache"  # never `max-age`: a new release shows at once
    again = client.get(path, headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.content == b"" and again.headers["cache-control"] == "no-cache"
    assert client.get(path, headers={"If-None-Match": '"other"'}).status_code == 200


def test_other_answers_are_left_alone(client):
    assert "cache-control" not in client.get("/api/health").headers
    assert client.get("/api/regions/ZZ/geometry").status_code == 404


def test_event_stream_is_not_compressed(database, store):
    chat_api.GATE._active.clear()
    client = TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None),
                                   chat_model=ScriptedModel(say("Fine, and a long enough answer " * 80))))
    res = client.post("/api/chats/new/messages", json={"text": "hi"}, headers={"Accept-Encoding": "gzip"})
    assert res.headers.get("content-encoding") is None
    assert "event: done" in res.text


def test_weather_pictures_are_not_compressed(wx):  # noqa: F811
    res = wx.get("/api/weather/wind-field.png", params={"time": "2026-11-10T06:00:00Z"}, headers={"Accept-Encoding": "gzip"})
    assert res.headers.get("content-encoding") is None


def test_fire_weather_for_a_region_or_some_ids(wx, live):  # noqa: F811
    everything = wx.get("/api/weather/fires").json()["fires"]
    west = wx.get("/api/weather/fires", params={"region": "XA-W"}).json()
    assert west["available"] and 0 < len(west["fires"]) < len(everything)
    one = everything[0]["fire_id"]
    picked = wx.get("/api/weather/fires", params={"ids": f"{one},nope"}).json()
    assert [f["fire_id"] for f in picked["fires"]] == [one] and picked["hours"] == 25
    assert wx.get("/api/weather/fires", params={"region": "ZZ"}).status_code == 404
    assert wx.get("/api/weather/fires", params={"ids": ",".join(["a"] * 201)}).status_code == 422
