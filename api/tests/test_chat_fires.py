from datetime import timedelta

import pytest
from fakes import ScriptedModel, call, parse_sse, say
from fastapi.testclient import TestClient
from test_fires import live  # noqa: F401
from weather_files import START, write

from senda_api.app import create_app
from senda_api.chat import api as chat_api
from senda_api.chat.verify import unverified
from senda_api.contracts import ChatDetail, FireDetail, FireList
from senda_api.settings import Settings

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture(autouse=True)
def _free_gate():
    chat_api.GATE._active.clear()


def ask_with(store, tmp_path, *steps, weather=True):
    folder = write(tmp_path / "weather" / "current", start=START + timedelta(days=1)) if weather else tmp_path / "none"
    model = ScriptedModel(*steps)
    client = TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=folder),
                                   chat_model=model))
    got = parse_sse(client.post("/api/chats/new/messages", json={"text": "Which fire grows fastest?"}).text)
    return model, got


def result(model, index=1):
    import json
    return json.loads(model.tool_results(index)[0]["content"])


@pytest.mark.parametrize("sort_by", ["growth", "front_speed", "wind", "place", "area_ha"])
def test_the_list_of_fires_answers_the_questions_of_the_fires_tab(store, tmp_path, live, sort_by):  # noqa: F811
    model, got = ask_with(store, tmp_path, call("list_fires", {"region": "XA", "sort_by": sort_by, "limit": 5}),
                          say("Done."))
    assert [n for n, _ in got][-1] == "done"
    out = result(model)
    assert out["sorted_by"] == sort_by and out["total"] == 2 and out["window_days"] == 3
    row = out["fires"][0]
    assert {"id", "area_ha", "detection_count", "nearest_place", "area_change_last_pass_ha", "front_speed_m_per_h",
            "wind", "growth"} <= set(row)
    assert row["nearest_place"]["name"] in {"Westville", "Eastford"} and isinstance(row["nearest_place"]["direction"], str)
    assert row["wind"]["speed_kmh"] > 0 and row["wind"]["at"].endswith("Z") and 1 <= len(row["growth"]) <= 4
    if sort_by == "place":
        distances = [f["nearest_place"]["distance_km"] for f in out["fires"]]
        assert distances == sorted(distances)
    if sort_by == "growth":
        changes = [f["area_change_last_pass_ha"] or 0 for f in out["fires"]]
        assert changes == sorted(changes, reverse=True)


def test_the_numbers_of_the_fire_tools_pass_the_number_check(store, tmp_path, live):  # noqa: F811
    model, _ = ask_with(store, tmp_path, call("list_fires", {"region": "XA"}), say("Done."))
    out = result(model)
    top = out["fires"][0]
    text = f"The biggest is {top['area_ha']} ha with {top['detection_count']} detections."
    assert unverified(text, [out], []) == []
    assert unverified("The biggest is 999999 ha.", [out], []) != []


def test_one_fire_and_the_errors(store, tmp_path, live):  # noqa: F811
    fire = live.fires[0]
    model, _ = ask_with(store, tmp_path, call("get_fire", {"fire_id": fire.id}), say("Done."))
    one = result(model)
    assert one["id"] == fire.id and one["wind"] is not None and len(one["growth"]) >= 2
    # the forecast at the fire for the hours after the last pass, as far as the weather grid goes
    ahead = one["weather_ahead"]
    assert 1 <= ahead["hours_covered"] <= 24 and ahead["from"] == one["wind"]["at"]
    assert ahead["rain_mm_total"] >= 0 and ahead["max_gust_kmh"] > 0 and 0 <= ahead["min_humidity_pct"] <= 100
    assert [p["in_hours"] for p in ahead["points"]] == [h for h in (3, 6, 12, 24) if h <= ahead["hours_covered"]]
    assert all({"at", "wind_kmh", "wind_from", "gust_kmh", "rain_mm_per_h", "humidity_pct", "temperature_c"} <= set(p)
               for p in ahead["points"])
    # without a weather grid there is no forecast, and the card still comes
    model, _ = ask_with(store, tmp_path, call("get_fire", {"fire_id": fire.id}), say("Done."), weather=False)
    assert result(model)["weather_ahead"] is None
    model, _ = ask_with(store, tmp_path, call("get_fire", {"fire_id": "nope"}), say("Not found."))
    assert "not_found" in model.tool_results(1)[0]["content"]
    model, _ = ask_with(store, tmp_path, call("list_fires", {"region": "ZZ"}), say("No such region."))
    assert "not_found" in model.tool_results(1)[0]["content"]


def test_without_weather_the_fires_have_no_wind_but_the_rest(store, tmp_path, live):  # noqa: F811
    model, _ = ask_with(store, tmp_path, call("list_fires", {"region": "XA"}), say("Done."), weather=False)
    assert all(f["wind"] is None and f["area_ha"] > 0 for f in result(model)["fires"])


def test_clock_times_are_not_data_numbers(store, tmp_path, live):  # noqa: F811
    model, _ = ask_with(store, tmp_path, call("list_fires", {"region": "XA"}), say("Done."))
    out = result(model)
    fire = out["fires"][0]
    text = (f"Площадь {fire['area_ha']} га, ветер на 14:47 и в 03:08, ближайший пункт {fire['nearest_place']['name']} "
            f"в {fire['nearest_place']['distance_km']} км.")
    assert unverified(text, [out], []) == []


@pytest.mark.parametrize("tool,step", [("list_fires", "live_fires"), ("get_fire", "fire_detail")])
def test_the_step_names_the_fire_tool(store, tmp_path, live, tool, step):  # noqa: F811
    args = {"region": "XA"} if tool == "list_fires" else {"fire_id": live.fires[0].id}
    _, got = ask_with(store, tmp_path, call(tool, args), say("Done."))
    assert ("step", {"tool": step}) in got


@pytest.mark.parametrize("text,header,word", [("Какой пожар растёт?", "en", "проверить"), ("Which?", "es-ES,es;q=0.9", "comprobar"),
                                              ("Which?", "fr", "vérifier"), ("Which?", "", "check")])
def test_the_refusal_speaks_the_language_of_the_question(store, tmp_path, live, text, header, word):  # noqa: F811
    folder = tmp_path / "none"
    model = ScriptedModel(call("list_fires", {"region": "XA"}), say("The biggest is 999999 ha."),
                          say("The biggest is 999999 ha."))
    client = TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=folder), chat_model=model))
    got = parse_sse(client.post("/api/chats/new/messages", json={"text": text},
                                headers={"Accept-Language": header} if header else {}).text)
    assert word in next(d["text"] for n, d in got if n == "text")


def test_an_answer_in_the_style_of_the_model_passes_and_a_made_up_number_does_not(store, tmp_path, live):  # noqa: F811
    model, _ = ask_with(store, tmp_path, call("list_fires", {"region": "XA", "sort_by": "growth"}), say("Done."))
    out = result(model)
    fire = out["fires"][0]
    place = fire["nearest_place"]
    good = (f"Пожар {fire['id']} в {place['distance_km']} км от {place['name']}: площадь {fire['area_ha']} га, "
            f"влажность {fire['wind']['humidity_pct']} %, ветер {fire['wind']['speed_kmh']} км/ч.".replace(".", ","))
    assert unverified(good, [out], []) == []
    bad = good.replace(str(place["name"]), "X") + " Прирост 77,7 %."
    assert unverified(bad, [out], []) == ["77,7 %"]


def widgets(got):
    return [d for n, d in got if n == "widget"]


@pytest.mark.parametrize("sort_by,limit", [("growth", 1), ("place", 5), ("area_ha", 2)])
def test_the_list_of_fires_comes_with_its_card_of_the_same_fires_in_the_same_order(store, tmp_path, live, sort_by, limit):  # noqa: F811
    model, got = ask_with(store, tmp_path, call("list_fires", {"region": "XA", "sort_by": sort_by, "limit": limit}),
                          say("Done."))
    out = result(model)
    [card] = widgets(got)
    assert card["type"] == "fire_list"
    data = FireList.model_validate(card["data"]).model_dump(mode="json")
    assert [f["id"] for f in data["fires"]] == [f["id"] for f in out["fires"]]
    for shown, said in zip(data["fires"], out["fires"], strict=True):
        assert shown["area_ha"] == said["area_ha"] and shown["nearest_place"]["name"] == said["nearest_place"]["name"]
        assert shown["detection_count"] == said["detection_count"]


@pytest.mark.parametrize("first", ["list_fires", "get_fire"])
def test_one_fire_comes_with_its_card_and_the_list_that_found_it_is_not_shown(store, tmp_path, live, first):  # noqa: F811
    fire = live.fires[0]
    folder = write(tmp_path / "weather" / "current", start=START + timedelta(days=1))
    steps = [call("list_fires", {"region": "XA"}), call("get_fire", {"fire_id": fire.id}, call_id="t2")]
    model = ScriptedModel(*(steps if first == "list_fires" else steps[::-1]), say("Done."))
    client = TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=folder),
                                   chat_model=model))
    got = parse_sse(client.post("/api/chats/new/messages", json={"text": "Which fire grows fastest?"}).text)
    one = result(model, 2 if first == "list_fires" else 1)
    [card] = widgets(got)
    assert card["type"] == "fire_detail"
    detail = FireDetail.model_validate(card["data"])
    assert detail.summary.id == fire.id and detail.summary.area_ha == one["area_ha"]
    assert detail.summary.detection_count == one["detection_count"]
    # the points, the scar and the outline stay with the Fires screen
    assert detail.detections == [] and detail.outline is None and detail.scar is None and detail.core is None
    chat = next(d for n, d in got if n == "done")["chat_id"]
    kept = ChatDetail.model_validate(client.get(f"/api/chats/{chat}").json())
    assert [w.type for w in kept.messages[1].widgets] == ["fire_detail"]  # the chat keeps what was sent


def test_a_list_of_fires_alone_comes_after_the_text_and_is_kept(store, tmp_path, live):  # noqa: F811
    _, got = ask_with(store, tmp_path, call("list_fires", {"region": "XA"}), say("Two fires."))
    names = [n for n, _ in got]
    assert names.index("text") < names.index("widget") < names.index("done")
    assert [w["type"] for w in widgets(got)] == ["fire_list"]


def test_growth_comes_ready_in_hectares_and_percent(store, tmp_path, live):  # noqa: F811
    model, _ = ask_with(store, tmp_path, call("list_fires", {"region": "XA", "sort_by": "growth"}), say("Done."))
    for f in result(model)["fires"]:
        if f["area_change_last_pass_ha"] and f["growth"][-2]["area_ha"]:
            assert f["area_change_last_pass_pct"] == round(100 * f["area_change_last_pass_ha"] / f["growth"][-2]["area_ha"], 1)
