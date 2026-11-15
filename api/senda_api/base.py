"""Health, config, regions and world countries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from . import areas
from . import fires as fires_mod
from .contracts import Config, Health, RegionGeometry, Regions, WorldCountries, ok
from .errors import ApiError
from .regions import LANGUAGES, region_index, region_item, short_bbox, types_of, zone_of
from .store import Store
from .world import world_of

router = APIRouter(tags=["api"])

ATTRIBUTION = "Administrative boundaries: Natural Earth 10m (public domain)."
WORLD_ATTRIBUTION = "Fire detections: NASA FIRMS (MODIS and VIIRS), harmonized by Verner."
DEFAULT_AREA = "AR"
SEARCH_LIMIT = 50


def store_of(request: Request) -> Store:
    return request.app.state.get_store(request)


@router.get("/api/health", responses=ok(Health))
def health(request: Request):
    data = store_of(request)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    built = data.manifest.get("built_at") or data.manifest.get("created_at")
    db = request.app.state.db
    up = db.ping()  # the site works without it: chats and plans answer 503 `storage_unavailable`
    return {
        "status": "ok", "database": "ok" if up else "down", "schema_revision": db.revision_state() if up else "unknown",
        "artifacts": [{"name": "calendar", "version": data.version, "built_at": built, "loaded_at": now,
                       "error": None}],
        "ok": True, "data_version": data.version,
    }


@router.get("/api/config", responses=ok(Config))
def config(request: Request):
    data = store_of(request)
    idx = region_index(data)
    countries = [{"id": r.id, "names": idx.names[r.id], "bbox": short_bbox(r.bbox)}
                 for r in sorted(data.regions.records, key=lambda r: idx.order[r.id]) if r.kind == "country"]
    first = data.first_month // 12 + 2000
    last = data.cur_month // 12 + 2000
    default = DEFAULT_AREA if DEFAULT_AREA in data.regions.by_id else (countries[0]["id"] if countries else "WORLD")
    return {"covered_countries": countries, "languages": LANGUAGES, "archive_years": list(range(first, last + 1)),
            "default_area": default}


@router.get("/api/regions", responses=ok(Regions))
def get_regions(
    request: Request,
    demo: bool = False,
    q: Annotated[str, Query(max_length=120)] = "",
    country: Annotated[str | None, Query(max_length=64)] = None,
    kind: Literal["country", "region", "province"] | None = None,
    lang: Annotated[str | None, Query(max_length=8)] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    data = store_of(request)
    if lang is not None and lang not in LANGUAGES:
        raise ApiError(422, "validation_error", "lang: not a configured language")
    if not q.strip() and country is None and kind is None:
        kind = "country"  # the start of the site needs the countries; the regions of one come with `country`
    if q.strip() and limit is None:
        limit = SEARCH_LIMIT
    found = region_index(data).search(q, country, None if kind == "province" else kind, lang, limit)
    items = [region_item(data, r, fires_mod.fires_now(data, r, demo)) for r in found]
    return {"regions": items, "types": types_of(i["type"] for i in items), "attribution": ATTRIBUTION}


@router.get("/api/regions/{region_id}/geometry", responses=ok(RegionGeometry))
def get_region_geometry(region_id: str, request: Request):
    data = store_of(request)
    region = data.regions.by_id.get(region_id)
    if region is None:
        raise ApiError(404, "not_found", f"No data for region {region_id}")
    return {"id": region.id, "geometry": areas.to_geojson(region.geometry), "bbox": region.bbox,
            "timezone": zone_of(region), "covered": True}


@router.get("/api/world/countries", responses=ok(WorldCountries))
def world_countries(
    request: Request,
    ids: Annotated[str | None, Query()] = None,
    years: Annotated[str | None, Query(pattern=r"^\d{4}(,\d{4})*$")] = None,
):
    data = store_of(request)
    id_list = [i.strip().upper() for i in ids.split(",") if i.strip()][:10] if ids else None
    if id_list is not None:
        for rid in id_list:
            region = data.regions.by_id.get(rid)
            if region is None or region.kind != "country":
                raise ApiError(404, "not_found", f"No data for {rid}")
    year_list = [int(y) for y in years.split(",")][:10] if years else None
    return world_of(data).countries(id_list, year_list, WORLD_ATTRIBUTION)
