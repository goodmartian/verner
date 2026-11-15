"""Postgres of the chats and the saved plans, through a plain SQLAlchemy engine (the routes are sync).

The database may be down: `session()` then raises 503 `storage_unavailable` and the rest of the site goes on.
Migrations are applied by `make migrate`, never by the server; `revision_state()` says whether they were.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .errors import ApiError

log = logging.getLogger("senda.db")
ROOT = Path(__file__).resolve().parents[1]
POOL_SIZE = 5


def unavailable() -> ApiError:
    return ApiError(503, "storage_unavailable", "Chats and plans are not available now")


class Database:
    def __init__(self, url: str | None) -> None:
        self.url = url
        self._engine: Engine | None = None
        self._sessions: sessionmaker[Session] | None = None

    @property
    def engine(self) -> Engine:
        if self.url is None:
            raise unavailable()
        if self._engine is None:
            self._engine = create_engine(self.url, pool_size=POOL_SIZE, pool_pre_ping=True,
                                         connect_args={"connect_timeout": 3})
            self._sessions = sessionmaker(self._engine, expire_on_commit=False)
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        """One short transaction: committed when the block ends, rolled back when it fails."""
        try:
            self.engine  # noqa: B018 (creates the engine, or says there is none)
            assert self._sessions is not None
            with self._sessions() as session:
                try:
                    yield session
                    session.commit()
                except BaseException:
                    session.rollback()
                    raise
        except (OperationalError, InterfaceError) as error:
            log.warning("database unavailable: %s", error.__class__.__name__)
            raise unavailable() from error
        except DBAPIError as error:
            if error.connection_invalidated:
                raise unavailable() from error
            raise

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except (OperationalError, InterfaceError, ApiError):
            return False

    def revision_state(self) -> str:
        """`ok` when the alembic revision is the head of the migrations, `outdated` when it is not, `unknown` when
        the database or the migrations cannot be read."""
        try:
            head = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
            with self.engine.connect() as conn:
                current = MigrationContext.configure(conn).get_current_revision()
        except (SQLAlchemyError, ApiError, CommandError, OSError):
            return "unknown"
        return "ok" if current == head else "outdated"

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
