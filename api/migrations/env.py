"""Alembic over the sync engine. The URL is `sqlalchemy.url` of the config (tests) or `DATABASE_URL`."""

import os

from alembic import context
from sqlalchemy import create_engine

from senda_api.models import Base

config = context.config
url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is not set (see .env.example)")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
