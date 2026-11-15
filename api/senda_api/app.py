"""FastAPI application. Routes are thin: they parse the request and call the pure functions of the other modules."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import TypeAdapter

from . import (
    areas,
    base,
    calendar,
    calendar_routes,
    climate_routes,
    errors,
    export_routes,
    fires_routes,
    meta,
    plans_routes,
    reload,
    schemas,
    weather_routes,
)
from .chat import api as chat_api
from .chat import routes as chat_routes
from .chat.guard import Guard
from .chat.llm import Model
from .chat.spend import DailySpend
from .contracts import AreaPeriodRequest, ChatEvent, ErrorResponse
from .db import Database
from .errors import ApiError, SafeJSONResponse
from .http_cache import Caching, Compression
from .limits import DailyCounter, Slots, Tickets
from .settings import Settings
from .store import Store

log = logging.getLogger("senda")

ERRORS = {400: "Bad request", 404: "Not found", 409: "Conflict", 413: "Too large", 422: "Validation error",
          500: "Internal error", 503: "Data not loaded"}


def with_chat_events(app: FastAPI, schema: dict) -> dict:
    """The answer stream of a chat is a list of typed events; FastAPI cannot say that for text/event-stream."""
    if "StepEvent" not in schema["components"]["schemas"]:
        events = TypeAdapter(ChatEvent).json_schema(ref_template="#/components/schemas/{model}", mode="serialization")
        schema["components"]["schemas"].update(events.pop("$defs"))
        post = schema["paths"]["/api/chats/{chat_id}/messages"]["post"]
        post["responses"]["200"]["content"]["text/event-stream"]["schema"] = events
        app.openapi_schema = schema
    return schema


def create_app(store: Store | None = None, settings: Settings | None = None, load_on_start: bool = True,
               chat_model: Model | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        watcher = None
        if app.state.store is None and load_on_start:
            app.state.store = Store.load(settings.data_dir)
            if settings.reload_every_s > 0:
                watcher = asyncio.create_task(reload.watch(app, settings.reload_every_s))
        if app.state.store is not None:
            calendar_routes.warm_later(app.state.store)  # in the background: the start does not wait for it
        state = app.state.db.revision_state()
        if state != "ok":  # the site works without it; chats and plans answer 503
            log.warning("database: %s. Chats and plans need Postgres: `make db-up`, then `make migrate`.", state)
        yield
        if watcher is not None:
            watcher.cancel()
        app.state.db.dispose()

    app = FastAPI(
        title="Verner API",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        default_response_class=SafeJSONResponse,
        responses={code: {"model": ErrorResponse, "description": text} for code, text in ERRORS.items()},
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    errors.install(app)

    def get_store(request: Request) -> Store:
        found = request.app.state.store
        if found is None:
            raise ApiError(503, "unavailable", "Data is not loaded")
        return found

    @app.get("/api/meta", response_model=schemas.Meta)
    def get_meta(request: Request):
        return meta.meta(get_store(request), chat_enabled=request.app.state.chat_model is not None)

    @app.post("/api/calendar", response_model=schemas.Calendar)
    def post_calendar(body: AreaPeriodRequest, request: Request):
        data = get_store(request)
        return calendar.build(data, areas.parse(body.area.as_dict(), data), body.from_, body.to)

    app.state.get_store = get_store
    app.add_middleware(Caching)  # added first: it hashes the body before it is compressed
    app.add_middleware(Compression)
    app.state.chat_model = chat_routes.resolve_model(settings, chat_model)
    # both kept in Postgres when there is one, so a restart forgets no dollar and no ban; else in the process
    kept = app.state.db if settings.database_url else None
    app.state.chat_spend = DailySpend(settings.chat_daily_usd, db=kept)
    app.state.chat_guard = Guard.from_settings(settings, app.state.chat_spend, live=chat_model is None, db=kept)
    # the hotspot export: rows of the server's day (kept like the spend), streams at once, one-time links
    app.state.export_rows = DailyCounter("export_rows", kept)
    app.state.export_slots = Slots(settings.export_slots, settings.export_wait_s)
    app.state.export_tickets = Tickets()
    for module in (base, calendar_routes, export_routes, fires_routes, plans_routes, chat_api, weather_routes, climate_routes):
        app.include_router(module.router)
    app.openapi = lambda: with_chat_events(app, FastAPI.openapi(app))
    return app


app = create_app()
