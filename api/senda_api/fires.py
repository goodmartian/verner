"""Fires: live fires of the last three days and the fires of an archive day.

A fire is a group of detections whose 0.0135 degree cells touch.
Live fires come from the VIIRS rows of the last days on disk, grouped for the whole world at once. Satellite
passes are numbered per country: detections of the country's fires sorted by time and cut at gaps of 30 minutes.
The nearest place is the nearest GeoNames place of 1000 inhabitants or more.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from . import areas, export
from .regions import geometry_zone
from .store import Store

LINK_CELL_DEG = 0.0135  # detections in neighbouring cells of this size belong to one fire
MIN_FIRE_DETECTIONS = 25
MAX_LISTED = 50  # fires in one list, the largest first
PASS_GAP_MS = 30 * 60 * 1000
AREA_CELL_DEG = (0.0039, 0.0034)  # cell of the burning-area estimate (lon, lat), about 14 ha
AREA_CELL_HA = 14
OUTLINE_PAD_DEG = 0.0025
WINDOW_DAYS = 3
EARTH_KM = 6371.0088
_WIDTH = 100_000
_ROW_SHIFT = 10_000
_COL_SHIFT = 20_000
ATTRIBUTION = "Fire detections: NASA FIRMS (VIIRS). Nearest places: GeoNames (CC BY 4.0)."


def iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def link(lon: np.ndarray, lat: np.ndarray, group: np.ndarray | None = None) -> np.ndarray:
    """Fire number of each detection; detections of different `group` values never join."""
    if len(lon) == 0:
        return np.zeros(0, dtype=np.int64)
    cx = np.floor(lon / LINK_CELL_DEG).astype(np.int64) + _COL_SHIFT
    cy = np.floor(lat / LINK_CELL_DEG).astype(np.int64) + _ROW_SHIFT
    key = cy * _WIDTH + cx
    if group is not None:
        key = key + (group - group.min()) * (_WIDTH * 2 * _ROW_SHIFT)
    unique, inverse = np.unique(key, return_inverse=True)
    rows, cols = [], []
    for dy, dx in ((0, 1), (1, -1), (1, 0), (1, 1)):
        neighbour = unique + dy * _WIDTH + dx
        pos = np.searchsorted(unique, neighbour)
        ok = (pos < len(unique)) & (unique[np.minimum(pos, len(unique) - 1)] == neighbour)
        rows.append(np.nonzero(ok)[0])
        cols.append(pos[ok])
    r, c = np.concatenate(rows), np.concatenate(cols)
    graph = coo_matrix((np.ones(len(r), dtype=np.int8), (r, c)), shape=(len(unique), len(unique)))
    _, component = connected_components(graph, directed=False)
    return component[inverse]


def assign_regions(store: Store, lon: np.ndarray, lat: np.ndarray) -> tuple[list[str | None], list[str | None]]:
    """Smallest non-country region (province) and the country of each point."""
    provinces: list[str | None] = [None] * len(lon)
    countries: list[str | None] = [None] * len(lon)
    index = store.regions
    if index.tree is None or len(lon) == 0:
        return provinces, countries
    inp, hit = index.tree.query(shapely.points(lon, lat), predicate="intersects")
    size = np.array([r.area_km2 for r in index.records])
    order = np.lexsort((size[hit], inp))
    for i, h in zip(inp[order].tolist(), hit[order].tolist(), strict=True):
        region = index.records[h]
        if countries[i] is None:
            countries[i] = region.country_id
        if provinces[i] is None and region.kind != "country":
            provinces[i] = region.id
    return provinces, countries


# --- places ---


@dataclass
class Places:
    tree: cKDTree
    lon: np.ndarray
    lat: np.ndarray
    name: list[str]


def _xyz(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    a, b = np.radians(lon), np.radians(lat)
    return np.column_stack([np.cos(b) * np.cos(a), np.cos(b) * np.sin(a), np.sin(b)])


_PLACES: dict[str, Places | None] = {}


def places_path(store: Store) -> Path:
    return Path(store.root).resolve().parents[1] / "_work" / "geo" / "places.parquet"


def places_of(store: Store) -> Places | None:
    path = places_path(store)
    key = str(path)
    if key not in _PLACES:
        if path.exists():
            df = pl.read_parquet(path)
            lon, lat = df["lon"].to_numpy().astype(float), df["lat"].to_numpy().astype(float)
            _PLACES[key] = Places(cKDTree(_xyz(lon, lat)), lon, lat, df["name"].to_list())
        else:
            _PLACES[key] = None
    return _PLACES[key]


def bearing(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Compass bearing in degrees from point 1 to point 2."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def compass(degrees: float) -> int:
    return round(degrees / 45) % 8


MIN_GAP_H, MAX_GAP_H = 1, 24

# --- live fires ---


@dataclass
class Fire:
    id: str
    lon: float
    lat: float
    idx: np.ndarray  # detections, by time
    country: str | None
    province: str | None
    place: dict = field(default_factory=dict)


@dataclass
class CountryPasses:
    starts: list[int]  # ms
    counts: list[int]


class Live:
    """The fires of the last days of the rows on disk."""

    def __init__(self, store: Store, frame: pl.DataFrame | None):
        self.store = store
        empty = frame is None or frame.is_empty()
        self.days: list[date] = []
        self.updated_ms = 0
        self.fires: list[Fire] = []
        self.passes: dict[str | None, CountryPasses] = {}
        self.pass_of = np.zeros(0, dtype=np.int64)
        self.lon = self.lat = self.frp = np.zeros(0)
        self.t = np.zeros(0, dtype=np.int64)
        if empty:
            return
        assert frame is not None
        frame = frame.sort("acq_utc")
        self.lon = frame["lon"].to_numpy().astype(float)
        self.lat = frame["lat"].to_numpy().astype(float)
        self.t = frame["acq_utc"].dt.epoch("ms").to_numpy().astype(np.int64)
        self.frp = np.nan_to_num(frame["frp_mw"].to_numpy().astype(float))
        last = frame["local_date"].max()
        self.days = [last - timedelta(days=k) for k in range(WINDOW_DAYS - 1, -1, -1)]
        self.updated_ms = int(self.t.max())
        self._group()

    def _group(self) -> None:
        label = link(self.lon, self.lat)
        sizes = np.bincount(label)
        big = np.nonzero(sizes >= MIN_FIRE_DETECTIONS)[0]
        if len(big) == 0:
            return
        order = np.argsort(label, kind="stable")
        bounds = np.searchsorted(label[order], big), np.searchsorted(label[order], big, side="right")
        members = [order[a:b] for a, b in zip(*bounds, strict=True)]  # each already sorted by time
        centers_lon = np.array([self.lon[m].mean() for m in members])
        centers_lat = np.array([self.lat[m].mean() for m in members])
        provinces, countries = assign_regions(self.store, centers_lon, centers_lat)
        first_day = [datetime.fromtimestamp(self.t[m[0]] / 1000, UTC).date() for m in members]
        for i, m in enumerate(members):
            tag = hashlib.sha1(f"{round(centers_lon[i], 1)}_{round(centers_lat[i], 1)}".encode()).hexdigest()[:6]
            self.fires.append(Fire(f"{first_day[i]:%Y%m%d}-{tag}", float(centers_lon[i]), float(centers_lat[i]), m,
                                   countries[i], provinces[i]))
        self.fires.sort(key=lambda f: -len(f.idx))
        self._places()
        self._passes()

    def _places(self) -> None:
        places = places_of(self.store)
        lon = np.array([f.lon for f in self.fires])
        lat = np.array([f.lat for f in self.fires])
        if places is None:
            for f in self.fires:
                rid = f.province or f.country
                name = self.store.regions.by_id[rid].name if rid in self.store.regions.by_id else "Unknown"
                f.place = {"name": name, "distance_km": 0.0, "location": [round(f.lon, 4), round(f.lat, 4)],
                           "direction": 0}
            return
        chord, nearest = places.tree.query(_xyz(lon, lat))
        for f, c, j in zip(self.fires, chord, nearest, strict=True):
            plon, plat = float(places.lon[j]), float(places.lat[j])
            f.place = {"name": places.name[j], "distance_km": round(2 * EARTH_KM * math.asin(min(1.0, c / 2)), 1),
                       "location": [round(plon, 5), round(plat, 5)],
                       "direction": compass(bearing(plon, plat, f.lon, f.lat))}

    def _passes(self) -> None:
        self.pass_of = np.zeros(len(self.t), dtype=np.int64)
        by_country: dict[str | None, list[np.ndarray]] = {}
        for f in self.fires:
            by_country.setdefault(f.country, []).append(f.idx)
        for cc, parts in by_country.items():
            idx = np.sort(np.concatenate(parts))
            times = self.t[idx]
            new = np.r_[True, np.diff(times) >= PASS_GAP_MS]
            number = np.cumsum(new) - 1
            self.pass_of[idx] = number
            self.passes[cc] = CountryPasses([int(x) for x in times[new]], np.bincount(number).tolist())

    # --- views ---

    def in_region(self, region_id: str | None) -> list[Fire]:
        if region_id is None or region_id == areas.WORLD_ID:
            return self.fires
        region = self.store.regions.by_id[region_id]
        if region.kind == "country":
            return [f for f in self.fires if f.country == region_id]
        return [f for f in self.fires if f.province == region_id]

    def count(self, region_id: str) -> int:
        return len(self.in_region(region_id))

    def growth(self, fire: Fire) -> list[dict]:
        passes = self.passes[fire.country]
        n = len(passes.starts)
        number = self.pass_of[fire.idx]
        per_pass = np.bincount(number, minlength=n)
        frp = np.bincount(number, weights=self.frp[fire.idx], minlength=n)
        cells = _cell_keys(self.lon[fire.idx], self.lat[fire.idx])
        first_pass: dict[int, int] = {}
        for c, p in zip(cells.tolist(), number.tolist(), strict=True):
            if c not in first_pass or p < first_pass[c]:
                first_pass[c] = p
        new_cells = np.bincount(np.fromiter(first_pass.values(), dtype=np.int64), minlength=n)
        total = np.cumsum(per_pass)
        area = np.cumsum(new_cells) * AREA_CELL_HA
        out, latest = [], 0
        for p in range(n):
            if per_pass[p] > 0:
                latest = round(frp[p])
            out.append({"pass_index": p, "time": iso(passes.starts[p]), "detections": int(total[p]),
                        "pass_detections": int(per_pass[p]), "area_ha": int(area[p]), "frp_mw": latest})
        return out

    def summary(self, fire: Fire, with_growth: bool = True) -> dict:
        times = self.t[fire.idx]
        growth = self.growth(fire) if with_growth else []
        return {
            "id": fire.id, "center": [round(fire.lon, 4), round(fire.lat, 4)], "nearest_place": fire.place,
            "detection_count": len(fire.idx), "area_ha": growth[-1]["area_ha"] if growth else _area_ha(self, fire.idx),
            "first_detection_at": iso(times.min()), "last_detection_at": iso(times.max()), "growth": growth,
            "timezone": geometry_zone(shapely.Point(fire.lon, fire.lat)),
        }

    def listing(self, region_id: str | None, chosen: list[Fire] | None = None) -> dict:
        """The fires of a region, the first MAX_LISTED; `chosen` lists these fires instead, in its order."""
        shown = self.in_region(region_id)[:MAX_LISTED] if chosen is None else chosen
        country = self._country_of(region_id)
        passes = self.passes.get(country)
        return {
            "source": "live", "available": len(self.t) > 0,
            "updated_at": iso(self.updated_ms) if len(self.t) else None, "days": [d.isoformat() for d in self.days],
            "passes": [{"index": i, "time": iso(s), "detection_count": c}
                       for i, (s, c) in enumerate(zip(passes.starts, passes.counts, strict=True))] if passes else [],
            "fires": [self.summary(f, with_growth=passes is not None) for f in shown], "attribution": ATTRIBUTION,
        }

    def _country_of(self, region_id: str | None) -> str | None:
        if region_id is None or region_id == areas.WORLD_ID:
            return None
        return self.store.regions.by_id[region_id].country_id

    def find(self, fire_id: str) -> Fire | None:
        return next((f for f in self.fires if f.id == fire_id), None)

    def spread(self, fire: Fire, upto: int) -> dict | None:
        """Speed of the head between the last two passes (up to `upto`) that saw this fire, from the detections alone.

        The head is how far the newer detections lie from the older ones (90th percentile of the distance to the
        nearest older detection). Needs a gap of MIN_GAP_H to MAX_GAP_H hours between the passes and a moving edge;
        otherwise None. Wind, shape and contours come from the weather and are added by the route (null and empty here).
        """
        number = self.pass_of[fire.idx]
        seen = np.unique(number[number <= upto])
        if len(seen) < 2:
            return None
        before, after = int(seen[-2]), int(seen[-1])
        starts = self.passes[fire.country].starts
        hours = (starts[after] - starts[before]) / 3_600_000
        if not MIN_GAP_H <= hours <= MAX_GAP_H:
            return None
        scale = np.cos(np.radians(fire.lat))
        metres = 111_320.0

        def xy(sel: np.ndarray) -> np.ndarray:
            return np.column_stack([self.lon[sel] * scale * metres, self.lat[sel] * metres])

        old, new = xy(fire.idx[number == before]), xy(fire.idx[number == after])
        distance = float(np.percentile(cKDTree(old).query(new)[0], 90))
        rate = distance / hours
        if rate <= 0:
            return None
        return {"rate_m_per_h": round(rate, 1), "observed": True, "rate_source": "measured",
                "rate_weather_m_per_h": None, "rate_measured_m_per_h": round(rate, 1), "length_to_breadth": None,
                "wind": None, "contours": [], "current_area_ha": float(self.growth(fire)[upto]["area_ha"])}

    def detail(self, fire: Fire, pass_index: int | None) -> dict:
        passes = self.passes[fire.country]
        last = len(passes.starts) - 1
        upto = last if pass_index is None else pass_index
        number = self.pass_of[fire.idx]
        keep = fire.idx[number <= upto]
        core = fire.idx[(number <= upto) & (number >= upto - 1)]
        lon, lat = self.lon[keep], self.lat[keep]
        days: dict[str, int] = {d.isoformat(): 0 for d in self.days}
        for ms in self.t[fire.idx]:
            key = datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()
            days[key] = days.get(key, 0) + 1
        return {
            "source": "live", "summary": self.summary(fire), "pass_index": upto, "pass_time": iso(passes.starts[upto]),
            "detections": [{"position": [round(float(x), 5), round(float(y), 5)], "pass_index": int(p),
                            "frp_mw": round(float(v), 1)}
                           for x, y, p, v in zip(lon, lat, self.pass_of[keep], self.frp[keep], strict=True)],
            "outline": _outline(lon, lat), "scar": _drawn_footprint(lon, lat),
            "core": _drawn_footprint(self.lon[core], self.lat[core]), "spread": self.spread(fire, upto), "weather": None,
            "detections_by_day": days, "attribution": ATTRIBUTION,
            "timezone": geometry_zone(shapely.Point(fire.lon, fire.lat)),
        }


def _cell_keys(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    return (np.round(lat / AREA_CELL_DEG[1]).astype(np.int64) + 100_000) * 1_000_000 \
        + np.round(lon / AREA_CELL_DEG[0]).astype(np.int64) + 500_000


def _area_ha(live: Live, idx: np.ndarray) -> int:
    return int(len(np.unique(_cell_keys(live.lon[idx], live.lat[idx]))) * AREA_CELL_HA)


def _outline(lon: np.ndarray, lat: np.ndarray) -> list | None:
    if len(lon) == 0:
        return None
    pad = OUTLINE_PAD_DEG
    corners = [(x + dx, y + dy) for x, y in zip(lon.tolist(), lat.tolist(), strict=True)
               for dx in (-pad, pad) for dy in (-pad, pad)]
    hull = shapely.MultiPoint(corners).convex_hull
    return [[round(x, 5), round(y, 5)] for x, y in hull.exterior.coords] if hull.geom_type == "Polygon" else None


CLOSING_M = 190.0  # drawing only: cells closer than twice this are one patch, holes narrower than that are filled
ROUNDING_M = 60.0  # drawing only: convex corners of the patch are rounded to this radius
DRAWING_SIMPLIFY_M = 30.0
M_PER_DEG = 111_320.0


def _cell_union(lon: np.ndarray, lat: np.ndarray) -> shapely.Geometry:
    """The area cells of the detections joined: the burning ground as counted. Nothing smoothed."""
    dx, dy = AREA_CELL_DEG[0] / 2, AREA_CELL_DEG[1] / 2
    return shapely.union_all(shapely.box(lon - dx, lat - dy, lon + dx, lat + dy))


def _drawn_footprint(lon: np.ndarray, lat: np.ndarray, closing_m: float = CLOSING_M) -> list | None:
    """Footprint for the map ONLY, as polygons: the cells closed in metres (buffer out and back, round joins), the
    corners rounded, lightly simplified. It is larger than the cells; areas, growth, the planner and its safe ground
    are counted on `_cell_union` and the detections, never on this."""
    if len(lon) == 0:
        return None
    lon0, lat0 = float(lon.mean()), float(lat.mean())
    kx = M_PER_DEG * math.cos(math.radians(lat0))
    cells = shapely.transform(_cell_union(lon, lat), lambda c: (c - [lon0, lat0]) * [kx, M_PER_DEG])
    drawn = cells.buffer(closing_m, 8).buffer(-closing_m, 8)
    drawn = drawn.buffer(-ROUNDING_M, 8).buffer(ROUNDING_M, 8).simplify(DRAWING_SIMPLIFY_M)
    if drawn.is_empty:
        drawn = cells
    drawn = shapely.transform(drawn, lambda c: c / [kx, M_PER_DEG] + [lon0, lat0])
    geometry = areas.to_geojson(drawn, 5)
    return [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]


def load_frame(store: Store) -> pl.DataFrame | None:
    """VIIRS detections (not low confidence) of the last days that have rows on disk."""
    root = store.root / "rows"
    start_year = store.last_complete_date.year
    files = [str(root / f"year={y}" / "*" / "*.parquet") for y in (start_year - 1, start_year)
             if (root / f"year={y}").exists()]
    if not files:
        return None
    lf = pl.scan_parquet(files).filter(pl.col("sensor").str.starts_with("viirs") & (pl.col("confidence") != "l"))
    recent = lf.filter(pl.col("local_date") >= store.last_complete_date - timedelta(days=7))
    last = recent.select(pl.col("local_date").max()).collect().item()
    if last is None:
        return None
    return lf.filter(pl.col("local_date") >= last - timedelta(days=WINDOW_DAYS - 1)) \
        .select("lat", "lon", "acq_utc", "local_date", "frp_mw").collect()


def live_of(store: Store) -> Live:
    return store.once("live", lambda: Live(store, load_frame(store)))


def fires_now(store: Store, region, demo: bool = False) -> int:
    return 0 if demo else live_of(store).count(region.id)


# --- fires of an archive day ---


@dataclass
class DayClusters:
    day: np.ndarray  # days since 1970-01-01
    lon: np.ndarray
    lat: np.ndarray
    first_ms: np.ndarray
    detections: np.ndarray
    raw: np.ndarray
    frp: np.ndarray
    viirs: np.ndarray  # bool

    def __len__(self) -> int:
        return len(self.day)


_DAY_COLUMNS = ["lat", "lon", "acq_utc", "local_date", "sensor", "frp_mw", "confidence", "daynight"]


def day_clusters(store: Store, area: areas.Area, start: date, end: date) -> DayClusters:
    """Fires of each local date: the area's detections joined within their own day, in the scale of VIIRS."""
    frames = [df for df in export._chunks(store, area, start, end, _DAY_COLUMNS) if len(df)]
    if not frames:
        return DayClusters(*(np.zeros(0) for _ in range(7)), viirs=np.zeros(0, dtype=bool))  # type: ignore[call-arg]
    df = pl.concat(frames)
    lon, lat = df["lon"].to_numpy().astype(float), df["lat"].to_numpy().astype(float)
    day = df["local_date"].cast(pl.Int32).to_numpy().astype(np.int64)
    label = link(lon, lat, day)
    k = np.array([float(x) if x else 1.0 for x in export._weights(store, df)])
    n = int(label.max()) + 1
    count = np.bincount(label, minlength=n)
    first = np.full(n, np.iinfo(np.int64).max, dtype=np.int64)
    ms = df["acq_utc"].dt.epoch("ms").to_numpy().astype(np.int64)
    np.minimum.at(first, label, ms)
    sensor_viirs = np.char.startswith(df["sensor"].to_numpy().astype(str), "viirs")
    rep = np.zeros(n, dtype=np.int64)
    rep[label] = np.arange(len(label))
    return DayClusters(
        day=day[rep], lon=np.bincount(label, weights=lon, minlength=n) / count,
        lat=np.bincount(label, weights=lat, minlength=n) / count, first_ms=first,
        detections=np.bincount(label, weights=k, minlength=n), raw=count,
        frp=np.bincount(label, weights=np.nan_to_num(df["frp_mw"].to_numpy().astype(float)), minlength=n),
        viirs=np.bincount(label, weights=sensor_viirs, minlength=n) > 0)


EPOCH = date(1970, 1, 1).toordinal()


def cluster_counts(clusters: DayClusters) -> dict[date, int]:
    days, counts = np.unique(clusters.day, return_counts=True)
    return {date.fromordinal(EPOCH + int(d)): int(c) for d, c in zip(days, counts, strict=True)}
