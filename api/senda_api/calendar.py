"""Calendar of an area: the monthly record (`Ser`) with its normals and forecast, and the
board answer built from it: series, normals, yearly totals, season, quality, forecast, blind check, presets.

Months are absolute numbers (month 0 = 2000-01) in the store and indices from the first archive month in `Ser`.
Only complete months count as seen; the current month is running; the months after it are the forecast.
"""

from __future__ import annotations

import math
from functools import cached_property

import numpy as np
import polars as pl

from . import daily, forecasts, quality, seam, season
from .areas import Area, to_geojson
from .errors import ApiError
from .levels import level_of, ratio_level
from .months import BASE_FIRST_MONTH, BASE_FIRST_YEAR, month_label, month_start, parse_month, round_int
from .store import MODIS_SENSORS, SENSORS, Store
from .weights import cell_weights, weighted_sum

MAX_SERIES_MONTHS = 1200
FORECAST_MONTHS = 6  # how far ahead the climatological forecast goes
MIN_FORECAST_YEARS = 3  # base years with fires that a forecast needs
FIT_YEARS = (2012, 2019)  # the "forward" scenario of the harmonization: fit on these years,
BLIND_YEARS = (2020, 2021)  # check on these


def js_round(value: float) -> int:
    return math.floor(value + 0.5)


def resolve_period(store: Store, from_: str | None, to: str | None) -> tuple[int, int]:
    """Requested first and last month (absolute numbers). Months before the archive are clipped away."""
    first, last = parse_month(from_, "from"), parse_month(to, "to")
    if first is not None and last is not None and first > last:
        raise ApiError(400, "invalid_period", "from must not be after to")
    first = store.first_month if first is None else max(first, store.first_month)
    last = store.cur_month if last is None else last
    if last < first:
        raise ApiError(400, "invalid_period", "The period lies outside the archive")
    if last - first + 1 > MAX_SERIES_MONTHS:
        raise ApiError(400, "invalid_period", f"The period is longer than {MAX_SERIES_MONTHS} months")
    return first, last


def _normals(counts: np.ndarray, base_years: list[int]) -> tuple[np.ndarray, list[dict], list[int | None]]:
    """Per calendar month: baseline values (years x 12), the 12 normals entries and exact medians."""
    values = np.array([counts[(y - 2000) * 12:(y - 2000) * 12 + 12] for y in base_years], dtype=np.int64).reshape(-1, 12)
    entries, medians = [], []
    for moy in range(12):
        col = values[:, moy]
        n = len(col)
        median = round_int(np.median(col)) if n >= daily.MIN_BASE_YEARS else None
        medians.append(median)
        entries.append({
            "month": moy + 1,
            "median": median,
            "mean": round_int(col.mean()) if n else None,
            "p10": round_int(np.percentile(col, 10)) if n else None,
            "p90": round_int(np.percentile(col, 90)) if n else None,
            "years": n,
        })
    return values, entries, medians


class Ser:
    """One area's monthly record over the complete months of the archive and the normal of each calendar month."""

    def __init__(self, store: Store, area: Area):
        self.store = store
        self.area = area
        self.idx, self.w = cell_weights(store, area)
        self.cells = len(self.idx)
        self.counts = np.rint(weighted_sum(store.H, self.idx, self.w)).astype(np.int64)  # every month, running included
        self.values, self.entries, self.medians = _normals(self.counts, store.base_years)  # values: base years x 12
        self.normal = np.array([float(m) if m is not None else 0.0 for m in self.medians])
        self.has_normal = [m is not None for m in self.medians]
        last = store.cur_month - 1  # the current month is not finished
        self.first_abs = store.first_month
        self.monthly = self.counts[store.first_month:last + 1].astype(np.float64)
        self.partial = float(self.counts[store.cur_month])  # the running month, not finished
        self.reach = store.cur_month - store.first_month  # its index
        self.first_year = store.first_month // 12 + 2000

    # --- what the board needs besides the counts ---

    @cached_property
    def frp(self) -> np.ndarray:
        return weighted_sum(self.store.FRP, self.idx, self.w)

    @cached_property
    def converted(self) -> np.ndarray:
        """True where the month holds fires of the MODIS series (converted to the VIIRS scale)."""
        return sum(weighted_sum(self.store.SER[s], self.idx, self.w) for s in MODIS_SENSORS) > 1e-9

    @cached_property
    def raw(self) -> dict[str, np.ndarray]:
        return {s: weighted_sum(self.store.RAW[s], self.idx, self.w) for s in SENSORS}

    @cached_property
    def quality(self) -> dict:
        return {**quality.for_area(self.store, self.idx, self.w, area_id=self.area.id),
                "seam": seam.slice_for(self.store, self.area.id, self.idx, self.w)}

    @cached_property
    def to_date(self) -> dict:
        """The running month against the same dates of the baseline years."""
        store = self.store
        through = store.last_complete_date
        got = daily.same_dates(store, self.idx, self.w, month_start(store.cur_month), through)
        return {"through": through.isoformat(), "count": got["count"], "median": got["median"], "ratio": got["ratio"],
                "rank": got["rank"], "of": got["of"]}

    @cached_property
    def blind_check(self) -> dict | None:
        """The conversion checked blind: MODIS counts converted to the VIIRS scale with the factors fitted on
        2012-2019 (the model) and unconverted MODIS counts (the plain method) against the VIIRS count of
        2020-2021, and the calendar normal. The normal uses every baseline year, so it is the harder baseline."""
        store = self.store
        first, last = (BLIND_YEARS[0] - 2000) * 12, (BLIND_YEARS[1] - 2000) * 12 + 11
        months = [m for m in range(first, last + 1) if m not in store.incomplete and m <= store.cur_month]
        real = self.raw["viirs_snpp"][months]
        if not months or real.sum() <= 0:
            return None
        model = _converted_modis(store, self.idx, self.w, first, last)[np.array(months) - first]
        plain = self.raw["modis_aqua"][months]
        normal = np.array([self.normal[m % 12] for m in months])
        years = np.array([m // 12 + 2000 for m in months])
        return {
            "fit_years": {"first": FIT_YEARS[0], "last": FIT_YEARS[1]},
            "blind_years": {"first": BLIND_YEARS[0], "last": BLIND_YEARS[1]},
            "months": [{"month": month_label(m), "real": float(r), "model": float(v), "normal": float(n)}
                       for m, r, v, n in zip(months, real, model, normal, strict=True)],
            "climatology": _score(real, normal, normal, years),
            "poisson": _score(real, model, normal, years),
            "boosting": _score(real, plain, normal, years),
        }

    # --- forecast: the model where it passed its check, else the median of the same calendar month over the baseline years ---

    @cached_property
    def model(self) -> forecasts.ModelForecast | None:
        """The model forecast, when this area has rows of its own in it: the model was checked on the area and beat the
        median. An area without rows (a drawn one, a small region, one the model did not beat the median on) has the
        median."""
        found = self.store.forecast
        return found if found is not None and self.area.id in found.rows else None

    def month_label(self, index: int) -> str:
        return month_label(self.first_abs + index)

    def climatology_error(self, index: int) -> float | None:
        """Error of the median forecast of a month in percent: in the check of the model at that horizon, where the area
        was checked; else the leave-one-year-out error of the yearly total."""
        found = self.store.forecast
        if found is not None and self.area.id is not None:
            error = found.base_error(self.area.id, self.first_abs + index - found.trained_through)
            if error is not None:
                return error
        return None if self.accuracy is None else round(100 * self.accuracy["year_error"], 1)

    @property
    def forecast_available(self) -> bool:
        return (bool((self.values.sum(axis=1) > 0).sum() >= MIN_FORECAST_YEARS) and all(self.has_normal)
                and float(self.normal.sum()) > 0)

    @property
    def forecast_first(self) -> int:
        return self.reach + 1

    @property
    def forecast_last(self) -> int:
        return self.reach + FORECAST_MONTHS if self.forecast_available else self.reach

    def forecast_at(self, index: int) -> dict | None:
        """Median and the 10th and 90th percentile of the calendar month of `index`, for a month ahead."""
        if not self.forecast_first <= index <= self.forecast_last:
            return None
        entry = self.entries[(self.first_abs + index) % 12]
        own = {"median": float(entry["median"]), "low": float(entry["p10"]), "high": float(entry["p90"])}
        found = None if self.model is None else self.model.rows[self.area.id].get(self.month_label(index))
        if found is not None:
            found = {"median": found["p50"], "low": found["p10"], "high": found["p90"], "err_pct": found["err_pct"]}
            return {**{k: found[k] for k in own}, "method": "model", "err_pct": found["err_pct"]}
        return {**own, "method": "climatology", "err_pct": self.climatology_error(index)}

    def forecast_info(self) -> dict:
        """How the forecast of the answer was made: the horizons the model serves here, when it was trained, and a line;
        `model` is what the model says for the area and how it was checked there (for the assistant; the board's schema
        leaves it out)."""
        ahead = [self.forecast_at(i) for i in range(self.forecast_first, self.forecast_last + 1)]
        months = sum(p["method"] == "model" for p in ahead if p is not None)
        found = self.store.forecast
        src, doc = self.model, None if found is None else found.doc
        basis = "model" if months else "climatology"
        return {"model_horizons": 0 if src is None else src.months(self.area.id), "model_months": months, "basis": basis,
                "trained_at": None if doc is None or src is None else doc.get("trained_at"),
                "trained_through": None if doc is None or src is None else doc.get("trained_through"),
                "model": None if found is None else found.summary(self.area.id)}

    @cached_property
    def accuracy(self) -> dict | None:
        """Leave-one-year-out check of the forecast: each baseline year against the median of the other years."""
        if not self.forecast_available or len(self.values) < MIN_FORECAST_YEARS + 1:
            return None
        guess = np.array([np.median(np.delete(self.values, k, axis=0), axis=0) for k in range(len(self.values))])
        real = self.values.astype(float)
        yearly = float(np.abs(guess.sum(axis=1) - real.sum(axis=1)).sum() / max(1.0, real.sum()))
        monthly = float(np.mean(np.abs(np.log1p(guess) - np.log1p(real))))
        span = {"first": int(min(self.store.base_years)), "last": int(max(self.store.base_years))}
        return {"fit_years": span, "blind_years": span, "year_error": yearly, "normal_year_error": yearly,
                "month_log_error": monthly, "normal_month_log_error": monthly, "month_improvement": 0.0}

    # --- names and indices ---

    @property
    def months(self) -> int:
        return len(self.monthly)

    @property
    def last_index(self) -> int:
        return self.months - 1

    @property
    def last_full_year(self) -> int:
        """The last year with all twelve months seen."""
        end = self.first_abs + self.months  # one past the last seen month
        return end // 12 + 2000 - 1

    def month_name(self, index: int) -> str:
        return month_label(self.first_abs + index)

    def index_of(self, label: str, name: str = "month") -> int:
        m = parse_month(label, name)
        if m is None:
            raise ApiError(400, "invalid_period", f"{name} is required")
        return m - self.first_abs

    def check_range(self, first: int, last: int, running: bool = False, ahead: bool = False) -> None:
        """Both months must be inside the data; `running` also admits the unfinished current month and `ahead`
        the months of the forecast."""
        if first > last:
            raise ApiError(422, "period_out_of_range", "The start of the period is after its end")
        top = self.forecast_last if ahead else self.reach if running else self.last_index
        for index in (first, last):
            if not 0 <= index <= top:
                raise ApiError(422, "period_out_of_range", f"Month {self.month_name(max(0, index))} is outside the data")

    def default_period(self) -> tuple[int, int]:
        """The forecast where there is one, otherwise the last twelve seen months."""
        if self.forecast_available:
            return self.forecast_first, self.forecast_last
        return max(0, self.months - 12), self.months - 1

    def value_at(self, index: int) -> float:
        """Count of a seen month (the running month included) or the median of a month ahead."""
        if index == self.reach:
            return self.partial
        if index > self.reach:
            ahead = self.forecast_at(index)
            if ahead is None:
                raise ApiError(422, "period_out_of_range", f"Month {self.month_name(index)} is outside the data")
            return ahead["median"]
        return float(self.monthly[index])

    def level(self, value: float, month_number: int) -> int | None:
        median = int(self.normal[month_number]) if self.has_normal[month_number] else None
        return ratio_level(int(value), median)[1]

    # --- statistics ---

    def normal_at(self, index: int) -> float:
        """What is usual for a month; for the running one, the usual count of the same dates of the past years."""
        if index == self.reach:
            return float(self.to_date["median"] or 0.0)
        return float(self.normal[(self.first_abs + index) % 12])

    def points(self, first: int, last: int) -> list[dict]:
        return [{"index": i, "value": self.value_at(i), "normal": self.normal_at(i)} for i in range(first, last + 1)]

    def yearly_totals(self) -> list[float]:
        """Totals of the full calendar years from the first baseline year on."""
        start = max(BASE_FIRST_MONTH, -(-self.first_abs // 12) * 12) - self.first_abs
        seen = self.monthly[start:]
        full = len(seen) // 12 * 12
        return [float(v) for v in seen[:full].reshape(-1, 12).sum(axis=1)]

    def trend_percent(self) -> int | None:
        """Slope of a straight line through the last ten full-year totals, as a share of their mean."""
        yearly = self.yearly_totals()[-10:]
        if len(yearly) < 10:
            return None
        mean = sum(yearly) / 10
        if mean < 1:
            return None
        centred = [k - 4.5 for k in range(10)]
        slope = sum(c * (y - mean) for c, y in zip(centred, yearly, strict=True)) / sum(c * c for c in centred)
        return js_round(slope / mean * 100)

    @cached_property
    def trend(self) -> dict | None:
        percent = self.trend_percent()
        last = self.last_full_year
        return None if percent is None else {"first_year": last - 9, "last_year": last, "percent_per_year": percent}

    def preset_items(self) -> list[dict]:
        """Periods worth offering: the last three full years, then the forecast.

        No fixed "season": October to March is the season of no area in particular, and the board knows each one's own.
        """
        last = self.last_full_year
        items = [{"id": str(y), "kind": "year", "first_month": f"{y}-01", "last_month": f"{y}-12"}
                 for y in (last, last - 1, last - 2) if y >= self.first_year]
        if self.forecast_available:
            items.append({"id": "forecast", "kind": "forecast", "first_month": self.month_name(self.forecast_first),
                          "last_month": self.month_name(self.forecast_last)})
        return items


_LIMIT = 48


def series_of(store: Store, area: Area) -> Ser:
    return store.lru("series", (area.id or area.slug, round(area.area_km2, 3)), lambda: Ser(store, area), _LIMIT)


def _score(real: np.ndarray, model: np.ndarray, normal: np.ndarray, years: np.ndarray) -> dict:
    """Errors of a prediction of the monthly counts against the real ones."""
    log_error = float(np.mean(np.abs(np.log1p(model) - np.log1p(real))))
    yearly = []
    for year in np.unique(years):
        sel = years == year
        total = real[sel].sum()
        if total > 0:
            yearly.append(abs(model[sel].sum() - total) / total)
    side = np.sign(real - normal)
    guess = np.sign(model - normal)
    decided = (side != 0) & (guess != 0)
    samples = int(decided.sum())
    return {"month_log_error": log_error, "year_error": float(np.mean(yearly)) if yearly else 0.0,
            "direction_accuracy": float((side[decided] == guess[decided]).mean()) if samples else 0.0,
            "direction_samples": samples}


def _converted_modis(store: Store, idx: np.ndarray, w: np.ndarray, first: int, last: int) -> np.ndarray:
    """Weighted MODIS counts of the months first..last converted to the VIIRS scale with the factors of the
    harmonization (the same lookup that builds H), one value per month. MODIS stays in H only before 2012."""
    n_rows = len(store.cells.cell_id)
    few = len(idx) < min(daily.CELL_FILTER_LIMIT, n_rows)
    lf = pl.scan_parquet(store.root / "monthly.parquet").filter(
        (pl.col("sensor") == "modis_aqua") & pl.col("month").is_between(first, last))
    if few:
        lf = lf.filter(pl.col("cell_id").is_in(store.cells.cell_id[idx].tolist()))
    df = lf.select("cell_id", "month", "n_day", "n_night").collect()
    out = np.zeros(last - first + 1)
    if df.is_empty():
        return out
    rows = store.cells.row_of[df["cell_id"].to_numpy()].astype(np.int64)
    weight = np.zeros(n_rows)
    weight[idx] = w
    keep = rows >= 0
    rows = rows[keep]
    months = df["month"].to_numpy()[keep].astype(np.int64)
    n_day = df["n_day"].to_numpy()[keep]
    n_night = df["n_night"].to_numpy()[keep]
    k_d, _, _ = store.klookup.lookup("modis_aqua", rows, months, "D")
    k_n, _, _ = store.klookup.lookup("modis_aqua", rows, months, "N")
    value = weight[rows] * (n_day * k_d + n_night * k_n)
    return np.bincount(months - first, weights=value, minlength=len(out))[:len(out)]


def build(store: Store, area: Area, from_: str | None = None, to: str | None = None) -> dict:
    """The board answer. Without `to` the series runs on through the forecast, where there is one. A `to` beyond the
    last month of the answer is cut to it; a `from` after it is refused."""
    ser = series_of(store, area)
    first, last = resolve_period(store, from_, to)
    end = store.first_month + ser.forecast_last if ser.forecast_available else store.cur_month
    if to is None:
        last = max(last, end)
    if first > end:
        raise ApiError(400, "invalid_period", f"from lies after the last month of the answer, {month_label(end)}")
    last = min(last, end)  # the series ends with the forecast, or with the data where there is none
    counts, medians, normals, cur = ser.counts, ser.medians, ser.entries, store.cur_month
    error = ser.quality["expected_error"]

    def element(m: int) -> dict:
        moy = m % 12
        if m < store.first_month or m > cur:
            ahead = ser.forecast_at(m - store.first_month) if m > cur else None
            return {
                "month": month_label(m), "kind": "forecast" if ahead else "none", "count": None,
                "raw": dict.fromkeys(SENSORS), "frp_mw": None,
                "median": medians[moy], "mean": normals[moy]["mean"], "ratio": None, "level": None, "rank": None,
                "of": None, "partial": False, "complete_through": None, "source": "none", "converted": False,
                "sensors": [], "lo": None, "hi": None,
                "forecast": ({**{k: int(ahead[k]) for k in ("median", "low", "high")}, "method": ahead["method"],
                              "err_pct": ahead["err_pct"]} if ahead else None),
            }
        count = int(counts[m])
        ratio, level = ratio_level(count, medians[moy])
        rank = of = None
        if medians[moy] is not None:
            rank = 1 + int((ser.values[:, moy] > count).sum())
            of = len(ser.values) + (0 if (m // 12 + 2000) in store.base_years else 1)
        is_converted = bool(ser.converted[m])
        lo, hi = quality.band(count, error) if is_converted and error is not None else (None, None)
        return {
            "month": month_label(m), "kind": "running" if m == cur else "seen", "count": count,
            "raw": {s: round_int(ser.raw[s][m]) for s in SENSORS},
            "frp_mw": round_int(ser.frp[m]), "median": medians[moy], "mean": normals[moy]["mean"], "ratio": ratio,
            "level": level, "rank": rank, "of": of, "partial": m == cur or m in store.incomplete,
            "complete_through": store.last_complete_date.isoformat() if m == cur else None,
            "source": store.month_source.get(m, "sp"), "converted": is_converted,
            "sensors": list(store.month_sensors.get(m, [])), "lo": lo, "hi": hi, "forecast": None,
        }

    archive = [element(m) for m in range(store.first_month, cur + 1)]
    yearly_all = _yearly(store, counts, ser.converted)
    current = archive[-1] | {"to_date": ser.to_date}
    return {
        "area": {
            "id": area.id, "name": area.name, "bbox": area.bbox, "area_km2": round_int(area.area_km2),
            "approximate": area.approximate, "geometry": to_geojson(area.geometry),
        },
        "first_month": month_label(store.first_month),
        "last_complete_date": store.last_complete_date.isoformat(),
        "series": [archive[m - store.first_month] if m <= cur else element(m) for m in range(first, last + 1)],
        "normals": normals,
        "current_month": current,
        "yearly": [y for y in yearly_all if first // 12 + 2000 <= y["year"] <= last // 12 + 2000],
        "season": season.summarize(archive[max(0, BASE_FIRST_MONTH - store.first_month):], normals,
                                   [y for y in yearly_all if y["year"] >= BASE_FIRST_YEAR]),
        "quality": ser.quality,
        "forecast": {"first_month": ser.month_name(ser.forecast_first), "last_month": ser.month_name(ser.forecast_last),
                     "accuracy": ser.accuracy, **ser.forecast_info()} if ser.forecast_available else None,
        "trend": ser.trend,
        "check": ser.blind_check,
        "presets": ser.preset_items(),
        "data_version": store.version,
    }


def _yearly(store: Store, counts: np.ndarray, converted: np.ndarray) -> list[dict]:
    cur_year = store.cur_month // 12 + 2000
    out = []
    for year in range(store.first_month // 12 + 2000, cur_year + 1):
        months = [m for m in range((year - 2000) * 12, (year - 2000) * 12 + 12) if store.first_month <= m <= store.cur_month]
        if not months:
            continue
        out.append({
            "year": year,
            "count": int(sum(counts[m] for m in months)),
            "complete": len(months) == 12 and year < cur_year,
            "gaps": any(m in store.incomplete for m in months),
            "converted": all(converted[m] for m in months),
        })
    return out


__all__ = ["build", "level_of", "ratio_level", "resolve_period", "series_of"]
