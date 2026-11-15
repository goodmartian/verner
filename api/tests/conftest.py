import os
from pathlib import Path

import fixture
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from senda_api.app import create_app
from senda_api.store import Store


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("senda") / "v1"
    fixture.build(root)
    return root


@pytest.fixture(scope="session")
def store(data_dir):
    return Store.load(data_dir)


@pytest.fixture(scope="session")
def client(store):
    return TestClient(create_app(store=store))


@pytest.fixture(scope="session")
def ids():
    return {"a": fixture.CELL_A, "b": fixture.CELL_B, "never": fixture.CELL_NEVER}


@pytest.fixture(autouse=True)
def _no_land_cover_network(monkeypatch):
    """No test reaches AWS: a reader without a stub fetcher finds no network."""
    from senda_api import landcover

    def refuse(self, url, start, length):
        raise landcover.FetchError("the network is off in tests")

    monkeypatch.setattr(landcover.HttpFetcher, "get_range", refuse)

    from senda_api import access

    def no_route(self, *args, **kwargs):
        raise access.AccessError("the network is off in tests")

    for method in ("get_json", "post_form", "post_json"):
        monkeypatch.setattr(access.HttpClient, method, no_route)


# Postgres of the chats and plans. The server is the one of the working database (`DATABASE_URL`, or the line in
# ../.env); the tests use a database of their own, `<name>_test_<pid>`, made for the run and dropped at its end (so two runs at once do not meet). The working one is never touched.
def _working_url() -> str | None:
    found = os.environ.get("DATABASE_URL")
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not found and env_file.exists():
        line = next((x for x in env_file.read_text().splitlines() if x.startswith("DATABASE_URL=")), "")
        found = line.partition("=")[2].strip() or None
    return found


_WORKING = _working_url()
_TEST = make_url(_WORKING).set(database=f"{make_url(_WORKING).database}_test_{os.getpid()}") if _WORKING else None
if _TEST is not None:
    os.environ["DATABASE_URL"] = _TEST.render_as_string(hide_password=False)  # what `Settings()` reads in tests
else:
    os.environ.pop("DATABASE_URL", None)

TABLES = ("plans, chat_files, messages, chats, chat_guard_questions, chat_guard_points, chat_guard_bans, chat_spend, "
          "chat_guard_keys, daily_counts")


@pytest.fixture(scope="session")
def database_url():
    if _TEST is None:
        pytest.skip("no DATABASE_URL: set it in .env and start Postgres (docker compose up -d)")
    assert "_test_" in _TEST.database
    admin = create_engine(_TEST.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{_TEST.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{_TEST.database}"'))
    except OperationalError:
        pytest.skip("Postgres is not running: docker compose up -d")
    finally:
        admin.dispose()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", _TEST.render_as_string(hide_password=False).replace("%", "%%"))
    command.upgrade(config, "head")
    yield _TEST
    admin = create_engine(_TEST.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_TEST.database}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def database(database_url):
    """The test database with empty tables; tests that keep chats or plans use it (and are skipped without Postgres)."""
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield database_url
    engine.dispose()
