"""Answers of the calendar routes built from the period statistics of `Ser`: provinces, month detail, cell map and days."""

from __future__ import annotations

from datetime import date

import numpy as np

from . import areas, cells, daily, fires
from .calendar import Ser, series_of
from .errors import ApiError
from .months import BASE_FIRST_MONTH, BASE_FIRST_YEAR, month_end, month_start, parse_month
from .regions import geometry_zone, region_index
from .store import Store
from .weights import cell_weights

TOP_PROVINCES = 3
ATTRIBUTION = "Fire detections: NASA FIRMS (MODIS and VIIRS), harmonized by Verner."


def resolve_period(ser: Ser, from_: str | None, to: str | None) -> tuple[int, int]:
    """The months asked for as indices; what is left out defaults to the forecast (or the last twelve seen
    months), and a first month alone is that one month."""
    first, last = ser.default_period()
    if from_ is not None:
        first = ser.index_of(from_, "from")
    if to is not None:
        last = ser.index_of(to, "to")
    elif from_ is not None:
        last = first
    return first, last


def _local_names(store: Store, rid: str) -> dict:
    names = region_index(store).names[rid]
    return {"en": names["en"], "ru": names["ru"], "es": names["es"], **({"fr": names["fr"]} if "fr" in names else {})}


def _provinces_of(store: Store, country_id: str):
    return [r for r in store.regions.records if r.kind != "country" and r.country_id == country_id]


def _province_series(store: Store, region) -> Ser | None:
    try:
        return series_of(store, areas.parse({"id": region.id}, store))
    except ApiError as err:
        if err.code == "no_land":
            return None
        raise


def provinces(store: Store, country: areas.Area, ser: Ser, first: int, last: int, sort: str) -> dict:
    ser.check_range(first, last, ahead=True)
    whole = first <= max(0, BASE_FIRST_MONTH - ser.first_abs) and last >= ser.last_index  # the baseline years at least
    rows = []
    for region in _provinces_of(store, country.id or ""):
        own = _province_series(store, region)
        if own is None:
            continue
        try:
            points = own.points(first, last)
        except ApiError:  # this province has no forecast
            continue
        total = float(sum(p["value"] for p in points))
        normal = float(sum(p["normal"] for p in points))
        rows.append({"id": region.id, "names": _local_names(store, region.id), "total": total, "normal": normal,
                     "ratio": total / normal if normal > 0 else None, "share": 0.0,
                     "year_normal": float(own.normal.sum())})
    everything = float(sum(r["total"] for r in rows))
    for row in rows:
        row["share"] = row["total"] / max(1.0, everything)
    if sort == "name":
        rows.sort(key=lambda r: r["names"]["es"].casefold())
    elif sort == "ratio" and not whole:
        rows.sort(key=lambda r: -((r["ratio"] or 1) - 1 if r["normal"] > 0 else 0))
    else:
        rows.sort(key=lambda r: -r["total"])
    return {"first_month": ser.month_name(first), "last_month": ser.month_name(last), "approximate": last > ser.reach,
            "whole": whole, "sort": sort, "total": everything, "rows": rows, "attribution": ATTRIBUTION}


def month(store: Store, area: areas.Area, ser: Ser, label: str) -> dict:
    index = ser.index_of(label, "month")
    ser.check_range(index, index, ahead=True)
    number = (ser.first_abs + index) % 12
    years = [{"year": (ser.first_abs + other) // 12 + 2000, "month": ser.month_name(other), "kind": "seen",
              "value": ser.value_at(other), "low": None, "high": None}
             for other in range(index % 12, ser.reach + 1, 12)]
    ahead = ser.forecast_at(index)
    if ahead is not None:
        years.append({"year": (ser.first_abs + index) // 12 + 2000, "month": label, "kind": "forecast",
                      "value": ahead["median"], "low": ahead["low"], "high": ahead["high"]})
    value = ser.value_at(index)
    normal = ser.normal_at(index)
    # the place among the baseline years, and the month itself when it lies before them
    column = [y["value"] for y in years if y["year"] >= BASE_FIRST_YEAR or y["month"] == label]
    rank = None if ahead else {"place": sorted(column, reverse=True).index(value) + 1, "of": len(column)}
    if index == ser.reach and ser.to_date["rank"] is not None:  # the running month is ranked by the same dates
        rank = {"place": ser.to_date["rank"], "of": ser.to_date["of"]}
    top: list[dict] = []
    share = None
    kind = kind_of(store, area)
    if ahead is not None:
        pass
    elif kind == "country":
        found = []
        for region in _provinces_of(store, area.id or ""):
            own = _province_series(store, region)
            if own is not None:
                found.append((region.id, own.value_at(index)))
        found.sort(key=lambda item: -item[1])
        top = [{"id": pid, "names": _local_names(store, pid), "value": v} for pid, v in found[:TOP_PROVINCES] if v >= 1]
    elif kind == "province" and area.id:
        parent = store.regions.by_id[store.regions.by_id[area.id].country_id]
        country = series_of(store, areas.parse({"id": parent.id}, store))
        share = value / max(1.0, country.value_at(index))
    return {"area": info(store, area, ser), "month": label, "calendar_month": number + 1,
            "kind": "forecast" if ahead else "seen",
            "value": value, "normal": normal, "ratio": value / normal if normal > 0 else None, "rank": rank,
            "years": years, "top_provinces": top, "share_of_country": share,
            "forecast": None if ahead is None else {"low": ahead["low"], "high": ahead["high"], "normal": normal,
                                                      "rain_vs_normal": None, "factors": []},
            "attribution": ATTRIBUTION}


def _forecast_cells(store: Store, area: areas.Area, ser: Ser, index: int) -> list[dict]:
    """Cells with the median over the baseline years of their own calendar month, weighted as in the area."""
    idx, w = cell_weights(store, area)
    number = (ser.first_abs + index) % 12
    columns = [(y - 2000) * 12 + number for y in store.base_years]
    base = np.asarray(store.H[idx][:, columns].toarray()) * w[:, None]
    median = np.median(base, axis=1)
    keep = np.nonzero(median >= 0.5)[0]
    top = max(1.0, float(median[keep].max()) if len(keep) else 0.0)
    order = keep[np.argsort(median[keep], kind="stable")]
    cell = store.cells
    return [{"type": "Feature", "properties": {"v": float(median[i]), "w": float(median[i]) / top},
             "geometry": {"type": "Point", "coordinates": [round(float(cell.lon[idx[i]]), 4),
                                                           round(float(cell.lat[idx[i]]), 4)]}} for i in order]


def cell_map(store: Store, area: areas.Area, ser: Ser, label: str) -> dict:
    index = ser.index_of(label, "month")
    ser.check_range(index, index, ahead=True)
    if index > ser.reach:
        return {"type": "FeatureCollection", "month": label, "kind": "forecast", "attribution": ATTRIBUTION,
                "features": _forecast_cells(store, area, ser, index)}
    found = [c for c in cells.month_cells(store, area, label)["cells"] if c["count"] > 0]
    found.sort(key=lambda c: c["count"])
    return {"type": "FeatureCollection", "month": label, "kind": "seen", "attribution": ATTRIBUTION,
            "features": [{"type": "Feature", "properties": {"v": float(c["count"]), "w": None},
                          "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]}} for c in found]}


def days(store: Store, area: areas.Area, label: str) -> dict:
    m = parse_month(label, "month")
    if m is None or m < store.first_month:
        raise ApiError(422, "period_out_of_range", f"Month {label} is outside the data")
    idx, w = cell_weights(store, area)
    start: date = month_start(m)
    end: date = min(month_end(m), store.last_complete_date)  # a month after the data has no days
    harmonized = daily.by_day(store, idx, w, start, end) if end >= start else {}
    groups = fires.cluster_counts(fires.day_clusters(store, area, start, end)) if end >= start else {}
    rows = [{"date": d.isoformat(), "clusters": groups.get(d, 0), "detections": float(v)} for d, v in sorted(harmonized.items())]
    return {"month": label, "area": area.id or "drawn",
            "coverage": {"first_day": month_start(store.first_month).isoformat(),
                         "last_day": store.last_complete_date.isoformat()},
            "days": rows, "attribution": ATTRIBUTION}


def kind_of(store: Store, area: areas.Area) -> str:
    if area.id == areas.WORLD_ID:
        return "world"
    if area.id is None:
        return "drawn"
    region = store.regions.by_id.get(area.id)
    return "country" if region is not None and region.kind == "country" else "province"


def info(store: Store, area: areas.Area, ser: Ser | None = None) -> dict:
    """AreaInfo of an area."""
    ser = ser or series_of(store, area)
    return {"id": area.id or "drawn", "kind": kind_of(store, area), "bbox": area.bbox,
            "timezone": geometry_zone(area.geometry), "covered": True, "forecast_available": ser.forecast_available}
