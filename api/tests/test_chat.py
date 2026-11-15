from dataclasses import replace
from datetime import date, timedelta

import anthropic
import httpx
import pytest
from fakes import ScriptedModel, call, say
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from senda_api import areas, events, window
from senda_api.app import create_app
from senda_api.chat import loop
from senda_api.chat.llm import AnthropicModel, ModelFailure, ModelRequest
from senda_api.chat.tools import TOOLS, ToolBox
from senda_api.contracts import Widget
from senda_api.settings import Settings

AREA = {"id": "XA"}
QUESTION = [{"role": "user", "text": "How did 2019 look in Xland?"}]
SETTINGS = Settings(anthropic_api_key=None)


def make_client(store, model, settings=SETTINGS):
    return TestClient(create_app(store=store, settings=settings, chat_model=model))


def ask(store, model, messages=QUESTION, settings=SETTINGS):
    """The events of one question through the tool loop."""
    return list(loop.run(model, store, settings, messages))


def calendar_2019(client):
    return client.post("/api/calendar", json={"area": AREA, "from": "2019-01", "to": "2019-12"}).json()


# ---------- availability ----------


def test_without_key_chat_is_off(store):
    assert make_client(store, None).get("/api/meta").json()["chat"] == {"enabled": False}


def test_with_a_model_chat_is_on(store):
    client = make_client(store, ScriptedModel())
    assert client.get("/api/meta").json()["chat"] == {"enabled": True}


def test_key_comes_only_from_settings_and_stays_out_of_repr_and_errors(store, monkeypatch):
    secret = "sk-ant-test-SECRET"
    assert secret not in repr(Settings(anthropic_api_key=secret))
    model = AnthropicModel(secret)

    def boom(**_):
        raise anthropic.APIConnectionError(message=f"cannot reach, key {secret}",
                                           request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(model._client.messages, "create", boom)
    with pytest.raises(ModelFailure) as err:
        model.complete(ModelRequest("m", "s", [], [{"role": "user", "content": "q"}], 10, True, 5.0))
    assert err.value.code == "upstream_error" and secret not in err.value.message
    got = ask(store, model, settings=Settings(anthropic_api_key=secret))
    assert secret not in repr(got)
    assert got[-1] == ("error", {"code": "upstream_error", "message": "The model service failed."})


@pytest.mark.parametrize("status,text", [(402, "billing problem"),
                                         (400, "Your credit balance is too low to access the Anthropic API")])
def test_an_account_out_of_credit_is_told_as_a_spent_day_not_as_a_failure_to_try_again(monkeypatch, status, text):
    model = AnthropicModel("key")
    response = httpx.Response(status, request=httpx.Request("POST", "http://x"))

    def boom(**_):
        raise anthropic.APIStatusError(text, response=response, body=None)

    monkeypatch.setattr(model._client.messages, "create", boom)
    with pytest.raises(ModelFailure) as err:
        model.complete(ModelRequest("m", "s", [], [{"role": "user", "content": "q"}], 10, True, 5.0))
    assert err.value.code == "rate_limited"


def test_another_refusal_of_the_model_service_is_still_a_failure(monkeypatch):
    model = AnthropicModel("key")
    response = httpx.Response(500, request=httpx.Request("POST", "http://x"))

    def boom(**_):
        raise anthropic.APIStatusError("overloaded", response=response, body=None)

    monkeypatch.setattr(model._client.messages, "create", boom)
    with pytest.raises(ModelFailure) as err:
        model.complete(ModelRequest("m", "s", [], [{"role": "user", "content": "q"}], 10, True, 5.0))
    assert err.value.code == "upstream_error"


# ---------- stream ----------


def test_stream_order_tokens_after_tools_then_done(store):
    client_plain = make_client(store, None)
    cal = calendar_2019(client_plain)
    yearly = next(y for y in cal["yearly"] if y["year"] == 2019)
    text = f"In 2019 there were {yearly['count']:,} detections. The area has a clear season."
    model = ScriptedModel(
        call("get_calendar", {"area": AREA, "from": "2019-01", "to": "2019-12"}, text="Let me look. It is 12345 now."),
        say(text),
    )
    got = ask(store, model)
    names = [n for n, _ in got]
    assert names == ["tool", "tool", "token", "token", "done"]
    assert got[0][1] == {"id": "t1", "name": "get_calendar", "status": "running"}
    ok = got[1][1]
    assert ok["status"] == "ok" and ok["args"]["from"] == "2019-01" and "artifact" not in ok
    assert "".join(d["text"] for n, d in got if n == "token") == text
    done = got[-1][1]
    assert done["verified"] is True and done["text"] == text and done["tool_calls"] == 1
    assert done["model"] == SETTINGS.chat_model and done["data_version"] == "test-1"
    assert model.requests[0].tools_allowed and model.requests[0].model == "claude-sonnet-5-5"
    assert "12345" not in done["text"]  # text before a tool call is never shown


def test_number_not_from_tools_is_replaced_by_refusal_text_after_one_retry(store):
    bad = say("There were 987,654,321 detections.")
    model = ScriptedModel(call("get_calendar", {"area": AREA}), bad, bad)
    got = ask(store, model)
    assert [n for n, _ in got] == ["tool", "tool", "done"]
    done = got[-1][1]
    assert done["verified"] is False
    assert done["text"] == "I could not check this answer. Try a suggested question."
    assert len(model.requests) == 3 and not model.requests[2].tools_allowed  # one retry, no more
    assert done["input_tokens"] == 30  # the retry is paid for and counted


def test_a_retry_mends_an_answer_with_a_number_nobody_gave(store):
    model = ScriptedModel(say("Call 911 now."), say("Call the local emergency number now."))
    got = ask(store, model, [{"role": "user", "text": "The forest behind our village is burning, what do I do?"}])
    done = got[-1][1]
    assert done["verified"] is True and done["text"] == "Call the local emergency number now."
    retry = model.requests[1]
    assert not retry.tools_allowed and retry.messages[-2]["role"] == "assistant"
    assert retry.messages[-1]["role"] == "user" and "911" in retry.messages[-1]["content"]
    assert done["input_tokens"] == 20


def test_a_clean_answer_is_not_retried(store):
    model = ScriptedModel(say("Verner answers questions about fire detections."))
    got = ask(store, model)
    assert got[-1][1]["verified"] is True and len(model.requests) == 1


def test_number_from_the_question_is_allowed(store):
    model = ScriptedModel(say("You asked about 4321 detections, I cannot say without data."))
    got = ask(store, model, [{"role": "user", "text": "Were there 4,321 detections?"}])
    assert got[-1][1]["verified"] is True


def test_calendar_tool_matches_calendar_endpoint(store, client):
    cal = client.post("/api/calendar", json={"area": AREA, "from": "2019-01", "to": "2019-12"}).json()
    view = ToolBox(store, SETTINGS).run("get_calendar", {"area": AREA, "from": "2019-01", "to": "2019-12"}).result
    assert view["period"] == {"from": "2019-01", "to": "2019-12"}
    assert view["season"] == cal["season"]
    assert [n["median"] for n in view["normals"]] == [n["median"] for n in cal["normals"]]
    assert [(y["year"], y["count"]) for y in view["yearly"]] == [(y["year"], y["count"]) for y in cal["yearly"]]
    assert [(s["month"], s["count"], s["median"]) for s in view["series"]] == \
           [(s["month"], s["count"], s["median"]) for s in cal["series"]]
    assert view["quality"]["expected_error"] == cal["quality"]["expected_error"]
    assert view["current_month"]["count"] == cal["current_month"]["count"]
    assert view["trend"] == cal["trend"]
    assert "geometry" not in str(view) and len(str(view)) < 9000


def test_calendar_view_drops_series_for_long_periods(store):
    view = ToolBox(store, SETTINGS).run("get_calendar", {"area": AREA}).result
    assert view.get("series_omitted") is True and "series" not in view
    assert all(m["ratio"] >= 2 for m in view["unusual_months"])


# ---------- tool errors do not break the stream ----------


@pytest.mark.parametrize("name,args", [
    ("get_calendar", {"area": AREA, "from": 2019}),          # wrong type
    ("get_calendar", {"area": AREA, "colour": "red"}),       # extra key
    ("get_calendar", {"area": {"id": "NOPE"}}),              # unknown region
    ("get_calendar", {"area": AREA, "from": "2019-13"}),     # bad month
    ("find_region", {"query": "x", "limit": 99}),            # out of range
    ("no_such_tool", {}),
])
def test_bad_tool_input_goes_back_to_the_model(store, name, args):
    model = ScriptedModel(call(name, args), say("I could not read that data."))
    got = ask(store, model)
    tool = [d for n, d in got if n == "tool"]
    assert tool[-1]["status"] == "error" and tool[-1]["code"]
    results = model.tool_results(1)
    assert results[0]["is_error"] is True and results[0]["tool_use_id"] == "t1"
    assert got[-1][0] == "done" and got[-1][1]["verified"] is True


def test_tool_crash_is_a_tool_error_not_a_server_error(store, monkeypatch):
    def broken(self, args):
        raise RuntimeError("boom")

    monkeypatch.setattr(ToolBox, "_get_calendar", broken)
    model = ScriptedModel(call("get_calendar", {"area": AREA}), say("The data is not available."))
    got = ask(store, model)
    assert [d["code"] for n, d in got if n == "tool" and d["status"] == "error"] == ["internal_error"]
    assert got[-1][0] == "done"


# ---------- the other tools ----------


def test_month_weather_gives_the_rain_and_the_temperature_against_their_normals(store, tmp_path):
    from climate_files import write

    from senda_api.chat.tools import ToolError
    from senda_api.climate import Climate

    grid = Climate.open(write(tmp_path / "climate" / "current"))
    box = ToolBox(store, SETTINGS, climate=lambda: grid)
    out = box.run("get_month_weather", {"area": AREA, "month": "2025-06"}).result
    assert out["kind"] == "observed" and out["area_name"] == "Xland" and out["normal_years"]["first"] <= out["normal_years"]["last"]
    assert out["temperature_c"] == {"value": 17.0, "normal": 16.0, "rank": 1, "of_years": 2, "difference_c": 1.0}
    # the rain comes as a change in percent of its normal: twice the normal is 100 percent more
    assert out["rain_mm"] == {"value": 100.0, "normal": 50.0, "rank": 1, "of_years": 2, "change_from_normal_pct": 100}
    # the percent is one the answer may quote, above the normal or below it
    from senda_api.chat.verify import unverified
    assert unverified("Rain was 100 % above its normal.", [out], []) == []
    assert unverified("Rain was 50 % below its normal.", [{"rain_mm": {"change_from_normal_pct": -50}}], []) == []
    assert unverified("Rain was 60 % below its normal.", [out], []) == ["60 %"]
    assert box.run("get_month_weather", {"area": AREA, "month": "2025-07"}).result == {
        "area_name": "Xland", "month": "2025-07", "kind": "none"}
    with pytest.raises(ToolError) as refused:
        ToolBox(store, SETTINGS).run("get_month_weather", {"area": AREA, "month": "2025-06"})
    assert refused.value.code == "unavailable"


def test_month_weather_shows_a_card_with_the_figures_of_the_answer(store, tmp_path):
    from climate_files import write

    from senda_api.climate import Climate
    from senda_api.climate_routes import month_weather

    grid = Climate.open(write(tmp_path / "climate" / "current"))
    box = ToolBox(store, SETTINGS, climate=lambda: grid)
    got = box.run("get_month_weather", {"area": AREA, "month": "2025-06"})
    card = TypeAdapter(Widget).validate_python(got.widget).model_dump(mode="json")
    # the card is the answer of /api/climate/month for that area and month
    assert card == {"type": "month_weather", "data": month_weather(grid, areas.parse(AREA, store), "XA", "2025-06")}
    by = {q["key"]: q for q in card["data"]["observed"]["quantities"]}
    assert by["rain_mm"]["change_pct"] == got.result["rain_mm"]["change_from_normal_pct"] == 100
    assert by["temperature_c"]["anomaly"] == got.result["temperature_c"]["difference_c"]
    assert by["temperature_c"]["change_pct"] is None
    # a month without weather has no card
    assert box.run("get_month_weather", {"area": AREA, "month": "2025-07"}).widget is None


def test_check_event_shows_the_month_card_with_the_figures_it_answers(store, client):
    from senda_api.months import month_label

    for month in ("2010-08", "2019-09", month_label(store.cur_month)):
        got = ToolBox(store, SETTINGS).run("check_event", {"area": AREA, "month": month})
        card = TypeAdapter(Widget).validate_python(got.widget).model_dump(mode="json")
        detail, out = card["data"], got.result
        assert card["type"] == "month_detail" and detail["month"] == out["month"] == month
        # the text and the card: the same count, normal, ratio and place
        assert (out["count"], out["median"], out["ratio"]) == (detail["value"], detail["normal"], detail["ratio"])
        assert (out["rank"], out["of"]) == ((detail["rank"] or {}).get("place"), (detail["rank"] or {}).get("of"))
        assert out["unusual"] is events.is_found(out["ratio"], out["rank"])
        # and the card is the month of the calendar screen
        route = client.get("/api/calendar/month", params={"area": "XA", "month": month}).json()
        assert (route["value"], route["normal"], route["rank"]) == (detail["value"], detail["normal"], detail["rank"])
    assert got.result["partial"] is True


def test_check_event_of_a_drawn_area_and_outside_the_archive(store):
    from senda_api.chat.tools import ToolError

    drawn = {"U1": {"type": "Polygon", "coordinates": [[[20, 9], [21, 9], [21, 10], [20, 9]]]}}
    got = ToolBox(store, SETTINGS, areas_drawn=drawn).run("check_event", {"area": {"drawn": "U1"}, "month": "2019-09"})
    assert got.widget["data"]["area"]["kind"] == "drawn" and got.result["area_name"] == "Drawn area U1"
    for month in ("1999-01", "2099-01"):
        with pytest.raises(ToolError):
            ToolBox(store, SETTINGS).run("check_event", {"area": AREA, "month": month})


def test_get_window_shows_a_card_with_the_figures_it_answers(store):
    got = ToolBox(store, SETTINGS).run("get_window", {"area": AREA, "start": "2025-07-01", "end": "2025-07-31"})
    card = TypeAdapter(Widget).validate_python(got.widget).model_dump(mode="json")
    assert card["type"] == "window_stats" and card["data"]["area"] == {"id": "XA", "name": "Xland"}
    for key in ("count", "median", "p10", "p90", "rank", "of", "ratio", "years", "window", "partial", "complete_through"):
        assert card["data"][key] == got.result[key], key
    # dates after the last complete day have no data and no card
    later = (store.last_complete_date + timedelta(days=5)).isoformat()
    assert ToolBox(store, SETTINGS).run("get_window", {"area": AREA, "start": later, "end": later}).widget is None


def test_find_region(store):
    out = ToolBox(store, SETTINGS).run("find_region", {"query": "xland", "limit": 3}).result
    assert out["regions"][0]["id"] == "XA" and set(out["regions"][0]) == {"id", "kind", "country_name", "name", "bbox"}


def test_check_event_uses_the_event_rule(store):
    out = ToolBox(store, SETTINGS).run("check_event", {"area": AREA, "month": "2010-08"}).result
    assert out["unusual"] is events.is_found(out["ratio"], out["rank"])
    assert out["month"] == "2010-08" and out["count"] > 0


def test_get_window_matches_the_window(store):
    body = {"area": AREA, "start": "2025-07-01", "end": "2025-07-31"}
    want = window.compare(store, areas.parse(AREA, store), date(2025, 7, 1), date(2025, 7, 31), SETTINGS.window_max_area_km2)
    got = ToolBox(store, SETTINGS).run("get_window", body).result
    for key in ("count", "median", "rank", "of", "ratio", "years", "window", "partial"):
        assert got[key] == want[key], key


# ---------- schemas ----------


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def test_schemas_use_only_accepted_keys():
    allowed = {"type", "properties", "required", "additionalProperties", "anyOf", "items", "enum", "description", "minItems"}
    for tool in TOOLS:
        assert set(tool) == {"name", "description", "input_schema"}
        for node in walk(tool["input_schema"]):
            if "type" in node or "anyOf" in node:
                assert set(node) <= allowed, (tool["name"], set(node) - allowed)
            assert node.get("minItems", 0) in (0, 1)


# ---------- the loop ----------


def test_rounds_are_limited_and_the_last_runs_without_tools(store):
    steps = [call("find_region", {"query": "xland"}, call_id=f"t{i}") for i in range(5)] + [say("Xland is a country.")]
    model = ScriptedModel(*steps)
    got = ask(store, model)
    assert len(model.requests) == SETTINGS.chat_max_rounds == 6
    assert [r.tools_allowed for r in model.requests] == [True] * 5 + [False]
    assert got[-1][0] == "done"


def test_model_asking_for_tools_on_the_last_round_gets_no_tool_run(store):
    steps = [call("find_region", {"query": "xland"}, call_id=f"t{i}") for i in range(6)]
    model = ScriptedModel(*steps)
    got = ask(store, model)
    assert len([1 for n, d in got if n == "tool" and d["status"] == "running"]) == 5
    assert got[-1][1]["verified"] is False  # nothing to show


@pytest.mark.parametrize("failure,code", [(ModelFailure("upstream_error", "x"), "upstream_error"),
                                          (ModelFailure("timeout", "x"), "timeout"),
                                          (RuntimeError("boom"), "internal_error")])
def test_model_failure_ends_with_error_event(store, failure, code):
    got = ask(store, ScriptedModel(failure))
    assert [n for n, _ in got] == ["error"] and got[0][1]["code"] == code


def test_refusal_stop_reason(store):
    turn = replace(say("no"), stop_reason="refusal")
    got = ask(store, ScriptedModel(turn))
    assert got == [("error", {"code": "refused", "message": "The model declined to answer."})]


def test_deadline(store):
    settings = replace(SETTINGS, chat_deadline_s=0.0)
    got = ask(store, ScriptedModel(say("hi")), settings=settings)
    assert got[0][1]["code"] == "timeout"


def test_history_is_sent_as_plain_text(store):
    model = ScriptedModel(say("Fine."))
    ask(store, model, [{"role": "user", "text": "hello"}, {"role": "assistant", "text": "hi"},
                                    {"role": "user", "text": "and 2019?"}])
    assert model.requests[0].messages == [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"},
                                          {"role": "user", "content": "and 2019?"}]


def test_sentences_split_keeps_decimals():
    assert list(loop.sentences("It was 5.51 times. Then 2 more.\n- one\n- two")) == \
           ["It was 5.51 times. ", "Then 2 more.\n", "- one\n", "- two"]


# ---------- input limits ----------


def u(text):
    return {"role": "user", "text": text}


def a(text):
    return {"role": "assistant", "text": text}


def test_limit_of_exact_size_passes(store):
    msgs = [u("q")] + [m for i in range(7) for m in (a("x"), u("y"))]
    assert len(msgs) == 15  # the longest dialogue that ends with a question from the person
    msgs[-1] = u("w" * 1500)
    got = ask(store, ScriptedModel(say("Ok.")), msgs)
    assert got[-1][0] == "done"


def test_the_model_is_told_to_lead_with_to_date_for_a_partial_month():
    from senda_api.chat.prompt import SYSTEM
    from senda_api.chat.tools import TOOLS

    assert "first and main comparison is with the same dates of earlier years" in SYSTEM
    calendar_tool = next(t for t in TOOLS if t["name"] == "get_calendar")
    assert "first and main comparison is current_month.to_date" in calendar_tool["description"]


def test_calendar_view_carries_to_date_for_the_running_month(store):
    from senda_api import areas, calendar
    from senda_api.chat.tools import calendar_view

    cal = calendar.build(store, areas.parse({"id": "XA"}, store), None, None)
    view = calendar_view(cal, store.first_month, store.cur_month)
    assert set(view["current_month"]["to_date"]) == {"through", "count", "median", "ratio", "rank", "of"}
