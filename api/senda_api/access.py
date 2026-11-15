"""The way to a fire: the nearest fire station, then the quickest road to the fire's edge, then the walk from the road's
end to the edge.

Sources, in this order. Stations: OpenStreetMap through Overpass (short timeouts, a failure is remembered for ten
minutes), then Google Places when a key is set, then the nearest place of the fire's own name (`origin_source: place`).
Route: OSRM, then Google Routes when OSRM does not answer. Google is the fallback and has a daily ceiling; what comes from
Google is never drawn on our map: no road line, no road end and no station point, only names, kilometres and minutes.
Every answer is kept on disk: a fire that grows hits the same cached ones.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from .db import Database
from .limits import DailyCounter

log = logging.getLogger("uvicorn.error").getChild("senda.access")

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
OSM_ATTRIBUTION = "Roads, places, fire stations and borders: © OpenStreetMap contributors, ODbL 1.0. Routes: OSRM."
GOOGLE_ATTRIBUTION = "Google Maps."
PLACE_ATTRIBUTION = "Nearest places: GeoNames (CC BY 4.0)."
USER_AGENT = "senda-api/0.1 (wildfire research; open data)"
MAX_PARALLEL = 2
WALK_KMH = 3.5
STATION_REACH_DEG = 0.75
"""Fire stations are looked for this far (about 80 km) around the fire's centre."""
GOOGLE_REACH_M = 50_000
"""The furthest Google Places searches."""
SNAP_DEG = 0.05
ROUTE_DEG = 0.01
"""Starts and ends of a route are rounded to this (about 1 km): a growing fire asks the same question."""
MEMORY = 128
TOTAL_S = 12.0
OVERPASS_BUDGET_S = 6.0
OVERPASS_TRY_S = 4.0
OSRM_TRY_S = 5.0
GOOGLE_TRY_S = 4.0
OVERPASS_PAUSE_S = 600.0
GOOGLE_PER_DAY = 300


class AccessError(Exception):
    """There is no way to the fire now: no network, no road, no start."""


class Http(Protocol):
    def get_json(self, url: str, timeout: float) -> Any: ...

    def post_form(self, url: str, form: dict[str, str], timeout: float) -> Any: ...

    def post_json(self, url: str, body: dict, headers: dict[str, str], timeout: float) -> Any: ...


class HttpClient:
    """The requests over httpx, at most 2 at a time. Errors say the host and the kind, never the URL (it may hold a key)."""

    def __init__(self, parallel: int = MAX_PARALLEL) -> None:
        self._client = httpx.Client(headers={"User-Agent": USER_AGENT})
        self._slots = threading.BoundedSemaphore(parallel)

    def _send(self, request: httpx.Request) -> Any:
        host = request.url.host
        with self._slots:
            try:
                res = self._client.send(request)
            except httpx.HTTPError as error:
                raise AccessError(f"{host}: {error.__class__.__name__}") from error
        if res.status_code != 200:
            raise AccessError(f"{host}: HTTP {res.status_code}")
        try:
            return res.json()
        except ValueError as error:
            raise AccessError(f"{host}: not JSON") from error

    def get_json(self, url: str, timeout: float) -> Any:
        return self._send(self._client.build_request("GET", url, timeout=timeout))

    def post_form(self, url: str, form: dict[str, str], timeout: float) -> Any:
        return self._send(self._client.build_request("POST", url, data=form, timeout=timeout))

    def post_json(self, url: str, body: dict, headers: dict[str, str], timeout: float) -> Any:
        return self._send(self._client.build_request("POST", url, json=body, headers=headers, timeout=timeout))


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Approximate distance between two [lon, lat] points over short ranges, kilometres."""
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * 111.32 * math.cos(lat), (a[1] - b[1]) * 110.57)


def _snap(value: float, step: float) -> float:
    return round(round(value / step) * step, 2)


@dataclass(frozen=True)
class Origin:
    name: str
    lon: float
    lat: float
    source: str  # `osm`, `google` or `place`


class Clock:
    """The time of the run: a deadline for the whole way, and what is left of it."""

    def __init__(self, total: float = TOTAL_S, now: Callable[[], float] = time.monotonic) -> None:
        self.now, self.end = now, now() + total

    def left(self, cap: float) -> float:
        """The timeout for one request: the cap, or what is left of the run; 0 when nothing is."""
        return max(0.0, min(cap, self.end - self.now()))


def overpass_stations(http: Http, box: tuple[float, float, float, float], clock: Clock) -> list[list]:
    """Fire stations inside the box (west, south, east, north): [name, lon, lat]. The mirrors are tried in turn within
    6 seconds in all, 4 for each at most."""
    west, south, east, north = box
    area = f"({south},{west},{north},{east})"
    ql = f'[out:json][timeout:25];(node["amenity"="fire_station"]{area};way["amenity"="fire_station"]{area};);out center tags;'
    until = clock.now() + OVERPASS_BUDGET_S
    last: Exception | None = None
    for url in OVERPASS_URLS:
        timeout = min(OVERPASS_TRY_S, until - clock.now(), clock.left(OVERPASS_TRY_S))
        if timeout < 0.5:
            break
        try:
            elements = http.post_form(url, {"data": ql}, timeout)["elements"]
        except (AccessError, KeyError, TypeError) as error:  # a mirror may fail in any way; the next one is tried
            last = error
            continue
        found = []
        for element in elements:
            lon = element.get("lon", element.get("center", {}).get("lon"))
            lat = element.get("lat", element.get("center", {}).get("lat"))
            if element.get("tags", {}).get("amenity") == "fire_station" and lon is not None and lat is not None:
                found.append([element.get("tags", {}).get("name") or "Fire station", lon, lat])
        return found
    raise AccessError(f"Overpass did not answer: {last}")


def google_stations(http: Http, key: str, centre: tuple[float, float], clock: Clock) -> list[list]:
    """The three fire stations nearest to the centre within 50 km, from Google Places: [name, lon, lat]."""
    timeout = clock.left(GOOGLE_TRY_S)
    if timeout < 0.5:
        raise AccessError("no time left for Google Places")
    body = {"includedTypes": ["fire_station"], "maxResultCount": 3, "rankPreference": "DISTANCE",
            "locationRestriction": {"circle": {"center": {"latitude": centre[1], "longitude": centre[0]},
                                               "radius": GOOGLE_REACH_M}}}
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": "places.displayName,places.location"}
    answer = http.post_json(PLACES_URL, body, headers, timeout)
    return [[p.get("displayName", {}).get("text") or "Fire station", p["location"]["longitude"], p["location"]["latitude"]]
            for p in answer.get("places", []) if "location" in p]


def osrm_route(http: Http, origin: tuple[float, float], target: tuple[float, float], clock: Clock) -> dict:
    """OSRM driving from `origin` to the road point nearest to `target`."""
    timeout = clock.left(OSRM_TRY_S)
    if timeout < 0.5:
        raise AccessError("no time left for OSRM")
    url = f"{OSRM_URL}/{origin[0]},{origin[1]};{target[0]},{target[1]}?overview=full&geometries=geojson"
    answer = http.get_json(url, timeout)
    if answer.get("code") != "Ok" or not answer.get("routes"):
        raise AccessError("there is no road route")
    route, end = answer["routes"][0], answer["waypoints"][1]["location"]
    return {"drive_s": route["duration"], "drive_m": route["distance"], "road_end": [round(end[0], 5), round(end[1], 5)],
            "path": [[round(x, 5), round(y, 5)] for x, y in route["geometry"]["coordinates"]]}


def google_route(http: Http, key: str, origin: tuple[float, float], target: tuple[float, float], clock: Clock) -> dict:
    """Google Routes driving: time, distance and where the road ends. No line: it is not ours to draw."""
    timeout = clock.left(GOOGLE_TRY_S)
    if timeout < 0.5:
        raise AccessError("no time left for Google Routes")

    def point(p: tuple[float, float]) -> dict:
        return {"location": {"latLng": {"latitude": p[1], "longitude": p[0]}}}

    headers = {"X-Goog-Api-Key": key,
               "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.legs.endLocation"}
    answer = http.post_json(ROUTES_URL, {"origin": point(origin), "destination": point(target), "travelMode": "DRIVE"},
                            headers, timeout)
    try:
        route = answer["routes"][0]
        end = route["legs"][-1]["endLocation"]["latLng"]
        return {"drive_s": float(str(route["duration"]).rstrip("s")), "drive_m": float(route["distanceMeters"]),
                "road_end": [round(end["longitude"], 5), round(end["latitude"], 5)]}
    except (KeyError, IndexError, ValueError, TypeError) as error:
        raise AccessError("there is no road route") from error


class Access:
    """Finds the way to a fire; `folder` keeps the answers as JSON between runs (None: memory only)."""

    def __init__(self, folder: Path | None = None, http: Http | None = None, google_key: str | None = None,
                 today: Callable[[], str] = lambda: datetime.now(UTC).date().isoformat(),
                 now: Callable[[], float] = time.monotonic, db: Database | None = None) -> None:
        self.folder, self.http, self.key = folder, http or HttpClient(), google_key
        self._today, self._now = today, now
        self._kept: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()
        self._osm_down_until = 0.0
        # the Google calls of the UTC day: in Postgres when there is one, so a restart does not start them again
        self._google_calls = DailyCounter("google_calls", db, lambda: date.fromisoformat(self._today()))

    # cache: memory and a small JSON file per answer
    def _remember(self, key: str, value: Any) -> None:
        with self._lock:
            self._kept[key] = value
            while len(self._kept) > MEMORY:
                self._kept.popitem(last=False)

    def _get(self, key: str) -> Any:
        with self._lock:
            if key in self._kept:
                self._kept.move_to_end(key)
                return self._kept[key]
        if self.folder is not None:
            try:
                value = json.loads((self.folder / f"{key}.json").read_text())
            except (OSError, ValueError):
                return None
            self._remember(key, value)
            return value
        return None

    def _put(self, key: str, value: Any) -> None:
        self._remember(key, value)
        if self.folder is None:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.folder / f".{key}.tmp"
            tmp.write_text(json.dumps(value, separators=(",", ":")))
            tmp.replace(self.folder / f"{key}.json")
        except OSError:
            pass  # the cache is a convenience: the answer does not depend on it

    # Google has a ceiling per day; above it Google is taken as not available
    def _google_ok(self) -> bool:
        if not self.key:
            return False
        return self._google_calls.take(1, GOOGLE_PER_DAY)

    def _stations(self, cx: float, cy: float, centre: tuple[float, float], clock: Clock) -> tuple[list, str]:
        """The stations near the fire and where they come from (`osm`, `google`); an empty list when none was found."""
        osm = self._get(f"stations_osm_{cx}_{cy}")
        if osm is None and self._now() >= self._osm_down_until:
            box = (cx - STATION_REACH_DEG, cy - STATION_REACH_DEG, cx + STATION_REACH_DEG, cy + STATION_REACH_DEG)
            try:
                osm = overpass_stations(self.http, box, clock)
                self._put(f"stations_osm_{cx}_{cy}", osm)
            except AccessError as error:
                self._osm_down_until = self._now() + OVERPASS_PAUSE_S
                log.info("access: Overpass is not answering (%s); not asked again for ten minutes", error)
        if osm:
            return osm, "osm"
        google = self._get(f"stations_google_{cx}_{cy}")
        if google is None and self._google_ok():
            try:
                google = google_stations(self.http, self.key or "", centre, clock)
                self._put(f"stations_google_{cx}_{cy}", google)
            except AccessError as error:
                log.info("access: Google Places failed (%s)", error)
        return google or [], "google"

    def _route(self, start: tuple[float, float], target: tuple[float, float], clock: Clock) -> tuple[dict, str]:
        tag = f"{start[0]}_{start[1]}_{target[0]}_{target[1]}"
        found = self._get(f"route_osrm_{tag}")
        if found is not None:
            return found, "osrm"
        found = self._get(f"route_google_{tag}")
        if found is not None:
            return found, "google"
        try:
            found = osrm_route(self.http, start, target, clock)
            self._put(f"route_osrm_{tag}", found)
            return found, "osrm"
        except AccessError as error:
            log.info("access: OSRM failed (%s)", error)
        if self._google_ok():
            found = google_route(self.http, self.key or "", start, target, clock)
            self._put(f"route_google_{tag}", found)
            return found, "google"
        raise AccessError("there is no road route")

    def of_outline(self, outline: list, place: dict | None) -> dict:
        """The way to a fire with this outline and nearest place (as in the fire list): an `AccessRoute`, with
        where each part came from. Google's part carries no coordinates of its own."""
        clock = Clock(now=self._now)
        centre = (sum(p[0] for p in outline) / len(outline), sum(p[1] for p in outline) / len(outline))
        cx, cy = _snap(centre[0], SNAP_DEG), _snap(centre[1], SNAP_DEG)
        found, source = self._stations(cx, cy, centre, clock)
        if found:
            name, lon, lat = min(found, key=lambda s: distance_km(centre, (s[1], s[2])))
            origin = Origin(name, lon, lat, source)
        elif place:
            origin = Origin(place["name"], place["location"][0], place["location"][1], "place")
        else:
            raise AccessError("there is no fire station or place to start from")
        edge = min(outline, key=lambda v: distance_km(v, (origin.lon, origin.lat)))
        target = (_snap(edge[0], ROUTE_DEG), _snap(edge[1], ROUTE_DEG))
        route, route_source = self._route((round(origin.lon, 4), round(origin.lat, 4)), target, clock)
        end = route["road_end"]
        walk_km = distance_km((end[0], end[1]), (edge[0], edge[1]))
        drive_min = route["drive_s"] / 60
        log.info("access: start from %s, route from %s", origin.source, route_source)
        credit = []
        if origin.source == "osm" or route_source == "osrm":
            credit.append(OSM_ATTRIBUTION)
        if origin.source == "place":
            credit.append(PLACE_ATTRIBUTION)
        if origin.source == "google" or route_source == "google":
            credit.append(GOOGLE_ATTRIBUTION)
        return {
            "origin_kind": "station" if origin.source != "place" else "place",
            "origin_source": origin.source, "route_source": route_source,
            "station_name": origin.name,
            "station_location": None if origin.source == "google" else [origin.lon, origin.lat],
            "drive_min": round(drive_min), "drive_km": round(route["drive_m"] / 1000, 1), "walk_km": round(walk_km, 1),
            "walk_min": round(walk_km / WALK_KMH * 60), "total_min": round(drive_min + walk_km / WALK_KMH * 60, 1),
            "fire_edge_point": [round(edge[0], 5), round(edge[1], 5)],
            "road_end_point": None if route_source == "google" else end,
            "road_path": None if route_source == "google" else route["path"],
            "attribution": " ".join(credit),
        }
