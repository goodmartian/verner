import asyncio
import gc
import json
import logging
import shutil
import weakref

import pytest
from fastapi.testclient import TestClient

from senda_api import areas, calendar, reload
from senda_api.app import create_app
from senda_api.settings import Settings


def publish(root, data_dir, name, ready=True):
    """A copy of the test version in versions/<name> with its own version string."""
    folder = root / "versions" / name
    shutil.copytree(data_dir, folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["version"] = name
    (folder / "manifest.json").write_text(json.dumps(manifest))
    if ready:
        (folder / reload.READY).touch()
    return folder


def point(root, name):
    link = root / ".current.tmp"
    link.unlink(missing_ok=True)
    link.symlink_to(root / "versions" / name)
    link.replace(root / "current")


@pytest.fixture
def served(data_dir, tmp_path):
    publish(tmp_path, data_dir, "A")
    point(tmp_path, "A")
    app = create_app(settings=Settings(data_dir=tmp_path / "current", reload_every_s=3600, anthropic_api_key=None))
    with TestClient(app) as client:
        yield client, app, tmp_path


def version(client):
    return client.get("/api/meta").json()["data_version"]


def test_a_new_ready_version_replaces_the_store(served, data_dir):
    client, app, root = served
    assert version(client) == "A"
    first = client.get("/api/meta")
    publish(root, data_dir, "B")
    point(root, "B")
    assert asyncio.run(reload.check(app)) is True
    assert app.state.store.version == "B" and version(client) == "B"
    assert client.get("/api/meta", headers={"If-None-Match": first.headers["etag"]}).status_code == 200  # a new body, not a 304
    assert asyncio.run(reload.check(app)) is False  # nothing new now


def test_a_version_without_ready_is_waited_for(served, data_dir):
    client, app, root = served
    publish(root, data_dir, "B", ready=False)
    point(root, "B")
    assert asyncio.run(reload.check(app)) is False and version(client) == "A"
    (root / "versions" / "B" / reload.READY).touch()
    assert asyncio.run(reload.check(app)) is True and version(client) == "B"


def test_a_failed_load_keeps_the_old_store_and_says_so_once(served, data_dir, caplog):
    client, app, root = served
    folder = publish(root, data_dir, "B")
    (folder / "cells.parquet").write_bytes(b"not a parquet file")
    point(root, "B")
    with caplog.at_level(logging.WARNING, logger=reload.log.name):
        assert asyncio.run(reload.check(app)) is False
        assert asyncio.run(reload.check(app)) is False
    assert version(client) == "A"
    assert len([r for r in caplog.records if "not loaded" in r.message]) == 1
    shutil.copyfile(data_dir / "cells.parquet", folder / "cells.parquet")  # the files are complete on a later tick
    assert asyncio.run(reload.check(app)) is True and version(client) == "B"


def test_the_old_version_is_freed_with_its_caches(served, data_dir):
    _client, app, root = served
    old = app.state.store
    calendar.series_of(old, areas.parse({"id": "XA"}, old))  # a cache that refers back to its store
    gone = weakref.ref(old)
    del old
    publish(root, data_dir, "B")
    point(root, "B")
    assert asyncio.run(reload.check(app)) is True
    gc.collect()
    assert gone() is None


@pytest.mark.parametrize(("every", "started"), [(0, False), (60, True)])
def test_the_watcher_runs_only_when_switched_on(data_dir, tmp_path, monkeypatch, every, started):
    publish(tmp_path, data_dir, "A")
    point(tmp_path, "A")
    calls = []

    async def fake(app, seconds):
        calls.append(seconds)

    monkeypatch.setattr(reload, "watch", fake)
    app = create_app(settings=Settings(data_dir=tmp_path / "current", reload_every_s=every, anthropic_api_key=None))
    with TestClient(app):
        pass
    assert bool(calls) is started
