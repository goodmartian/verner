"""`/api/world/countries`: yearly and seasonal statistics of countries from the same calendar numbers as `calendar.build`.

Monthly counts of a country are
the harmonized H matrix weighted by the country's cell weights (the calendar of that country), so a country has
one set of numbers everywhere.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from . import areas
from .errors import ApiError
from .months import BASE_FIRST_YEAR
from .regions import geometry_zone, region_index, zone_of
from .store import Store
from .weights import cell_weights, weighted_sum

MIN_AVERAGE_FOR_COMPARISON = 1.0
SOURCE = "NASA FIRMS MODIS and VIIRS, harmonized by Verner"


@dataclass
class CountryStats:
    monthly: np.ndarray  # years * 12
    yearly: np.ndarray
    average: float
    seasonal: np.ndarray
    peak_month: int
    last_year_total: float
    trend_ratio: float | None


class World:
    def __init__(self, store: Store):
        self.store = store
        self.first_year = max(-(-store.first_month // 12) + 2000, BASE_FIRST_YEAR)  # the baseline years only
        self.start = (self.first_year - 2000) * 12
        cur_year = store.cur_month // 12 + 2000
        self.last_year = cur_year - 1  # complete years of the record
        self.years = self.last_year - self.first_year + 1
        self._stats: dict[str, CountryStats] = {}
        self._lock = threading.Lock()

    def country_ids(self) -> list[str]:
        return [r.id for r in self.store.regions.records if r.kind == "country"]

    def stats(self, rid: str) -> CountryStats:
        found = self._stats.get(rid)
        if found is not None:
            return found
        with self._lock:
            found = self._stats.get(rid)
            if found is None:
                found = self._stats[rid] = self._compute(rid)
        return found

    def _compute(self, rid: str) -> CountryStats:
        s = self.store
        area = areas.parse({"id": rid}, s)
        start = self.start
        try:
            idx, w = cell_weights(s, area)
            monthly = np.rint(weighted_sum(s.H, idx, w)[start:start + self.years * 12])
        except ApiError as err:
            if err.code != "no_land":  # a country too small to hold a cell has no record
                raise
            monthly = np.zeros(self.years * 12)
        grid = monthly.reshape(self.years, 12)
        yearly = grid.sum(axis=1)
        average = float(yearly.mean())
        seasonal = grid.mean(axis=0)
        first5 = float(yearly[:5].mean())
        trend = float(yearly[-5:].mean()) / first5 if first5 > 0 else None
        return CountryStats(monthly, yearly, average, seasonal, int(np.argmax(seasonal)) + 1, float(yearly[-1]), trend)

    def with_record(self) -> list[str]:
        return [rid for rid in self.country_ids() if self.stats(rid).average >= MIN_AVERAGE_FOR_COMPARISON]

    def cells(self, rid: str, year: int | None) -> list[dict]:
        """0.25 degree cells of the country gathered into 1 degree cells, smallest value first."""
        s = self.store
        idx, w = cell_weights(s, areas.parse({"id": rid}, s))
        if year is None:
            cols = slice(self.start, self.start + self.years * 12)
            per_cell = np.asarray(s.H[idx][:, cols].sum(axis=1)).ravel() / self.years
        else:
            c0 = self.start + (year - self.first_year) * 12
            per_cell = np.asarray(s.H[idx][:, c0:c0 + 12].sum(axis=1)).ravel()
        per_cell = per_cell * w
        lat, lon = s.cells.lat[idx], s.cells.lon[idx]
        gy, gx = np.floor(lat).astype(int), np.floor(lon).astype(int)
        keys = (gy + 90) * 360 + (gx + 180)
        uniq, inv = np.unique(keys, return_inverse=True)
        sums = np.bincount(inv, weights=per_cell)
        keep = sums >= 1
        out = sorted(((int(k), float(v)) for k, v in zip(uniq[keep], sums[keep], strict=True)), key=lambda t: t[1])
        return [{"lon": float(k % 360 - 180 + 0.5), "lat": float(k // 360 - 90 + 0.5), "value": v} for k, v in out]

    def answer(self, rid: str, years: list[int], cells_year: int | None, with_map: bool) -> dict:
        s = self.store
        region = s.regions.by_id[rid]
        st = self.stats(rid)
        details = []
        for y in years:
            j = y - self.first_year
            months = st.monthly[j * 12:j * 12 + 12]
            total = float(st.yearly[j])
            details.append({"year": y, "total": total, "vs_average": total / st.average if st.average > 0 else None,
                            "peak_month": int(np.argmax(months)) + 1, "monthly": [float(v) for v in months]})
        return {
            "id": rid, "timezone": zone_of(region), "covered": True, "names": region_index(s).names[rid],
            "area_km2": round(region.area_km2), "average_per_year": st.average,
            "density_per_1000_km2": st.average / region.area_km2 * 1000 if region.area_km2 > 0 else 0.0,
            "peak_month": st.peak_month, "last_year_total": st.last_year_total, "trend_ratio": st.trend_ratio,
            "yearly": [{"year": self.first_year + j, "total": float(v)} for j, v in enumerate(st.yearly)],
            "seasonal": [float(v) for v in st.seasonal], "years": details,
            "bbox": region.bbox if with_map else None,
            "geometry": _geojson(region.geometry) if with_map else None,
            "cells": self.cells(rid, cells_year) if with_map else None,
        }

    def countries(self, ids: list[str] | None, years: list[int] | None, attribution: str | None) -> dict:
        valid = [y for y in (years or []) if self.first_year <= y <= self.last_year]
        missing = [y for y in (years or []) if y not in valid]
        detail = sorted(set(valid)) if valid else ([self.last_year] if years else [])
        cells_year = detail[-1] if (detail and ids is not None) else None
        chosen = self.with_record() if ids is None else ids
        answers = [self.answer(rid, detail, cells_year, ids is not None) for rid in chosen]
        return {
            "first_year": self.first_year, "last_year": self.last_year, "source": SOURCE, "countries": answers,
            "missing_years": missing, "cells_year": cells_year,
            "comparison": _comparison(answers) if not detail else None,
            "year_comparison": _year_comparison(answers) if len(detail) == 1 else None,
            "attribution": attribution,
        }


def _geojson(geometry) -> dict:
    return areas.to_geojson(geometry)


def _comparison(answers: list[dict]) -> dict | None:
    if len(answers) < 2:
        return None
    by_total = sorted(answers, key=lambda a: -a["average_per_year"])
    largest, smallest = by_total[0], by_total[-1]
    if smallest["average_per_year"] < MIN_AVERAGE_FOR_COMPARISON:
        return None
    by_density = sorted(answers, key=lambda a: -a["density_per_1000_km2"])
    densest, sparsest = by_density[0], by_density[-1]
    return {"largest": largest["id"], "smallest": smallest["id"],
            "ratio": largest["average_per_year"] / smallest["average_per_year"], "densest": densest["id"],
            "sparsest": sparsest["id"],
            "density_ratio": densest["density_per_1000_km2"] / max(1e-9, sparsest["density_per_1000_km2"])}


def _year_comparison(answers: list[dict]) -> dict | None:
    if len(answers) < 2:
        return None
    ranked = sorted(answers, key=lambda a: -a["years"][0]["total"])
    largest, smallest = ranked[0], ranked[-1]
    if smallest["years"][0]["total"] < MIN_AVERAGE_FOR_COMPARISON or largest is smallest:
        return None
    return {"largest": largest["id"], "smallest": smallest["id"],
            "ratio": largest["years"][0]["total"] / smallest["years"][0]["total"]}


def world_of(store: Store) -> World:
    return store.once("world", lambda: World(store))


__all__ = ["World", "geometry_zone", "world_of"]
