import itertools
import json
from datetime import timedelta

import pytest
from fakes import ScriptedModel, call, parse_sse, say
from fastapi.testclient import TestClient
from test_fire_plan import west
from test_fires import live  # noqa: F401
from weather_files import START, write

from senda_api.app import create_app
from senda_api.chat import api as chat_api
from senda_api.chat.verify import unverified
from senda_api.contracts import ChatDetail, FirePlan
from senda_api.settings import Settings

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture(autouse=True)
def _free_gate():
    chat_api.GATE._active.clear()


def chat(store, tmp_path, *steps, weather=True):
    folder = write(tmp_path / "weather" / "current", start=START + timedelta(days=1)) if weather else tmp_path / "none"
    model = ScriptedModel(*steps)
    app = create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=folder), chat_model=model)
    return TestClient(app), model


def ask(client, text="Make a plan.", chat_id="new"):
    return parse_sse(client.post(f"/api/chats/{chat_id}/messages", json={"text": text}).text)


def result(model, index=1):
    return json.loads(model.tool_results(index)[0]["content"])


def fire_of(store, tmp_path, live):  # noqa: F811
    client, _ = chat(store, tmp_path)
    return west(client)


def test_make_plan_gives_the_model_a_summary_and_the_screen_the_plan(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    client, model = chat(store, tmp_path, call("make_plan", {"fire_id": fire, "crews": 2, "hours": 3}), say("Done."))
    got = ask(client)
    out = result(model)
    assert out["window_hours"] == 3 and out["wind"]["speed_kmh"] > 0 and out["wind"]["from"]
    # the forecast for the hours of the work: no further than the window
    window = out["weather_in_window"]
    assert 1 <= window["hours_covered"] <= 3 and window["rain_mm_total"] >= 0 and window["max_gust_kmh"] > 0
    assert [p["in_hours"] for p in window["points"]] == [h for h in (3,) if h <= window["hours_covered"]]
    assert out["front"]["spread_km_per_h"] > 0 and len(out["crews"]) == 2
    crew = out["crews"][0]
    assert {"trail_km", "trail_min", "path_kind", "land", "front_reaches_work_in_h", "way_out_km", "status"} <= set(crew)
    assert crew["path_kind"] == "straight line" and out["straight_line_only"] is True
    assert "on_trail" not in crew and "expected_growth_ha_in_window" in out["front"] and "area_ha_at_pass" in out["front"]
    assert "noland" in {i["kind"] for i in out["issues"]}
    assert "coordinates" not in json.dumps(out) and "route" not in crew
    assert ("step", {"tool": "build_plan"}) in got
    widget = next(d for n, d in got if n == "widget")
    assert widget["type"] == "work_plan"
    FirePlan.model_validate(widget["data"])  # the same plan the screen draws


def test_make_plan_follows_the_arguments(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    client, model = chat(store, tmp_path, call("make_plan", {"fire_id": fire, "crews": 3, "hours": 6}), say("Done."))
    ask(client)
    out = result(model)
    assert out["window_hours"] == 6 and len(out["crews"]) == 3


def test_make_plan_errors_go_back_to_the_model(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    for args, code, weather in [({"fire_id": "nope"}, "not_found", True), ({"fire_id": fire}, "plan_unavailable", False),
                                ({"fire_id": fire, "crews": 0}, "invalid_input", True),
                                ({"fire_id": fire, "hours": 2}, "invalid_input", True),
                                ({"fire_id": fire, "colour": 1}, "invalid_input", True)]:
        client, model = chat(store, tmp_path, call("make_plan", args), say("No plan."), weather=weather)
        got = ask(client)
        assert code in model.tool_results(1)[0]["content"], args
        assert got[-1][0] == "done"


def test_the_text_of_a_plan_answer_passes_the_number_check(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    client, model = chat(store, tmp_path, call("make_plan", {"fire_id": fire}), say("Done."))
    ask(client)
    out = result(model)
    crew = out["crews"][0]
    text = (f"Ветер {out['wind']['speed_kmh']} км/ч, фронт идёт {out['front']['spread_km_per_h']} км/ч. "
            f"Бригада {crew['number']}: тропа {crew['trail_km']} км, {crew['trail_min']} минут; "
            f"до выжженной земли {crew['way_out_km']} км. Окно {out['window_hours']} ч.").replace(".", ",")
    assert unverified(text, [out], []) == []
    assert unverified(text + " Тропа 9 876 км.", [out], []) == ["9 876"]


def draw(shapes, replace=False):
    return call("draw_on_map", {"shapes": shapes, "replace": replace})


def drawn(got):
    return [a for n, a in got if n == "action" and a["type"] == "draw"]


def test_plain_shapes_are_named_by_the_server_and_run_through_the_chat(store, tmp_path, live):  # noqa: F811
    shapes = [{"kind": "polygon", "label": "Zone", "rings": [[[10, 10], [11, 10], [11, 11]]]},
              {"kind": "line", "points": [[10, 10], [11, 11]], "role": "path"},
              {"kind": "point", "position": [10.5, 10.5], "label": "P"},
              {"kind": "circle", "center": [10, 10], "radius_km": 5, "label": "Ring"}]
    client, model = chat(store, tmp_path, draw(shapes), say("Drawn [Zone](shape:A1)."), draw(shapes[2:3]), say("Drawn."))
    got = ask(client)
    action = drawn(got)[0]
    assert [s["id"] for s in action["shapes"]] == ["A1", "A2", "A3", "A4"] and action["replace"] is False
    assert [s["kind"] for s in action["shapes"]] == ["polygon", "line", "point", "circle"]
    assert action["shapes"][0]["rings"][0][0] == action["shapes"][0]["rings"][0][-1]  # the ring is closed
    assert all(s["label_at"] for s in action["shapes"])
    assert [d["id"] for d in result(model)["drew"]] == ["A1", "A2", "A3", "A4"]
    chat_id = next(d["chat_id"] for n, d in got if n == "start")
    second = ask(client, "More.", chat_id)
    assert [s["id"] for s in drawn(second)[0]["shapes"]] == ["A5"]  # the numbers go on
    saved = client.get(f"/api/chats/{chat_id}").json()["messages"]
    assert [a["type"] for m in saved for a in m["actions"]] == ["draw", "draw"]


def test_bad_shapes_are_refused_with_what_to_change(store, tmp_path, live):  # noqa: F811
    for item, word in [({"kind": "polygon"}, "needs `rings`"), ({"kind": "circle", "center": [0, 0], "radius_km": 999}, "radius_km"),
                       ({"kind": "point", "position": [500, 0]}, "longitude"), ({"kind": "blob"}, "kind is"),
                       ({"kind": "reference", "from": "nothing"}, "`from` is"),
                       ({"kind": "reference", "from": "area:ZZZ"}, "no area"),
                       ({"kind": "reference", "from": "area:XA", "buffer_km": 1}, "go with `fire:` only"),
                       ({"kind": "line", "points": [[0, 0]]}, "2 to"), ({"kind": "point", "position": [0, 0], "colour": 1}, "colour")]:
        client, model = chat(store, tmp_path, draw([item]), say("Sorry."))
        ask(client)
        assert word in model.tool_results(1)[0]["content"], item


def test_a_call_draws_at_most_twenty_shapes_in_an_answer(store, tmp_path, live):  # noqa: F811
    point = {"kind": "point", "position": [1, 1]}
    client, model = chat(store, tmp_path, draw([point] * 20), draw([point]), say("Done."))
    ask(client)
    assert "at most 20" in model.tool_results(2)[0]["content"]


def test_references_to_a_fire(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    ref = f"fire:{fire}"
    items = [{"kind": "reference", "from": ref, "label": "Fire"},
             {"kind": "reference", "from": ref, "buffer_km": 2, "label": "Buffer"},
             {"kind": "reference", "from": ref, "forecast_hours": 3, "label": "In 3 h"},
             {"kind": "reference", "from": ref, "approach_from": [0.0, 0.0], "label": "Arrow"}]
    client, model = chat(store, tmp_path, draw(items), say("Done."))
    got = ask(client)
    assert drawn(got), model.tool_results(1)[0]["content"]
    shapes = drawn(got)[0]["shapes"]
    by_label = {s["label"]: s for s in shapes}
    assert by_label["Fire"]["kind"] == "polygon" and by_label["Arrow"]["role"] == "approach"
    assert by_label["Arrow"]["kind"] == "line" and len(by_label["Arrow"]["points"]) == 2
    def area(ring):
        return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in itertools.pairwise(ring))) / 2

    assert area(by_label["Buffer"]["rings"][0]) > area(by_label["Fire"]["rings"][0])
    # the forecast is the planner's own front, the one the fire card draws: no second calculation
    card = client.get(f"/api/fires/{fire}").json()["spread"]["contours"]
    front = next(c for c in card if c["hours"] == 3)["polygons"][0][0]
    assert area(by_label["In 3 h"]["rings"][0]) == pytest.approx(area(front), rel=1e-6)
    assert all(s["id"].startswith("A") for s in shapes) and result(model)["warnings"] == []


def test_a_forecast_needs_wind_and_whole_hours(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    item = {"kind": "reference", "from": f"fire:{fire}", "forecast_hours": 3}
    client, model = chat(store, tmp_path, draw([item]), say("No."), weather=False)
    ask(client)
    assert "no forecast" in model.tool_results(1)[0]["content"]
    client, model = chat(store, tmp_path, draw([{**item, "forecast_hours": 2}]), say("No."))
    ask(client)
    assert "forecast_hours is 1, 3 or 6" in model.tool_results(1)[0]["content"]
    client, model = chat(store, tmp_path, draw([{**item, "buffer_km": 1}]), say("No."))
    ask(client)
    assert "not both" in model.tool_results(1)[0]["content"]


def test_an_area_reference_draws_its_border(store, tmp_path, live):  # noqa: F811
    code = next(c for c in store.regions.by_id if c != "WORLD" and c != "XA")
    client, _ = chat(store, tmp_path, draw([{"kind": "reference", "from": f"area:{code}", "label": "Border"}]), say("Done."))
    shapes = drawn(ask(client))[0]["shapes"]
    assert shapes and all(s["kind"] == "polygon" and s["label"] == "Border" for s in shapes)


def test_the_plan_is_drawn_from_the_plan_the_planner_made(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    items = [{"kind": "reference", "from": f"route:{fire}", "label": "In"},
             {"kind": "reference", "from": f"escape:{fire}", "label": "Out"}]
    client, model = chat(store, tmp_path, call("make_plan", {"fire_id": fire, "crews": 3}), draw(items), say("Done."))
    got = ask(client)
    widget = next(d for n, d in got if n == "widget")["data"]
    shapes = drawn(got)[0]["shapes"]
    assert [(s["role"], s["label"]) for s in shapes] == [("path", "In")] * 3 + [("escape", "Out")] * 3
    assert [s["points"] for s in shapes[:3]] == [tuple(map(tuple, c["route"])) for c in widget["crews"]] or \
        [[list(p) for p in s["points"]] for s in shapes[:3]] == [c["route"] for c in widget["crews"]]
    assert result(model, 2)["warnings"] == []  # the ways of a plan are not checked against their own fire


def test_without_a_plan_in_the_answer_the_default_one_is_drawn(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    client, model = chat(store, tmp_path, draw([{"kind": "reference", "from": f"route:{fire}"}]), say("Done."))
    shapes = drawn(ask(client))[0]["shapes"]
    assert len(shapes) == 2 and {s["role"] for s in shapes} == {"path"}  # two crews
    client, model = chat(store, tmp_path, draw([{"kind": "reference", "from": f"route:{fire}"}]), say("No."), weather=False)
    ask(client)
    assert "there is no plan" in model.tool_results(1)[0]["content"]


def test_safe_zones_of_the_plan_are_not_warned_about(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    client, model = chat(store, tmp_path, draw([{"kind": "reference", "from": f"safe_zones:{fire}"}]), say("Done."))
    ask(client)
    content = model.tool_results(1)[0]["content"]
    assert "WARNING" not in content


def test_a_safe_zone_on_the_fire_and_a_way_out_through_its_front_are_warned_about(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    found = live.find(fire)
    centre = [found.lon, found.lat]
    items = [{"kind": "circle", "center": centre, "radius_km": 0.5, "role": "safe_zone", "label": "Camp"},
             {"kind": "line", "points": [[centre[0] - 0.05, centre[1]], [centre[0] + 0.05, centre[1]]], "role": "escape",
              "label": "Way"},
             {"kind": "circle", "center": [centre[0] + 5, centre[1] + 5], "radius_km": 1, "role": "safe_zone",
              "label": "Far"}]
    client, model = chat(store, tmp_path, draw(items), say("Done."))
    ask(client)
    warnings = result(model)["warnings"]
    assert any("safe zone A1 (Camp)" in w and "lies on fire" in w for w in warnings)
    assert all("A3" not in w for w in warnings) and all(w.startswith("WARNING") for w in warnings)


def test_open_plan_is_an_action(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    client, _ = chat(store, tmp_path, call("open_plan", {"fire_id": fire, "crews": 3, "hours": 6}), say("Opened."))
    got = ask(client)
    assert ("action", {"type": "open_plan", "fire_id": fire, "crews": 3, "hours": 6}) in got
    assert ("step", {"tool": "build_plan"}) in got


def test_open_plan_errors(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    for args, code in [({"fire_id": "nope"}, "not_found"), ({"fire_id": fire, "crews": 21}, "invalid_input"),
                       ({"fire_id": fire, "hours": 2}, "invalid_input")]:
        client, model = chat(store, tmp_path, call("open_plan", args), say("No."))
        assert ask(client)[-1][0] == "done"
        assert code in model.tool_results(1)[0]["content"], args


def test_the_drawing_is_a_step_and_the_tool_and_its_arguments_are_logged(store, tmp_path, live, caplog):  # noqa: F811
    caplog.set_level("INFO")
    client, _ = chat(store, tmp_path, draw([{"kind": "point", "position": [1, 1], "label": "P"}]), say("Done."))
    got = ask(client)
    assert ("step", {"tool": "draw_on_map"}) in got
    assert any("chat tool draw_on_map args=" in r.getMessage() and '"label": "P"' in r.getMessage() for r in caplog.records)


# --- the plan of an earlier answer, the numbers of an earlier answer, the links of the text ---


def plan_chat(store, tmp_path, live, *steps):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    client, model = chat(store, tmp_path, *steps(fire))
    return fire, client, model


def test_safe_zones_with_outlines_that_cross_themselves_are_drawn_from_what_has_an_area(store):
    import random

    from senda_api.blob import blob_of
    from senda_api.chat import drawing
    from senda_api.errors import ApiError

    item = {"kind": "reference", "from": "safe_zones:x"}
    square = [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]
    flat = [[0, 0], [1, 1], [2, 2], [0, 0]]
    bowtie = [[5, 5], [7, 7], [7, 5], [5, 7], [5, 5]]

    def build(zones):
        return drawing.build(store, lambda: None, lambda _: {"safe_zones": zones, "crews": []}, [item], 1, 20)

    built = build([flat, square])
    assert [s.role for s in built.shapes] == ["safe_zone"] and built.from_plan == {"A1"}
    assert len(build([bowtie]).shapes) == 1  # a crossing outline keeps the part that has an area
    with pytest.raises(ApiError, match="no area to draw"):
        build([flat])
    with pytest.raises(ApiError, match="no burned ground"):
        build([])
    random.seed(1)  # what the planner's own blobs give: drawn, or told why not; never "not a valid shape"
    for _ in range(40):
        pts = [(-60 + random.random() * 0.02, -30 + random.random() * 0.02) for _ in range(random.randint(3, 25))]
        corners = [(x + dx, y + dy) for x, y in pts for dx in (-0.0019, 0.0019) for dy in (-0.0017, 0.0017)]
        zones = [p[0] for p in blob_of(corners, 0.0012, 0.0011) or []]
        try:
            assert all(s.kind == "polygon" for s in build(zones).shapes)
        except ApiError as error:
            assert "no area to draw" in error.message


def test_a_drawing_of_a_plan_gives_the_model_the_figures_of_what_is_drawn(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    items = [{"kind": "reference", "from": f"route:{fire}"}, {"kind": "reference", "from": f"escape:{fire}"}]
    client, model = chat(store, tmp_path, draw(items), say("Done."))
    ask(client)
    drew = result(model)["drew"]
    routes, ways = [d for d in drew if "trail_km" in d], [d for d in drew if "way_out_km" in d]
    assert len(routes) == len(ways) == 2 and all({"crew", "trail_min"} <= set(d) for d in routes)
    text = f"Бригада 1: путь {routes[0]['trail_km']} км, {routes[0]['trail_min']} мин, отход {ways[0]['way_out_km']} км."
    assert unverified(text.replace(".", ","), [result(model)], []) == []


def test_a_later_answer_may_quote_the_numbers_of_an_earlier_one_and_only_those(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    client, model = chat(store, tmp_path, call("make_plan", {"fire_id": fire}), say("Plan."), say("Вопрос."),
                         say("Done."))
    first = ask(client)
    out = result(model)
    chat_id = next(d["chat_id"] for n, d in first if n == "start")
    crew = out["crews"][0]
    model.steps[0] = say(f"Тропа {crew['trail_km']} км и {crew['trail_min']} мин.".replace(".", ","))
    second = ask(client, "Повтори.", chat_id)
    text = next(d["text"] for n, d in second if n == "text")
    assert "Тропа" in text  # numbers of the first answer: not refused
    model.steps[:] = [say("Тропа 9 876 км."), say("Тропа 9 876 км.")]
    third = ask(client, "Ещё.", chat_id)
    assert "проверить" in next(d["text"] for n, d in third if n == "text")  # a number nobody gave is refused
    assert all("memory" not in d for _, d in first + second + third)
    saved = client.get(f"/api/chats/{chat_id}").json()["messages"]
    assert all("memory" not in m for m in saved)


def test_the_numbers_of_an_earlier_plan_are_not_taken_from_another_chat(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    client, model = chat(store, tmp_path, call("make_plan", {"fire_id": fire}), say("Plan."), say("Done."))
    ask(client)
    crew = result(model)["crews"][0]
    model.steps[:] = [say(f"Тропа {crew['trail_km']} км.".replace(".", ","))] * 2
    other = ask(client, "New chat.")  # a new chat: the numbers of the first are not its own
    assert "could not check" in next(d["text"] for n, d in other if n == "text")


def test_a_drawing_in_a_new_answer_refers_to_the_plan_the_chat_made_last(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    ref = {"kind": "reference", "from": f"route:{fire}"}
    client, model = chat(store, tmp_path, call("make_plan", {"fire_id": fire, "crews": 3, "hours": 6}), say("Plan."),
                         draw([ref]), say("Drawn."))
    first = ask(client)
    chat_id = next(d["chat_id"] for n, d in first if n == "start")
    second = ask(client, "Show.", chat_id)
    assert len(drawn(second)[0]["shapes"]) == 3  # three crews: not the default two
    assert "hours" not in result(model, 3) and len(result(model, 3)["drew"]) == 3


def test_a_plan_found_through_the_list_of_fires_shows_and_keeps_only_the_plan(store, tmp_path, live):  # noqa: F811
    fire = fire_of(store, tmp_path, live)
    client, _ = chat(store, tmp_path, call("list_fires", {}), call("make_plan", {"fire_id": fire}, call_id="t2"),
                     say("Plan."))
    got = ask(client)
    assert [d["type"] for n, d in got if n == "widget"] == ["work_plan"]
    chat_id = next(d["chat_id"] for n, d in got if n == "done")
    kept = ChatDetail.model_validate(client.get(f"/api/chats/{chat_id}").json())
    assert [w.type for w in kept.messages[1].widgets] == ["work_plan"]


def test_links_to_shapes_that_are_not_drawn_are_cut_from_the_text(store, tmp_path, live):  # noqa: F811
    from senda_api.chat.links import only_known

    assert only_known("[a](shape:A1) [b](shape:A2) [c](shape:A0) [d](https://e.com) [e](fire:1)", 1) == \
        "[a](shape:A1) b [c](shape:A0)".replace("[c](shape:A0)", "c") + " d e"
    shapes = [{"kind": "point", "position": [1, 1], "label": "P"}]
    client, _ = chat(store, tmp_path, draw(shapes), say("Here [P](shape:A1), not [Q](shape:A7)."))
    text = next(d["text"] for n, d in ask(client) if n == "text")
    assert text == "Here [P](shape:A1), not Q."
