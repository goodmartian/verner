import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from senda_api import access
from senda_api.app import create_app
from senda_api.db import Database
from senda_api.limits import DailyCounter, SlotResponse, Slots
from senda_api.settings import Settings

BODY = {"area": {"id": "XA"}}
DOWN = "postgresql+psycopg://senda:x@127.0.0.1:1/senda"  # nothing listens there
HOME = ("198.51.100.7", 5000)


def app_with(store, **settings):
    settings.setdefault("anthropic_api_key", None)
    return create_app(store=store, settings=Settings(**settings))


def ticket(client, body=BODY):
    return client.post("/api/export/ticket", json=body)


@pytest.fixture
def kept(store, database):
    """Apps on the test database: a new one is the same server after a restart."""
    return lambda **settings: app_with(store, **settings)


def test_a_ticket_gives_the_file_once_to_its_address(kept):
    app = kept()
    client = TestClient(app, client=HOME)
    order = ticket(client)
    assert order.status_code == 200
    got = order.json()
    assert set(got) == {"url", "rows", "name"} and got["name"].startswith("verner_") and got["rows"] > 0
    assert got["url"].startswith("/api/export/file/") and len(got["url"]) > len("/api/export/file/") + 20
    stranger = TestClient(app, client=("203.0.113.9", 5000))
    assert stranger.get(got["url"]).status_code == 404  # another address cannot use it
    file = client.get(got["url"])
    assert file.status_code == 200 and file.headers["content-type"].startswith("text/csv")
    assert file.headers["content-disposition"] == f'attachment; filename="{got["name"]}"'
    assert len(file.text.splitlines()) == got["rows"] + 1
    assert file.text == client.post("/api/export", json=BODY).text  # the same file as the one-step export
    gone = client.get(got["url"])
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "not_found"  # once
    assert app.state.export_slots.free() == 2  # both streams gave their slot back


def test_a_ticket_lives_five_minutes(kept):
    app = kept()
    client = TestClient(app, client=HOME)
    url = ticket(client).json()["url"]
    tickets = app.state.export_tickets
    start = tickets.clock()
    tickets.clock = lambda: start + 301
    assert client.get(url).status_code == 404
    assert client.get("/api/export/file/" + "x" * 32).status_code == 404


def test_a_file_over_the_limit_is_413_with_its_figures(kept):
    client = TestClient(kept(max_export_rows=1), client=HOME)
    for res in (ticket(client), client.post("/api/export", json=BODY)):
        assert res.status_code == 413
        error = res.json()["error"]
        assert error["code"] == "payload_too_large" and error["limit"] == 1 and error["rows"] > 1
        assert error["more"] is True and "at least" in error["message"]  # the count stopped past the limit
    exact = ticket(TestClient(kept(), client=("203.0.113.5", 5000))).json()["rows"]
    assert error["rows"] < exact  # a lower bound: the count did not read the whole period


def test_an_address_orders_ten_an_hour_and_a_restart_does_not_forget(kept):
    client = TestClient(kept(export_per_hour=2), client=HOME)
    assert ticket(client).status_code == 200
    assert client.post("/api/export", json=BODY).status_code == 200  # the one-step export counts the same
    refused = ticket(client)
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "export_quota"
    assert 3500 < int(refused.headers["Retry-After"]) <= 3600
    assert client.post("/api/export", json=BODY).json()["error"]["code"] == "export_quota"
    again = TestClient(kept(export_per_hour=2), client=HOME)
    assert ticket(again).json()["error"]["code"] == "export_quota"
    other = TestClient(kept(export_per_hour=2), client=("203.0.113.9", 5000))
    assert ticket(other).status_code == 200
    assert other.post("/api/export/months", json=BODY).status_code == 200  # the months have no limits
    for _ in range(3):
        assert other.post("/api/export/months", json=BODY).status_code == 200


def test_the_server_gives_so_many_rows_a_day_and_a_restart_does_not_forget(kept):
    rows = ticket(TestClient(kept(), client=("203.0.113.1", 1))).json()["rows"]
    # the first order of this test spent `rows`; room for one more and a half
    cap = rows * 2 + rows // 2
    client = TestClient(kept(export_rows_per_day=cap), client=HOME)
    assert ticket(client).status_code == 200
    refused = ticket(client)
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "export_day_cap"
    assert 0 < int(refused.headers["Retry-After"]) <= 86_400
    assert ticket(TestClient(kept(export_rows_per_day=cap), client=HOME)).json()["error"]["code"] == "export_day_cap"
    assert ticket(TestClient(kept(export_rows_per_day=0), client=HOME)).status_code == 200  # 0: no cap


def test_busy_slots_refuse_the_ticket_at_once_and_the_file_after_its_wait(kept):
    app = kept()
    client = TestClient(app, client=HOME)
    url = ticket(client).json()["url"]
    app.state.export_slots = Slots(2, wait_s=0.1)
    held = [app.state.export_slots.take(), app.state.export_slots.take()]
    busy = ticket(client)
    assert busy.status_code == 429 and busy.json()["error"]["code"] == "export_busy" and busy.headers["Retry-After"]
    waited = client.get(url)
    assert waited.status_code == 429 and waited.json()["error"]["code"] == "export_busy"
    assert client.post("/api/export", json=BODY).json()["error"]["code"] == "export_busy"
    held[0]()
    held[0]()  # a release given twice frees one slot, not two
    assert app.state.export_slots.free() == 1
    assert client.get(url).status_code == 200  # the ticket waited for its turn


def test_a_client_that_goes_away_gives_the_slot_back():
    slots = Slots(2, wait_s=0.1)

    def rows():
        yield b"a,b\n"
        yield b"1,2\n"
        yield b"3,4\n"

    async def gone():
        return {"type": "http.disconnect"}

    async def broken(message):
        if message["type"] == "http.response.body":
            raise OSError("the client went away")

    async def silent(message):
        await asyncio.sleep(0)

    async def never():
        await asyncio.sleep(60)
        return {"type": "http.disconnect"}

    for receive, send in ((never, broken), (gone, silent)):
        release = slots.take()
        response = SlotResponse(rows(), release, media_type="text/csv")
        try:
            asyncio.run(response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send))
        except OSError:
            pass
        assert slots.free() == 2


def test_without_the_database_or_with_it_down_the_export_goes_on(store):
    alone = TestClient(app_with(store, database_url=None, export_per_hour=1), client=HOME)
    assert ticket(alone).status_code == 200
    assert ticket(alone).json()["error"]["code"] == "export_quota"  # counted in the process
    down = TestClient(app_with(store, database_url=DOWN, export_per_hour=1), client=HOME)
    assert ticket(down).status_code == 200
    assert ticket(down).status_code == 200  # a quota that cannot be read lets the request through, with a warning
    assert down.get(ticket(down).json()["url"]).status_code == 200


def test_a_daily_count_is_kept_in_the_database_and_holds_its_cap(database):
    url = database.render_as_string(hide_password=False)

    def today():
        return date(2026, 11, 15)

    first = DailyCounter("google_calls", Database(url), today)
    assert first.take(1, 2) and first.take(1, 2) and not first.take(1, 2)
    assert not DailyCounter("google_calls", Database(url), today).take(1, 2)  # after a restart
    assert DailyCounter("google_calls", Database(url), lambda: date(2026, 11, 16)).take(1, 2)  # the next day
    assert DailyCounter("export_rows", Database(url), today).take(5, 10)  # another name, its own count
    assert not DailyCounter("x", Database(url), today).take(11, 10)
    down = DailyCounter("google_calls", Database(DOWN), today)
    assert down.take(1, 1) and not down.take(1, 1)  # in the process while the database is down


def test_google_calls_outlive_a_restart(database, monkeypatch):
    url = database.render_as_string(hide_password=False)
    monkeypatch.setattr(access, "GOOGLE_PER_DAY", 2)
    first = access.Access(None, None, "key", today=lambda: "2026-11-15", db=Database(url))
    assert first._google_ok() and first._google_ok() and not first._google_ok()
    again = access.Access(None, None, "key", today=lambda: "2026-11-15", db=Database(url))
    assert not again._google_ok()
