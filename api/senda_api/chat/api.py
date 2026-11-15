"""`/api/chats*`: chats kept in Postgres (`chat.store`), answers streamed in the event protocol of the web app.

The questions go through the tool loop (`chat.loop`), with its number check. Its events are
translated: `tool` to `step` (and a `widget` for the calendar and region tools), `token` to `text`, `done` and
`error` keep their names. Without a model key the answer is 503 `unavailable`.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from .. import calendar, regions
from ..client import carry, client_of, uuid_of
from ..climate_routes import climate_or_none
from ..contracts import EVENT_STREAM, FILE_RESPONSE, ChatDetail, ChatSummary, ok
from ..errors import ApiError
from ..fires_routes import access_of, land_of
from ..regions import region_item, types_of
from ..weather_routes import weather_of
from . import loop, store
from .guard import address_of
from .routes import _OneAtATime, frame
from .spend import Metered
from .tools import resolve_area

log = logging.getLogger("senda.chat")
router = APIRouter(prefix="/api/chats", tags=["api"])

CHAT_ID = r"^(new|[0-9a-fA-F-]{36})$"
STEPS = {"find_region": "list_regions", "get_calendar": "area_calendar", "get_window": "period_stats",
         "get_month_weather": "month_weather",
         "check_event": "month_detail", "list_fires": "live_fires", "get_fire": "fire_detail",
         "prepare_file": "prepare_file", "write_report": "prepare_file", "make_plan": "build_plan",
         "open_plan": "build_plan", "draw_on_map": "draw_on_map"}
KNOWN_ERRORS = {"unauthorized", "forbidden", "not_found", "conflict", "chat_busy", "payload_too_large",
                "validation_error", "rate_limited", "internal_error", "upstream_error", "unavailable", "interrupted"}
TITLE_CHARS = 60
MAX_CORNERS = 400
DRAWN_ID = r"^[A-Za-z0-9_-]{1,16}$"
MAX_FACT_CHARS = 300
GATE = _OneAtATime()


MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
# what the page sends as an id is an id, not prose: these go to the model as they are, so they are kept short and plain
CATALOG_ID = r"^[A-Za-z0-9_.:-]{1,64}$"
TAB = r"^[A-Za-z0-9_-]{1,32}$"
MAX_FACT_LENGTH = 1000  # what the request may carry; the model and the judge read the first MAX_FACT_CHARS of it


class DrawnAreaIn(BaseModel):
    """An area the person drew on the map: its name there and its corners."""

    id: str = Field(pattern=DRAWN_ID, description="Its name on the map: U1, U2, ...")
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=MAX_CORNERS, description="Corners, [longitude, latitude].")
    role: Literal["area", "safe_zone"] = "area"


class ChatBoard(BaseModel):
    """What the person has on the screen. The server tells the model; the chat keeps only the person's text."""

    tab: str | None = Field(default=None, pattern=TAB, description="The open tab: calendar, fires, ...")
    area: str | None = Field(default=None, pattern=CATALOG_ID, description="Id of the area on the board.")
    area_name: str | None = Field(default=None, max_length=120, description="Its name in the language of the page.")
    first_month: str | None = Field(default=None, pattern=MONTH)
    last_month: str | None = Field(default=None, pattern=MONTH)
    month: str | None = Field(default=None, pattern=MONTH, description="The month the person selected.")
    fire_id: str | None = Field(default=None, pattern=CATALOG_ID, description="The open fire.")
    facts: list[Annotated[str, Field(max_length=MAX_FACT_LENGTH)]] = Field(default_factory=list, max_length=10, description=(
        "Figures of the board the person added to the question, each as `label: value (area, period)`; the model "
        "reads them as the person's own numbers."))
    areas: list[DrawnAreaIn] = Field(default_factory=list, max_length=10, description=(
        "The areas drawn on the map. The model is told their names; their corners stay with the server and the "
        "tools read them by name."))
    drawn_area: str | None = Field(default=None, pattern=DRAWN_ID, description=(
        "The name of the drawn area the calendar shows, when it shows one."))


class MonthAttachment(BaseModel):
    """A month of the calendar the person attached to the question."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["month"]
    area: str = Field(pattern=CATALOG_ID)
    month: str = Field(pattern=MONTH)


class AreaAttachment(BaseModel):
    """An area drawn on the map that the person attached to the question."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["area"]
    id: str = Field(pattern=DRAWN_ID)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=MAX_CORNERS)
    role: Literal["area", "safe_zone"] = "area"


Attachment = Annotated[MonthAttachment | AreaAttachment, Field(discriminator="kind")]


class ChatQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    board: ChatBoard | None = None
    # typed: what the page attaches goes into the text for the model, so nothing else may ride along (422)
    attachments: list[Attachment] = Field(default_factory=list, max_length=10)


_TAIL = re.compile(r"\s*\[tab:.*$", re.DOTALL)


def plain(text: str) -> str:
    """The person's own words: a board line appended to the question is cut off."""
    return _TAIL.sub("", text)


def _chat_id(text: str) -> uuid.UUID:
    found = uuid_of(text)
    if found is None:
        raise ApiError(404, "not_found", "No such chat")
    return found


def _summary(chat: dict) -> dict:
    return {**{k: chat[k] for k in ("id", "created_at", "updated_at")}, "title": plain(chat["title"])}


@router.get("", responses=ok(list[ChatSummary]))
def list_chats(request: Request, response: Response):
    client = client_of(request, response)
    return [_summary(c) for c in store.list_chats(request.app.state.db, client)]


@router.get("/{chat_id}", responses=ok(ChatDetail))
def get_chat(request: Request, response: Response, chat_id: Annotated[str, Path(pattern=CHAT_ID)]):
    chat = store.get_chat(request.app.state.db, client_of(request, response), _chat_id(chat_id))
    if chat is None:
        raise ApiError(404, "not_found", "No such chat")
    return {**_summary(chat), "messages": [{**m, "text": plain(m["text"])} for m in chat["messages"]]}


@router.get("/{chat_id}/files/{file_id}", response_class=Response, responses=FILE_RESPONSE)
def get_file(request: Request, response: Response, chat_id: Annotated[str, Path(pattern=CHAT_ID)],
             file_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]):
    found = store.get_file(request.app.state.db, client_of(request, response), _chat_id(chat_id), uuid.UUID(file_id))
    if found is None:
        raise ApiError(404, "not_found", "No such file")
    return Response(found["data"], media_type=found["mime"],
                    headers={"Content-Disposition": f'attachment; filename="{found["name"]}"', "X-Content-Type-Options": "nosniff"})


@router.delete("/{chat_id}", status_code=204)
def delete_chat(request: Request, response: Response, chat_id: Annotated[str, Path(pattern=CHAT_ID)]):
    if not store.delete_chat(request.app.state.db, client_of(request, response), _chat_id(chat_id)):
        raise ApiError(404, "not_found", "No such chat")
    return carry(response, Response(status_code=204))


def language_of(request: Request, text: str) -> str:
    """Language of the refusal text: Cyrillic in the question means Russian, else the first language of the browser."""
    if re.search("[а-яё]", text, re.IGNORECASE):
        return "ru"
    first = request.headers.get("accept-language", "en").split(",")[0].strip().lower()[:2]
    return first if first in loop.UNVERIFIED else "en"


def _ring(raw: Any) -> list[list[float]] | None:
    """Corners as a closed ring of [longitude, latitude], or None when they are not corners."""
    if not isinstance(raw, list) or not 3 <= len(raw) <= MAX_CORNERS:
        return None
    ring = []
    for point in raw:
        if not (isinstance(point, (list, tuple)) and len(point) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in point)):
            return None
        ring.append([float(point[0]), float(point[1])])
    return ring if ring[0] == ring[-1] else [*ring, ring[0]]


def drawn_areas(board: ChatBoard | None, attachments: list[dict]) -> dict[str, dict]:
    """What the person drew, by name: the areas of the board, then those attached to the question."""
    found: dict[str, dict] = {}
    for area in board.areas if board else []:
        ring = _ring([list(p) for p in area.polygon])
        if ring:
            found[area.id] = {"type": "Polygon", "coordinates": [ring]}
    for item in attachments:
        name, ring = item.get("id"), _ring(item.get("polygon"))
        if item.get("kind") == "area" and isinstance(name, str) and re.match(DRAWN_ID, name) and ring:
            found[name] = {"type": "Polygon", "coordinates": [ring]}
    return found


def context_line(board: ChatBoard | None, attachments: list[dict]) -> str:
    """What the person has on the board and attached, as plain words for the model."""
    parts = []
    drawn = drawn_areas(board, attachments)
    if board:
        if board.tab:
            parts.append(f"tab {board.tab}")
        first, last = board.first_month, board.last_month
        months = f", months {first} to {last}" if first and last else ""
        if board.area:
            name = f" ({board.area_name})" if board.area_name else ""
            parts.append(f"area {board.area}{name}{months}")
        elif board.drawn_area in drawn:
            parts.append(f"the calendar shows drawn area {board.drawn_area}{months}")
        if board.areas:
            safe = {a.id for a in board.areas if a.role == "safe_zone"}
            names = ", ".join(f"{a.id} (safe zone)" if a.id in safe else a.id for a in board.areas if a.id in drawn)
            parts.append(f"areas drawn on the map: {names}")
        if board.month:
            parts.append(f"selected month {board.month}")
        if board.fire_id:
            parts.append(f"fire {board.fire_id} is open")
        parts += [f"figure {fact[:MAX_FACT_CHARS]}" for fact in board.facts]
    for item in attachments:
        if item.get("kind") == "month":
            parts.append(f"attached month {item.get('month')} in area {item.get('area')}")
        elif item.get("kind") == "area" and item.get("id") in drawn:
            parts.append(f"attached drawn area {item.get('id')}")
    if drawn:
        parts.append('a tool reads a drawn area when its area is {"drawn": "<name>"}')
        # the person drew or attached it to ask about it: a question that names no place is about that area
        asked = [str(item.get("id")) for item in attachments if item.get("kind") == "area" and item.get("id") in drawn]
        plain_areas = [a.id for a in board.areas if a.id in drawn and a.role == "area"] if board else []
        about = asked[-1] if asked else board.drawn_area if board and board.drawn_area in drawn else (
            plain_areas[-1] if plain_areas else None)
        if about:
            parts.append(f"a question that names no place is about drawn area {about}, not about the area of the board")
    return f"\n\n[On the board: {'; '.join(parts)}]" if parts else ""


def widget_for(request: Request, name: str, args: dict, drawn: dict[str, dict] | None = None) -> dict | None:
    store = request.app.state.get_store(request)
    try:
        if name == "get_calendar":
            area = resolve_area(args["area"], store, drawn)
            return {"type": "area_calendar", "data": calendar.build(store, area, args.get("from"), args.get("to"))}
        if name == "find_region":
            items = []
            for found in regions.find(store, str(args.get("query", "")), int(args.get("limit", 10))):
                region = store.regions.by_id.get(found["id"])
                if region is not None:
                    full = region_item(store, region)
                    items.append({"id": full["id"], "country_id": full["country_id"], "kind": full["kind"],
                                  "names": full["names"], "type": full["type"], "covered": True})
            return {"type": "region_list",
                    "data": {"regions": items, "types": types_of(i["type"] for i in items)}} if items else None
    except (ApiError, KeyError, ValueError):
        return None
    return None


def translate(request: Request, events: Iterator[tuple[str, dict]], saved: dict,
              drawn: dict[str, dict] | None = None) -> Iterator[tuple[str, dict]]:
    """Events of the web app from the events of the loop. `saved` collects what the stored answer needs.

    A list of fires waits for the end of the answer: when the answer also shows one fire or a plan, the list was only
    the way to find that fire and is not shown."""
    spoke = False
    held: list[dict] = []  # fire_list cards, sent before `done` unless a fire or a plan card was sent
    sent: set[str] = set()
    for event, data in events:
        if event == "tool" and data["status"] == "running":
            yield "step", {"tool": STEPS.get(data["name"], "period_stats")}
        elif event == "tool" and data["status"] == "ok":
            if "action" in data:
                saved["actions"].append(data["action"])
                yield "action", data["action"]
            widget = data.get("widget") or ({"type": "file", "data": data["file"]} if "file" in data
                                            else widget_for(request, data["name"], data.get("args", {}), drawn))
            if widget is not None and widget["type"] == "fire_list":
                held.append(widget)
            elif widget is not None:
                sent.add(widget["type"])
                saved["widgets"].append(widget)
                yield "widget", widget
        elif event == "token":
            spoke = True
            saved["text"] += data["text"]
            yield "text", {"text": data["text"]}
        elif event == "done":
            saved["memory"] = data.get("memory", {})
            if not spoke and data.get("text"):
                saved["text"] = data["text"]
                yield "text", {"text": data["text"]}
            if not sent & {"fire_detail", "work_plan"}:
                for widget in held:
                    saved["widgets"].append(widget)
                    yield "widget", widget
            yield "done", {}
        elif event == "error":
            code = data["code"] if data["code"] in KNOWN_ERRORS else "upstream_error"
            yield "error", {"code": code, "message": data["message"]}


@router.post("/{chat_id}/messages", response_class=StreamingResponse, responses=EVENT_STREAM)
def ask(request: Request, response: Response, chat_id: Annotated[str, Path(pattern=CHAT_ID)], question: ChatQuestion):
    app = request.app
    model, settings, db = app.state.chat_model, app.state.settings, app.state.db
    if model is None:
        raise ApiError(503, "unavailable", "The chat is not available")
    who = address_of(request)  # one key for the gate, the quota and the bans: an IPv6 /64 is one person
    guard = app.state.chat_guard
    guard.check(who)  # a banned address, or one over its quota, is refused before any model call
    spend = app.state.chat_spend
    if spend.reached():  # before any model call; the board and the map do not depend on it
        raise ApiError(429, "rate_limited", "The chat has answered all it can today")
    model = Metered(model, spend)
    if len(question.text) > settings.chat_max_message_chars:
        raise ApiError(413, "payload_too_large", f"The question is longer than {settings.chat_max_message_chars} characters")
    client = client_of(request, response)
    new = chat_id == "new"
    existing = None if new else _chat_id(chat_id)
    token = GATE.acquire(who)
    if token is None:
        raise ApiError(409, "chat_busy", "The last question is still being answered")
    try:
        earlier = [] if existing is None else store.history(db, existing, settings.chat_max_history - 1)
        if earlier and earlier[0]["role"] != "user":
            earlier = earlier[1:]
        # The question and an empty answer are in the chat from the start and the answer grows in it (`save` after
        # each event), so a reader that goes away leaves them as far as they went.
        # the corners of drawn areas are not kept with the chat: the next question brings what is on the map then
        board = question.board.model_dump(exclude_none=True, exclude={"areas"}) if question.board else None
        begun = store.begin(db, client, existing, plain(question.text).strip()[:TITLE_CHARS], plain(question.text), board)
        if begun is None:
            raise ApiError(404, "not_found", "No such chat")
    except BaseException:
        GATE.release(who, token)
        raise
    cid, seq = begun
    attachments = [item.model_dump() for item in question.attachments]
    on_board = context_line(question.board, attachments)
    # only an accepted question counts toward the quota; the judge reads the question before it, for follow-ups
    previous = next((plain(m["text"]) for m in reversed(earlier) if m["role"] == "user"), None)
    guard.accept(who, plain(question.text), previous, on_board.strip())
    messages = [*earlier, {"role": "user", "text": question.text + on_board}]
    saved: dict[str, Any] = {"text": "", "widgets": [], "actions": [], "memory": {}}
    store_data = app.state.get_store(request)
    drawn = drawn_areas(question.board, attachments)

    def save() -> None:
        try:
            store.save_answer(db, cid, seq, saved)
        except ApiError:
            log.warning("chat %s: the answer could not be saved", cid)

    def drop() -> None:
        """A failed answer is not kept, nor are its files."""
        try:
            store.drop(db, cid, seq, new)
        except ApiError:
            log.warning("chat %s: the failed answer could not be removed", cid)

    def stream() -> Iterator[bytes]:
        try:
            yield frame("start", {"chat_id": str(cid)})
            run = loop.run(model, store_data, settings, messages, lambda: weather_of(request),
                           language_of(request, question.text), store.Files(db, cid, seq), lambda: land_of(request),
                           lambda: access_of(request), store.shapes_drawn(db, cid), store.memory(db, cid), drawn,
                           lambda: climate_or_none(request))
            for event, data in translate(request, run, saved, drawn):
                if event in ("text", "widget", "action", "done"):
                    save()
                if event == "done":
                    data = {"chat_id": str(cid)}
                elif event == "error":
                    drop()
                yield frame(event, data)
        finally:
            GATE.release(who, token)

    return carry(response, StreamingResponse(stream(), media_type="text/event-stream",
                                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                                             background=BackgroundTask(GATE.release, who, token)))
