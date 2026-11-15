"""Regions (countries and sub-national regions): the index by id and point, names in four languages, time zone, type
labels and search by word prefix.

The region table has English names only; provinces take their French, Spanish and Russian names from Natural Earth
(`reference/region_names.json`) and fall back to English. A province carries a type label when its admin-1 type
(`reference/region_type_en.json`) has translations in `reference/region_types.json`. The reference files are made by
`scripts/build_reference.py`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import shapely
from shapely.strtree import STRtree
from timezonefinder import TimezoneFinder

if TYPE_CHECKING:
    from .store import Store

def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text).casefold().replace("ё", "е"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.split())


def _names(raw) -> dict[str, str]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        value = None
    if isinstance(value, dict) and value:
        return {str(k): str(v) for k, v in value.items()}
    return {"en": str(raw)}


def _bbox(raw) -> list[float]:
    value = json.loads(raw) if isinstance(raw, str) else raw
    return [float(v) for v in value]


@dataclass(eq=False)
class Region:
    id: str
    kind: str
    country_id: str
    names: dict[str, str]
    bbox: list[float]
    area_km2: float
    geometry: shapely.Geometry
    name: str = ""
    name_key: str = ""
    other_keys: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.name = self.names.get("en") or next(iter(self.names.values()))
        self.name_key = _norm(self.name)
        self.other_keys = [_norm(v) for k, v in self.names.items() if k != "en"]


class RegionIndex:
    def __init__(self, records: list[Region]):
        self.records = records
        self.by_id = {r.id: r for r in records}
        self.tree = STRtree([r.geometry for r in records]) if records else None


def build_index(df: pl.DataFrame) -> RegionIndex:
    records = []
    for rec in df.iter_rows(named=True):
        records.append(
            Region(
                id=str(rec["id"]),
                kind=str(rec["kind"]),
                country_id=str(rec["country_id"]),
                names=_names(rec["names_json"]),
                bbox=_bbox(rec["bbox"]),
                area_km2=float(rec["area_km2"]),
                geometry=shapely.from_wkb(rec["geometry_wkb"]),
            )
        )
    return RegionIndex(records)


LANGUAGES = ["en", "fr", "es", "ru"]
_DATA = Path(__file__).parent / "reference"
_FINDER = TimezoneFinder()


@lru_cache(maxsize=1)
def country_names() -> dict[str, dict[str, str]]:
    raw = json.loads((_DATA / "country_metadata.json").read_text())
    return {k: v["names"] for k, v in raw.items()}


@lru_cache(maxsize=1)
def region_names() -> dict[str, dict[str, str]]:
    """French, Spanish and Russian names of provinces from Natural Earth admin-1 (`name_fr`, `name_es`, `name_ru`)."""
    return json.loads((_DATA / "region_names.json").read_text())


@lru_cache(maxsize=1)
def type_labels() -> tuple[dict[str, dict], dict[str, str]]:
    return json.loads((_DATA / "region_types.json").read_text()), json.loads((_DATA / "region_type_en.json").read_text())


def type_of(region_id: str) -> str | None:
    """The key of a region's type in `region_types.json`, when it has translations."""
    labels, by_region = type_labels()
    kind = by_region.get(region_id)
    return kind if kind in labels else None


def types_of(keys) -> dict[str, dict]:
    """The labels of the given type keys, in four languages: sent once beside the regions that carry the keys."""
    labels, _ = type_labels()
    return {k: labels[k] for k in sorted({k for k in keys if k})}


def short_bbox(bbox: list[float]) -> list[float]:
    """Three decimals, about 100 m: enough to frame a map on a region."""
    return [round(v, 3) for v in bbox]


def names_of(region: Region) -> dict[str, str]:
    known = country_names().get(region.id) if region.kind == "country" else region_names().get(region.id)
    base = {**region.names, **(known or {})}
    fallback = base.get("en") or next(iter(base.values()))
    return {lang: base.get(lang) or fallback for lang in LANGUAGES}


_ZONES: dict[str, str] = {}


def geometry_zone(geometry) -> str:
    """IANA zone at an interior point of the geometry (the centre when that point is at sea)."""
    point = geometry.representative_point()
    zone = _FINDER.timezone_at(lng=point.x, lat=point.y)
    if zone is None:
        c = geometry.centroid
        zone = _FINDER.timezone_at(lng=c.x, lat=c.y) or "UTC"
    return zone


def zone_of(region: Region) -> str:
    zone = _ZONES.get(region.id)
    if zone is None:
        zone = _ZONES[region.id] = geometry_zone(region.geometry)
    return zone


@dataclass
class NameIndex:
    """Search entries over ids and names in every language, sorted for prefix lookup."""

    index: RegionIndex
    names: dict[str, dict[str, str]] = field(default_factory=dict)
    entries: list[tuple[str, str, str]] = field(default_factory=list)
    order: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        records = self.index.records
        ordered = sorted(records, key=lambda r: (r.kind != "country", r.name))
        self.order = {r.id: i for i, r in enumerate(ordered)}
        entries: set[tuple[str, str, str]] = set()
        for r in records:
            self.names[r.id] = names_of(r)
            for lang in LANGUAGES:
                for value in (r.id, self.names[r.id][lang]):
                    text = _norm(value)
                    entries.add((text, r.id, lang))
                    for word in re.split(r"[\s\-]+", text):
                        entries.add((word, r.id, lang))
        self.entries = sorted(entries)

    def search(self, q: str = "", country: str | None = None, kind: str | None = None, lang: str | None = None,
               limit: int | None = None) -> list[Region]:
        prefix = _norm(q.strip())
        matching = None
        if prefix:
            matching = set()
            for i in range(bisect_left(self.entries, (prefix, "", "")), len(self.entries)):
                name, rid, language = self.entries[i]
                if not name.startswith(prefix):
                    break
                if lang is None or lang == language:
                    matching.add(rid)
        out = [r for r in sorted(self.index.records, key=lambda r: self.order[r.id])
               if (matching is None or r.id in matching)
               and (country is None or r.country_id == country)
               and (kind is None or r.kind == kind)]
        if prefix:
            # an exact name first, then countries (the largest first, so "United States" opens with the country
            # itself, not its minor islands), then the rest in catalog order
            out.sort(key=lambda r: (_norm(self.names[r.id].get(lang or "en", r.name)) != prefix
                                    and _norm(r.id) != prefix, r.kind != "country",
                                    -r.area_km2 if r.kind == "country" else self.order[r.id]))
        return out if limit is None else out[:limit]


def region_index(store: Store) -> NameIndex:
    return store.once("names", lambda: NameIndex(store.regions))


def region_item(store: Store, region: Region, fires_now: int = 0) -> dict:
    idx = region_index(store)
    return {
        "id": region.id, "kind": region.kind, "country_id": region.country_id, "names": idx.names[region.id],
        "type": type_of(region.id), "timezone": zone_of(region), "covered": True, "bbox": short_bbox(region.bbox),
        "fires_now": fires_now,
    }


def find(store: Store, query: str, limit: int) -> list[dict]:
    """The best `limit` regions for a name, as the chat's `find_region` tool shows them."""
    index = store.regions
    out = []
    for r in region_index(store).search(query, limit=limit):
        country = index.by_id.get(r.country_id)
        out.append({"id": r.id, "kind": r.kind, "country_id": r.country_id,
                    "country_name": country.name if country else r.name, "name": r.name, "bbox": r.bbox})
    return out
