"""Chats and plans in Postgres: one browser's label, files, cascade, and the site without a database."""

from datetime import timedelta

import pytest
from fakes import ScriptedModel, call, parse_sse, say
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from test_fire_plan import west
from test_fires import live  # noqa: F401
from weather_files import START, write

from senda_api import plans_routes
from senda_api.app import create_app
from senda_api.chat import api as chat_api
from senda_api.client import COOKIE
from senda_api.contracts import FireDetail, FirePlan
from senda_api.settings import Settings


@pytest.fixture(autouse=True)
def _free_gate():
    chat_api.GATE._active.clear()


def app_of(store, tmp_path, *steps, database_url="env"):
    folder = write(tmp_path / "weather" / "current", start=START + timedelta(days=1))
    settings = Settings(anthropic_api_key=None, weather_dir=folder)
    if database_url != "env":
        settings = Settings(anthropic_api_key=None, weather_dir=folder, database_url=database_url)
    return create_app(store=store, settings=settings, chat_model=ScriptedModel(*steps))


def ask(client, text="Prepare it", chat="new"):
    got = parse_sse(client.post(f"/api/chats/{chat}/messages", json={"text": text}).text)
    return next(d["chat_id"] for n, d in got if n == "start"), got


# the label of a browser

def test_the_cookie_is_set_once_and_keeps_chats_apart(store, tmp_path, database, live):  # noqa: F811
    app = app_of(store, tmp_path, call("prepare_file", {"kind": "fires", "region": "XA"}), say("Done."), say("Two."))
    a, b = TestClient(app), TestClient(app)
    cid, got = ask(a)
    cookie = a.cookies.get(COOKIE)
    assert cookie and len(cookie) == 36
    fid = next(d["data"]["id"] for n, d in got if n == "widget" and d["type"] == "file")
    assert [c["id"] for c in a.get("/api/chats").json()] == [cid]
    assert b.get("/api/chats").json() == []
    assert b.get(f"/api/chats/{cid}").status_code == 404
    assert b.get(f"/api/chats/{cid}/files/{fid}").status_code == 404
    assert b.delete(f"/api/chats/{cid}").status_code == 404
    assert b.post(f"/api/chats/{cid}/messages", json={"text": "x"}).status_code == 404
    assert a.get(f"/api/chats/{cid}/files/{fid}").status_code == 200
    assert b.cookies.get(COOKIE) != cookie
    other, _ = ask(b, "mine")
    assert [c["id"] for c in b.get("/api/chats").json()] == [other] and [c["id"] for c in a.get("/api/chats").json()] == [cid]


def test_the_cookie_is_http_only_lax_for_the_api_and_lasts_a_year(store, tmp_path, database):
    client = TestClient(app_of(store, tmp_path, say("Fine.")))
    first = client.get("/api/chats").headers["set-cookie"].lower()
    assert f"{COOKIE}=" in first and "httponly" in first and "samesite=lax" in first and "path=/api" in first
    assert f"max-age={365 * 24 * 3600}" in first
    assert "set-cookie" not in client.get("/api/chats").headers  # the browser has it now
    streamed = TestClient(app_of(store, tmp_path, say("Fine.")))
    assert COOKIE in streamed.post("/api/chats/new/messages", json={"text": "hi"}).headers["set-cookie"]
    broken = TestClient(app_of(store, tmp_path), cookies={COOKIE: "not-a-uuid"})
    assert COOKIE in broken.get("/api/chats").headers["set-cookie"]


def test_deleting_a_chat_deletes_its_messages_and_files_in_the_database(store, tmp_path, database, live):  # noqa: F811
    client = TestClient(app_of(store, tmp_path, call("prepare_file", {"kind": "fires", "region": "XA"}), say("Done.")))
    cid, _ = ask(client)
    engine = create_engine(database)

    def counts():
        with engine.connect() as conn:
            return [conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in ("chats", "messages", "chat_files")]

    assert counts() == [1, 2, 1]
    assert client.delete(f"/api/chats/{cid}").status_code == 204
    assert counts() == [0, 0, 0]
    engine.dispose()


# plans

def plan_client(store, tmp_path):
    return TestClient(app_of(store, tmp_path))


def test_a_plan_is_saved_listed_opened_and_deleted(store, tmp_path, database, live):  # noqa: F811
    client = plan_client(store, tmp_path)
    fire = west(client)
    res = client.post("/api/plans", json={"fire_id": fire, "title": "Night", "request": {"crews": 3, "hours": 6}})
    assert res.status_code == 201, res.text
    record = res.json()
    FirePlan.model_validate(record["plan"])
    FireDetail.model_validate(record["fire"])
    assert record["title"] == "Night" and record["fire_id"] == fire and record["request"]["crews"] == 3
    assert record["plan"]["pass_index"] == record["fire"]["pass_index"]
    [item] = client.get("/api/plans").json()
    assert item == {"id": record["id"], "title": "Night", "fire_id": fire, "near": "Westville", "crews": 3, "hours": 6,
                    "created_at": record["created_at"]}
    assert client.get(f"/api/plans/{record['id']}").json() == record
    assert client.delete(f"/api/plans/{record['id']}").status_code == 204
    assert client.get(f"/api/plans/{record['id']}").status_code == 404 and client.get("/api/plans").json() == []
    assert client.delete(f"/api/plans/{record['id']}").status_code == 404


def test_plans_are_a_browsers_own(store, tmp_path, database, live):  # noqa: F811
    app = app_of(store, tmp_path)
    a, b = TestClient(app), TestClient(app)
    plan_id = a.post("/api/plans", json={"fire_id": west(a), "request": {}}).json()["id"]
    assert b.get("/api/plans").json() == [] and b.get(f"/api/plans/{plan_id}").status_code == 404
    assert b.delete(f"/api/plans/{plan_id}").status_code == 404 and len(a.get("/api/plans").json()) == 1


def test_plan_errors_and_the_limit(store, tmp_path, database, live, monkeypatch):  # noqa: F811
    client = plan_client(store, tmp_path)
    assert client.post("/api/plans", json={"fire_id": "nope", "request": {}}).status_code == 404
    assert client.post("/api/plans", json={"fire_id": west(client), "request": {"crews": 99}}).status_code == 422
    assert client.get("/api/plans/0").status_code == 422
    monkeypatch.setattr(plans_routes, "MAX_PLANS", 1)
    assert client.post("/api/plans", json={"fire_id": west(client), "request": {}}).status_code == 201
    over = client.post("/api/plans", json={"fire_id": west(client), "request": {}})
    assert over.status_code == 409 and over.json()["error"]["code"] == "conflict"


def test_a_plan_without_wind_data_is_not_saved(store, live, database):  # noqa: F811
    client = TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None)))
    res = client.post("/api/plans", json={"fire_id": west(client), "request": {}})
    assert res.status_code == 409 and res.json()["error"]["code"] == "plan_unavailable"
    assert client.get("/api/plans").json() == []


# health, and the site without the database

def test_health_tells_the_truth_about_the_database(store, tmp_path, database):
    client = TestClient(app_of(store, tmp_path))
    body = client.get("/api/health").json()
    assert body["database"] == "ok" and body["schema_revision"] == "ok" and body["status"] == "ok"
    engine = create_engine(database)
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = '0000'"))
        assert client.get("/api/health").json()["schema_revision"] == "outdated"
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = '0004'"))
        engine.dispose()
    assert client.get("/api/health").json()["schema_revision"] == "ok"


@pytest.mark.parametrize("url", [None, "postgresql+psycopg://senda:x@127.0.0.1:1/senda"])
def test_without_the_database_chats_and_plans_say_503_and_the_rest_works(store, tmp_path, url):
    client = TestClient(app_of(store, tmp_path, say("Fine."), database_url=url))
    for res in (client.get("/api/chats"), client.get("/api/chats/" + "0" * 8 + "-0000-0000-0000-" + "0" * 12),
                client.post("/api/chats/new/messages", json={"text": "hi"}), client.get("/api/plans"),
                client.post("/api/plans", json={"fire_id": "x", "request": {}})):
        assert res.status_code == 503 and res.json()["error"]["code"] == "storage_unavailable", res.text
    health = client.get("/api/health").json()
    assert health["database"] == "down" and health["schema_revision"] == "unknown" and health["status"] == "ok"
    assert client.get("/api/meta").status_code == 200
    assert client.post("/api/calendar", json={"area": {"id": "XA"}}).status_code == 200
    assert client.get("/api/fires").status_code == 200
    assert chat_api.GATE._active == {}  # the question that failed to start did not keep the gate


def test_the_answer_and_the_board_of_a_question_are_kept_in_the_database(store, tmp_path, database):
    client = TestClient(app_of(store, tmp_path, say("Fine.")))
    got = parse_sse(client.post("/api/chats/new/messages",
                                json={"text": "How is it?", "board": {"tab": "fires", "area": "XA"}}).text)
    cid = got[0][1]["chat_id"]
    messages = client.get(f"/api/chats/{cid}").json()["messages"]
    assert [(m["role"], m["text"]) for m in messages] == [("user", "How is it?"), ("assistant", "Fine.")]
    engine = create_engine(database)
    with engine.connect() as conn:
        boards = conn.execute(text("SELECT board FROM messages ORDER BY seq")).scalars().all()
    engine.dispose()
    assert boards == [{"tab": "fires", "area": "XA", "facts": []}, None]
