import json
import time
import uuid

import pytest
from fakes import ScriptedModel, call, parse_sse, say
from fastapi.testclient import TestClient
from shapes import check
from sqlalchemy import select, update

from senda_api import areas
from senda_api.app import create_app
from senda_api.chat import api as chat_api
from senda_api.contracts import ChatDetail, DoneData, ErrorBody, RegionList
from senda_api.models import Chat, Message
from senda_api.schemas import Calendar
from senda_api.settings import Settings

AREA = {"id": "XA"}
SETTINGS = Settings(anthropic_api_key=None)

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture(autouse=True)
def _free_gate():
    chat_api.GATE._active.clear()


def make(store, model):
    return TestClient(create_app(store=store, settings=SETTINGS, chat_model=model))


def ask(client, chat_id="new", **body):
    body.setdefault("text", "How did 2019 look in Xland?")
    return client.post(f"/api/chats/{chat_id}/messages", json=body)


def yearly_2019(store, client):
    cal = client.post("/api/calendar", json={"area": AREA, "from": "2019-01", "to": "2019-12"}).json()
    return next(y for y in cal["yearly"] if y["year"] == 2019)["count"]


def test_without_a_key_the_unavailable_error(store):
    res = ask(make(store, None))
    assert res.status_code == 503 and res.json()["error"]["code"] == "unavailable"
    check("ErrorResponse", res.json())


def test_answer_streams_events_and_the_chat_is_kept(store):
    client = make(store, None)
    count = yearly_2019(store, client)
    text = f"In 2019 there were {count:,} detections."
    model = ScriptedModel(call("get_calendar", {"area": AREA, "from": "2019-01", "to": "2019-12"}), say(text))
    client = make(store, model)
    res = ask(client)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
    got = parse_sse(res.text)
    assert [n for n, _ in got] == ["start", "step", "widget", "text", "done"]
    assert got[1][1] == {"tool": "area_calendar"}
    assert got[2][1]["type"] == "area_calendar"
    Calendar.model_validate(got[2][1]["data"])
    assert got[3][1]["text"] == text
    assert got[0][1]["chat_id"] == got[-1][1]["chat_id"]
    done = got[-1][1]
    DoneData.model_validate(done)
    assert set(done) == {"chat_id"}
    chats = client.get("/api/chats").json()
    assert [c["id"] for c in chats] == [done["chat_id"]]
    check("ChatSummary", chats[0])
    detail = client.get(f"/api/chats/{done['chat_id']}").json()
    ChatDetail.model_validate(detail)
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] and detail["messages"][1]["text"] == text
    assert detail["messages"][1]["widgets"][0]["type"] == "area_calendar"
    assert detail["title"].startswith("How did 2019")


def test_follow_up_continues_the_chat_with_its_history(store):
    model = ScriptedModel(say("It was a busy year."), say("Less than the year before."))
    client = make(store, model)
    first = parse_sse(ask(client).text)[-1][1]["chat_id"]
    second = parse_sse(ask(client, first, text="And the year after?").text)
    assert second[-1][0] == "done" and second[-1][1]["chat_id"] == first
    sent = [m["content"] for m in model.requests[1].messages]
    assert len(sent) == 3 and sent[1] == "It was a busy year." and sent[2].startswith("And the year after?")
    assert len(client.get(f"/api/chats/{first}").json()["messages"]) == 4
    assert len(client.get("/api/chats").json()) == 1


def test_board_and_attachments_reach_the_model(store):
    model = ScriptedModel(say("Fine."))
    client = make(store, model)
    ask(client, board={"area": "XA", "first_month": "2019-01", "last_month": "2019-12", "fire_id": None, "areas": []},
        attachments=[{"kind": "month", "area": "XA", "month": "2019-05"}])
    prompt = model.requests[0].messages[0]["content"]
    assert "area XA, months 2019-01 to 2019-12" in prompt and "attached month 2019-05 in area XA" in prompt


def test_an_area_drawn_on_the_map_is_read_by_its_name(store):
    corners = [[20, 9], [21, 9], [21, 10]]
    asked = {"area": {"drawn": "U1"}, "from": "2019-01", "to": "2019-12"}
    model = ScriptedModel(call("get_calendar", asked), say("Fine."))
    got = parse_sse(ask(make(store, model), board={"tab": "calendar", "drawn_area": "U1", "first_month": "2019-01",
                                                   "last_month": "2019-12",
                                                   "areas": [{"id": "U1", "polygon": corners, "role": "area"}]}).text)
    prompt = model.requests[0].messages[0]["content"]
    # the model is told the name and how to pass it; the corners stay with the server
    assert "the calendar shows drawn area U1, months 2019-01 to 2019-12" in prompt and '{"drawn": "<name>"}' in prompt
    assert "[20" not in prompt
    widget = next(d for n, d in got if n == "widget")
    by_corners = areas.parse({"polygon": {"type": "Polygon", "coordinates": [[*corners, corners[0]]]}}, store)
    assert widget["type"] == "area_calendar" and widget["data"]["area"]["area_km2"] == round(by_corners.area_km2)
    assert widget["data"]["area"]["name"] == "Drawn area U1"
    assert [name for name, _ in got][-1] == "done"


def test_an_attached_area_is_read_by_its_name_and_an_unknown_name_is_refused(store):
    model = ScriptedModel(call("get_calendar", {"area": {"drawn": "U7"}}), say("I cannot see it."))
    ask(make(store, model), attachments=[{"kind": "area", "id": "U2", "polygon": [[20, 9], [21, 9], [21, 10]]}])
    assert "attached drawn area U2" in model.requests[0].messages[0]["content"]
    assert "a question that names no place is about drawn area U2" in model.requests[0].messages[0]["content"]
    refused = json.dumps(model.requests[1].messages[-1]["content"])
    assert "There is no drawn area U7" in refused and "U2" in refused
    assert make(store, ScriptedModel(say("x"))).post("/api/chats/new/messages", json={
        "text": "x", "board": {"areas": [{"id": "U1", "polygon": [[20, 9], [21, 9]]}]}}).status_code == 422


def test_an_area_drawn_beside_the_area_of_the_board_is_what_a_question_without_a_place_is_about(store):
    model = ScriptedModel(say("Fine."))
    corners = [[20, 9], [21, 9], [21, 10]]
    ask(make(store, model), board={"tab": "fires", "area": "XA", "areas": [
        {"id": "U1", "polygon": corners, "role": "area"}, {"id": "U2", "polygon": corners, "role": "safe_zone"}]})
    prompt = model.requests[0].messages[0]["content"]
    assert "area XA" in prompt and "areas drawn on the map: U1, U2 (safe zone)" in prompt
    assert "a question that names no place is about drawn area U1, not about the area of the board" in prompt


def test_region_search_gives_a_region_list_widget(store):
    model = ScriptedModel(call("find_region", {"query": "west"}), say("It is the west province."))
    got = parse_sse(ask(make(store, model)).text)
    widget = next(d for n, d in got if n == "widget")
    assert widget["type"] == "region_list" and [r["id"] for r in widget["data"]["regions"]] == ["XA-W"]
    RegionList.model_validate(widget["data"])


def test_a_month_and_a_date_window_come_as_cards_and_the_chat_keeps_them(store):
    model = ScriptedModel(call("check_event", {"area": AREA, "month": "2019-09"}),
                          call("get_window", {"area": AREA, "start": "2025-07-01", "end": "2025-07-31"}, call_id="t2"),
                          say("Fine."))
    client = make(store, model)
    got = parse_sse(ask(client).text)
    cards = [d for n, d in got if n == "widget"]
    assert [c["type"] for c in cards] == ["month_detail", "window_stats"]
    assert ("step", {"tool": "month_detail"}) in got and ("step", {"tool": "period_stats"}) in got
    month, window = (json.loads(r[0]["content"]) for r in (model.tool_results(1), model.tool_results(2)))
    assert cards[0]["data"]["month"] == month["month"] and cards[0]["data"]["value"] == month["count"]
    assert cards[1]["data"]["window"] == window["window"] and cards[1]["data"]["count"] == window["count"]
    chat = got[-1][1]["chat_id"]
    kept = ChatDetail.model_validate(client.get(f"/api/chats/{chat}").json())
    assert [w.type for w in kept.messages[1].widgets] == ["month_detail", "window_stats"]


def test_unchecked_number_is_replaced_and_still_streams_text(store):
    got = parse_sse(ask(make(store, ScriptedModel(say("There were 987654 fires."), say("There were 987654 fires.")))).text)
    assert [n for n, _ in got] == ["start", "text", "done"] and "987654" not in got[1][1]["text"]


def test_model_failure_is_an_error_event(store):
    from senda_api.chat.llm import ModelFailure

    got = parse_sse(ask(make(store, ScriptedModel(ModelFailure("timeout", "slow")))).text)
    assert got[-1][0] == "error" and got[-1][1]["code"] == "upstream_error"
    ErrorBody.model_validate(got[-1][1])
    client = make(store, ScriptedModel(ModelFailure("timeout", "slow")))
    ask(client)
    assert client.get("/api/chats").json() == []  # a failed answer is not kept


def test_errors(store):
    client = make(store, ScriptedModel(say("Fine.")))
    assert ask(client, text="").status_code == 422
    assert client.post("/api/chats/new/messages", json={}).json()["error"]["code"] == "validation_error"
    assert ask(client, "bad id").status_code == 422
    assert ask(client, "11111111-1111-1111-1111-111111111111").json()["error"]["code"] == "not_found"
    assert ask(client, text="x" * 1600).json()["error"]["code"] == "payload_too_large"
    assert client.get("/api/chats/11111111-1111-1111-1111-111111111111").status_code == 404
    assert client.delete("/api/chats/11111111-1111-1111-1111-111111111111").status_code == 404


def test_delete_and_busy(store):
    model = ScriptedModel(say("Fine."))
    client = make(store, model)
    chat_id = parse_sse(ask(client).text)[-1][1]["chat_id"]
    assert client.delete(f"/api/chats/{chat_id}").status_code == 204
    assert client.get("/api/chats").json() == []
    chat_api.GATE.acquire("unknown")  # the test client's host is no address: its key is `unknown`
    busy = ask(make(store, ScriptedModel(say("Fine."))))
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "chat_busy"


def test_schema_describes_the_event_stream(client):
    schema = client.get("/api/openapi.json").json()
    post = schema["paths"]["/api/chats/{chat_id}/messages"]["post"]
    stream = post["responses"]["200"]["content"]["text/event-stream"]["schema"]
    names = {x["$ref"].rsplit("/", 1)[1] for x in stream.get("oneOf", stream.get("anyOf"))}
    assert names == {"StartEvent", "StepEvent", "TextEvent", "WidgetEvent", "ActionEvent", "DoneEvent", "ErrorEvent"}
    assert post["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/ChatQuestion")
    assert schema["components"]["schemas"]["WorkPlanWidget"]["properties"]["data"]["$ref"].endswith("/FirePlan")
    assert "PlanResult" not in schema["components"]["schemas"]


def test_a_reader_that_goes_away_keeps_the_chat_and_what_was_said(store):
    """The client drops the connection after the first event, while the model is still thinking: the chat exists
    under the id it was given, holds the question, and the client's slot is freed once the loop ends."""
    import asyncio
    import json
    import threading

    release = threading.Event()

    class Slow(ScriptedModel):
        def complete(self, request):
            release.wait(5)
            return super().complete(request)

    app = create_app(store=store, settings=SETTINGS, chat_model=Slow(say("Fine.")))
    body = json.dumps({"text": "How did 2019 look in Xland?"}).encode()
    sent: list[dict] = []
    seen = asyncio.Event()
    calls = []

    async def receive():
        calls.append(1)
        if len(calls) == 1:
            return {"type": "http.request", "body": body, "more_body": False}
        await seen.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            seen.set()

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": "/api/chats/new/messages", "raw_path": b"/api/chats/new/messages", "query_string": b"",
             "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
             "client": ("203.0.113.7", 5000), "server": ("test", 80)}

    async def run():
        task = asyncio.create_task(app(scope, receive, send))
        await seen.wait()
        await asyncio.sleep(0.2)
        release.set()  # the model answers after the reader has gone
        await asyncio.wait_for(task, 5)

    asyncio.run(run())
    first = next(m["body"] for m in sent if m["type"] == "http.response.body" and m.get("body"))
    start = parse_sse(first.decode())[0]
    assert start[0] == "start"
    cid = uuid.UUID(start[1]["chat_id"])

    def stored():
        with app.state.db.session() as session:
            chats = session.scalars(select(Chat)).all()
            messages = session.scalars(select(Message).order_by(Message.seq)).all()
            return [(c.id, c.title) for c in chats], [(m.role, m.text) for m in messages]

    chats, messages = stored()
    assert [c[0] for c in chats] == [cid] and chats[0][1].startswith("How did 2019")
    for _ in range(50):  # the loop ends on its own thread
        if chat_api.GATE._active == {} and len(stored()[1]) == 2:
            break
        time.sleep(0.1)
    assert chat_api.GATE._active == {}
    messages = stored()[1]
    assert [m[0] for m in messages] == ["user", "assistant"] and messages[0][1].startswith("How did 2019")


def test_the_board_goes_to_the_model_and_the_chat_keeps_only_the_words_of_the_person(store):
    model = ScriptedModel(say("Fine."))
    client = make(store, model)
    board = {"tab": "fires", "area": "XA", "area_name": "Xland", "first_month": "2019-01", "last_month": "2019-12",
             "month": "2019-05", "fire_id": "f1"}
    done = parse_sse(ask(client, text="Which fire grows fastest?", board=board).text)[-1][1]
    prompt = model.requests[0].messages[0]["content"]
    assert prompt.startswith("Which fire grows fastest?")
    assert "tab fires" in prompt and "area XA (Xland)" in prompt and "selected month 2019-05" in prompt
    assert "fire f1 is open" in prompt
    detail = client.get(f"/api/chats/{done['chat_id']}").json()
    assert detail["messages"][0]["text"] == "Which fire grows fastest?" and detail["title"] == "Which fire grows fastest?"
    assert client.post("/api/chats/new/messages", json={"text": "x", "board": {"month": "bad"}}).status_code == 422


def test_a_board_tail_is_cut_from_titles_and_texts(store):
    client = make(store, ScriptedModel(say("Fine.")))
    done = parse_sse(ask(client, text="How is it? [tab: calendar; area: Xland (XA); period: 2019-01..2019-12]").text)[-1][1]
    assert client.get("/api/chats").json()[0]["title"] == "How is it?"
    detail = client.get(f"/api/chats/{done['chat_id']}").json()
    assert detail["messages"][0]["text"] == "How is it?"
    with client.app.state.db.session() as session:  # a stored title with its board line, cut at 60 characters
        session.execute(update(Chat).values(title="How is it? [tab: calendar; area: Xlan"))
    assert client.get("/api/chats").json()[0]["title"] == "How is it?"


def test_figures_from_the_board_reach_the_model_and_their_numbers_count_as_the_persons(store):
    model = ScriptedModel(say("In 2020 there were 398 detections."))
    client = make(store, model)
    done = parse_sse(ask(client, text="Is that a lot?", board={"facts": ["Year 2020: 398 (Xland, 2020)"]}).text)
    assert "figure Year 2020: 398 (Xland, 2020)" in model.requests[0].messages[0]["content"]
    assert [n for n, _ in done] == ["start", "text", "done"] and done[-1][1]["chat_id"]  # 398 passed the number check
    assert client.post("/api/chats/new/messages", json={"text": "x", "board": {"facts": ["a"] * 11}}).status_code == 422
