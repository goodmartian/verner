import asyncio
import logging
import threading

from fastapi.testclient import TestClient
from test_reload import point, publish, served  # noqa: F401 - the fixture of a server that reloads its data

from senda_api import areas, calendar_routes, reload, summary
from senda_api.app import create_app
from senda_api.settings import Settings
from senda_api.store import Store


def month_of(store):
    last = store.cur_month - 1
    return f"{2000 + last // 12}-{last % 12 + 1:02d}"


def counting(monkeypatch, name):
    calls = []
    real = getattr(summary, name)

    def counted(*args, **kwargs):
        calls.append(args[1].id)
        return real(*args, **kwargs)

    monkeypatch.setattr(summary, name, counted)
    return calls


def own_app(store):
    return create_app(store=store, settings=Settings(anthropic_api_key=None), load_on_start=False)


def test_the_map_and_the_days_of_an_area_and_month_are_made_once(store, monkeypatch):
    maps, days = counting(monkeypatch, "cell_map"), counting(monkeypatch, "days")
    client = TestClient(own_app(store))
    month = month_of(store)
    for area in ("XA", areas.WORLD_ID):
        first = client.get("/api/calendar/map", params={"area": area, "month": month})
        again = client.get("/api/calendar/map", params={"area": area, "month": month})
        assert first.status_code == 200 and first.content == again.content
        assert first.headers["content-type"] == "application/json"
        assert first.json()["type"] == "FeatureCollection"
        assert client.get("/api/calendar/days", params={"area": area, "month": month}).json() == \
            client.get("/api/calendar/days", params={"area": area, "month": month}).json()
    assert maps == ["XA", areas.WORLD_ID] and days == ["XA", areas.WORLD_ID]
    # an answer that fails is not kept: the next ask tries again
    assert client.get("/api/calendar/map", params={"area": "XA", "month": "1990-01"}).status_code == 422
    assert client.get("/api/calendar/map", params={"area": "XA", "month": "1990-01"}).status_code == 422
    assert maps.count("XA") == 3


def test_a_new_data_version_makes_them_again(store, data_dir, monkeypatch):
    maps = counting(monkeypatch, "cell_map")
    app = own_app(store)
    client = TestClient(app)
    month = month_of(store)
    client.get("/api/calendar/map", params={"area": "XA", "month": month})
    made = len(maps)  # 0 or 1: the session's store may hold it from an earlier test
    client.get("/api/calendar/map", params={"area": "XA", "month": month})
    assert len(maps) == made
    app.state.store = Store.load(data_dir)  # what reload does when a new version is ready
    client.get("/api/calendar/map", params={"area": "XA", "month": month})
    assert len(maps) == made + 1


def test_the_start_warms_the_world_in_the_background(store, monkeypatch):
    warmed = threading.Event()
    seen = []

    def fake(got):
        seen.append(got)
        warmed.set()

    monkeypatch.setattr(calendar_routes, "warm", fake)
    app = own_app(store)
    with TestClient(app):
        assert warmed.wait(5) and seen == [store]


def test_a_new_data_version_is_warmed(served, data_dir, monkeypatch):  # noqa: F811 - the fixture imported above
    _client, app, root = served
    seen = []
    monkeypatch.setattr(calendar_routes, "warm_later", seen.append)
    publish(root, data_dir, "B")
    point(root, "B")
    assert asyncio.run(reload.check(app)) is True
    assert [s.version for s in seen] == ["B"]


def test_a_warm_up_that_fails_is_a_line_in_the_log(store, monkeypatch, caplog):
    def broken(_):
        raise RuntimeError("no world today")

    monkeypatch.setattr(calendar_routes, "world_of", broken)
    maps = counting(monkeypatch, "cell_map")
    with caplog.at_level(logging.WARNING, logger=calendar_routes.log.name):
        calendar_routes.warm(store)  # does not raise
    assert any("countries" in r.message and "no world today" in r.message for r in caplog.records)
    assert maps == [areas.WORLD_ID]  # the other steps went on
    client = TestClient(own_app(store))
    current = f"{2000 + store.cur_month // 12}-{store.cur_month % 12 + 1:02d}"
    client.get("/api/calendar/map", params={"area": areas.WORLD_ID, "month": current})
    assert maps == [areas.WORLD_ID]  # the warmed map is the one the visitor gets
