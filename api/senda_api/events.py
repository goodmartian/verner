"""Known fire seasons checked against the calendar of their region."""

from __future__ import annotations

import json
from pathlib import Path

from . import areas, calendar
from .months import month_label, parse_month_label
from .store import Store

EVENTS_LIST = Path(__file__).with_name("events_list.json")
TOP_RANKS = 3
MIN_RATIO = 2.0


def load_list(path: Path = EVENTS_LIST) -> list[dict]:
    return json.loads(path.read_text())


def is_found(ratio: float | None, rank: int | None) -> bool:
    """An event is found when its month is among the top three of the same calendar month and at least twice usual."""
    return ratio is not None and rank is not None and rank <= TOP_RANKS and ratio >= MIN_RATIO


def compute(store: Store, definitions: list[dict]) -> list[dict]:
    out = []
    for event in definitions:
        region = store.regions.by_id.get(event["region_id"])
        if region is None:
            raise ValueError(f"event {event['id']}: region {event['region_id']} is not in regions.parquet")
        month = parse_month_label(event["month"])
        cal = calendar.build(store, areas.parse({"id": event["region_id"]}, store), month_label(month), month_label(month))
        el = cal["series"][0]
        out.append({
            "id": event["id"], "region_id": event["region_id"], "region_name": event["region_name"],
            "month": event["month"], "era": event["era"], "count": el["count"], "median": el["median"],
            "ratio": el["ratio"], "rank": el["rank"], "of": el["of"], "found": is_found(el["ratio"], el["rank"]),
            "source_url": event.get("source_url"),
        })
    return out
