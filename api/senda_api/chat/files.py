"""Files the chat prepares for the person: a CSV of data the screens show, or a Markdown report.

The numbers come from the same functions as the screens (`calendar.build`, `summary.days`, `fire_tools.list_fires`).
A file is kept in the chat it was made in (`chat["files"]`) and goes away with it.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .. import areas, calendar, fires, summary
from ..months import month_label
from ..store import Store
from ..weather import Weather
from . import fire_tools

MAX_BYTES = 1_000_000
MAX_PER_ANSWER = 3
MAX_PER_CHAT = 30
SAMPLE_ROWS = 5
CSV_MIME = "text/csv; charset=utf-8"
MD_MIME = "text/markdown; charset=utf-8"
MONTH_COLUMNS = ("month", "count", "median", "ratio", "level", "partial")
DAY_COLUMNS = ("date", "clusters", "detections")
FIRE_COLUMNS = ("id", "area_ha", "detection_count", "first_detection_at", "last_detection_at", "nearest_place",
                "distance_km", "direction", "area_change_last_pass_ha", "area_change_last_pass_pct",
                "hours_between_last_passes", "front_speed_m_per_h", "wind_speed_kmh", "wind_from_deg",
                "temperature_c", "humidity_pct", "wind_at")


PREPARE_FILE = {
    "name": "prepare_file",
    "description": "Prepare a CSV file for the person to download, from the same numbers the screens show. kind=monthly: "
                   "the monthly series of an area (area, from, to as in get_calendar). kind=days: the days of one month "
                   "(area, month YYYY-MM). kind=fires: the live fires of a region (region id, or WORLD). Returns the file's "
                   "name, rows, columns, the first rows and totals. The person sees a card under the answer that says "
                   "what the file is and how much is in it, with a button to save it, so the text says in a sentence or "
                   "two what the file holds and for which area and period, from this result alone; it does not read the "
                   "file out and does not need another tool. A table is never pasted into the answer. At most 3 files "
                   "per answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["monthly", "days", "fires"]},
            "area": {"type": "object", "description": "Area as in get_calendar; for monthly and days. Default: the whole world."},
            "region": {"type": "string", "description": "Region id from find_region or WORLD; for fires."},
            "from": {"type": "string", "description": "First month YYYY-MM; for monthly."},
            "to": {"type": "string", "description": "Last month YYYY-MM; for monthly."},
            "month": {"type": "string", "description": "The month YYYY-MM; for days."},
        },
        "required": ["kind"], "additionalProperties": False,
    },
}

WRITE_REPORT = {
    "name": "write_report",
    "description": "Save a short report as a Markdown file for the person to download. Pass a title and the report text; "
                   "the text goes through the same number check as an answer, so use only numbers from tool results. "
                   "The server adds the source, the data version and the date. Use it when the person asks for a report. area, from and to "
                   "(as in get_calendar) name the file: the area and period the report is about. The person sees a "
                   "card with a button to save the report, so the answer gives its main point in two or three "
                   "sentences and does not repeat the report.",
    "input_schema": {
        "type": "object",
        "properties": {"title": {"type": "string"}, "text": {"type": "string", "description": "Markdown."},
                       "area": {"type": "object", "description": "Area of the report, as in get_calendar."},
                       "from": {"type": "string", "description": "First month YYYY-MM."},
                       "to": {"type": "string", "description": "Last month YYYY-MM."}},
        "required": ["title", "text"], "additionalProperties": False,
    },
}


class FileError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def safe(text: str, default: str = "file") -> str:
    """A part of a file name: ASCII letters, digits, dot, dash and underscore only."""
    return re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-._")[:40] or default


def _cell(value: Any) -> Any:
    """Empty for none, lower-case true and false as JSON writes them."""
    return "" if value is None else str(value).lower() if isinstance(value, bool) else value


def _csv(columns: tuple[str, ...], rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(columns)
    writer.writerows([[_cell(r.get(c)) for c in columns] for r in rows])
    return out.getvalue()


def _fire_row(f: dict) -> dict:
    place, wind = f["nearest_place"] or {}, f["wind"] or {}
    return {**f, "nearest_place": place.get("name"), "distance_km": place.get("distance_km"),
            "direction": place.get("direction"), "wind_speed_kmh": wind.get("speed_kmh"),
            "wind_from_deg": wind.get("from_deg"), "temperature_c": wind.get("temperature_c"),
            "humidity_pct": wind.get("humidity_pct"), "wind_at": wind.get("at")}


def monthly(store: Store, area: areas.Area, first: int, last: int) -> tuple[str, str, list[dict], dict]:
    cal = calendar.build(store, area, month_label(first), month_label(last))
    rows = [e for e in cal["series"] if e["count"] is not None]
    name = f"verner_{area.slug}_{month_label(first)}_{month_label(last)}_months.csv"
    return name, _csv(MONTH_COLUMNS, rows), rows, {"detections_total": sum(e["count"] for e in rows)}


def days(store: Store, area: areas.Area, month: str) -> tuple[str, str, list[dict], dict]:
    rows = summary.days(store, area, month)["days"]
    return (f"verner_{area.slug}_{month}_days.csv", _csv(DAY_COLUMNS, rows), rows,
            {"detections_total": sum(r["detections"] for r in rows), "days_with_detections": len(rows)})


def live_fires(store: Store, weather: Callable[[], Weather | None], region: str) -> tuple[str, str, list[dict], dict]:
    found = fire_tools.list_fires(store, weather, region, "area_ha", fires.MAX_LISTED)
    rows = [_fire_row(f) for f in found["fires"]]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return (f"verner_fires_{safe(region)}_{stamp}.csv", _csv(FIRE_COLUMNS, rows), rows,
            {"fires_total": found["total"], "area_ha_total": round(sum(r["area_ha"] for r in rows), 1)})


def report(store: Store, area: areas.Area, first: int, last: int, title: str, text: str) -> tuple[str, str]:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    body = (f"# {title.strip()}\n\n{text.strip()}\n\n---\nSource: Verner. Data version {store.version}. "
            f"Prepared {stamp}.\n")
    return f"verner_{area.slug}_{month_label(first)}_{month_label(last)}_report.md", body


def keep(chat_files: Any, count: int, name: str, text: str, mime: str, kind: str, rows: int | None) -> dict:
    """Store a file in the chat and describe it; refuses past the limits."""
    data = text.encode("utf-8")
    if count >= MAX_PER_ANSWER:
        raise FileError("limit", f"At most {MAX_PER_ANSWER} files per answer.")
    if len(chat_files) >= MAX_PER_CHAT:
        raise FileError("limit", f"At most {MAX_PER_CHAT} files per chat.")
    if len(data) > MAX_BYTES:
        raise FileError("too_large", f"The file would be {len(data)} bytes, the limit is {MAX_BYTES}. Ask for a shorter period.")
    fid = uuid.uuid4().hex
    chat_files[fid] = {"name": name, "mime": mime, "data": data, "kind": kind, "rows": rows}
    return {"id": fid, "name": name, "mime": mime, "size": len(data), "rows": rows, "kind": kind}


def described(meta: dict, columns: tuple[str, ...], rows: list[dict], totals: dict) -> dict[str, Any]:
    """What the model may say about the file."""
    return {"file": {**{k: meta[k] for k in ("name", "kind", "rows", "size")}, "columns": list(columns)},
            "first_rows": [{c: r.get(c) for c in columns} for r in rows[:SAMPLE_ROWS]], "totals": totals}
