from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from shapes import check
from test_fires import live  # noqa: F401
from weather_files import START, write

from senda_api.app import create_app
from senda_api.contracts import FirePlan
from senda_api.settings import Settings


@pytest.fixture
def wx(store, tmp_path):
    """Weather that covers the day of the fires (the passes are on 2026-11-11)."""
    folder = write(tmp_path / "weather" / "current", start=START + timedelta(days=1))
    return TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=folder)))


def west(client):
    fires = client.get("/api/fires", params={"region": "XA"}).json()["fires"]
    return next(f for f in fires if f["nearest_place"]["name"] == "Westville")["id"]


def test_plan_needs_wind_data(client, live):  # noqa: F811
    res = client.post(f"/api/fires/{west(client)}/plan", json={})
    assert res.status_code == 409 and res.json()["error"]["code"] == "plan_unavailable"
    assert "wind" in res.json()["error"]["message"]


def test_card_has_no_front_without_wind(client, live):  # noqa: F811
    spread = client.get(f"/api/fires/{west(client)}").json()["spread"]
    assert spread is None or (spread["wind"] is None and spread["contours"] == [] and spread["length_to_breadth"] is None)


def test_plan_and_card_with_wind(wx, live):  # noqa: F811
    fire = west(wx)
    card = wx.get(f"/api/fires/{fire}").json()
    check("FireDetail", card)
    spread = card["spread"]
    assert spread is not None
    assert spread["wind"]["speed_kmh"] > 0 and [c["hours"] for c in spread["contours"]] == [1, 3, 6]
    res = wx.post(f"/api/fires/{fire}/plan", json={"crews": 2, "hours": 3})
    assert res.status_code == 200, res.text
    body = res.json()
    FirePlan.model_validate(body)
    # the plan's default pass is the last in which the fire was seen: the card at that pass says the same
    same = wx.get(f"/api/fires/{fire}", params={"pass": body["pass_index"]}).json()["spread"]
    assert body["contours"] == same["contours"] and body["wind"]["speed_kmh"] == same["wind"]["speed_kmh"]
    assert body["wind"]["at"] == body["pass_time"] == same["wind"]["at"]  # one moment for the card and the plan
    assert len(body["crews"]) == 2 and body["straight_line_only"] is True


def test_plan_of_unknown_fire_or_pass(wx, live):  # noqa: F811
    assert wx.post("/api/fires/nope/plan", json={}).status_code == 404
    assert wx.post(f"/api/fires/{west(wx)}/plan", json={"pass": 99}).status_code == 422


def test_card_and_plan_use_one_default_pass(wx, live):  # noqa: F811
    card = wx.get(f"/api/fires/{west(wx)}").json()
    plan = wx.post(f"/api/fires/{west(wx)}/plan", json={}).json()
    assert card["pass_index"] == plan["pass_index"]
    assert card["spread"]["wind"]["at"] == plan["wind"]["at"] == plan["pass_time"]
    assert {"access_route", "land_cover"}.isdisjoint(card)
