"""Shapes of the answers that the OpenAPI description promises: the calendar board and the archive meta."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Geometry(BaseModel):
    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list[Any]


class AreaOut(BaseModel):
    id: str | None
    name: str
    bbox: list[float]
    area_km2: int
    approximate: bool
    geometry: Geometry


class Raw(BaseModel):
    """Weighted detections of each satellite, before any conversion; null for a month without data."""

    modis_terra: int | None
    modis_aqua: int | None
    viirs_snpp: int | None
    viirs_noaa20: int | None


class ForecastValue(BaseModel):
    """The forecast of a month ahead and its 10th and 90th percentile: the model where it passed its check at that
    horizon, else the median of the same calendar month over the baseline years."""

    median: int
    low: int
    high: int
    method: Literal["model", "climatology"] = "climatology"
    err_pct: float | None = None  # typical error of this method at this horizon, percent; for the median without a check of its own, the leave-one-year-out error of the yearly total


class ToDate(BaseModel):
    """The running month against the same dates of the baseline years."""

    through: str
    count: int
    median: int | None
    ratio: float | None
    rank: int | None
    of: int | None


class Month(BaseModel):
    """One month. kind: seen (complete), running (the current month), forecast (ahead), none (outside the data)."""

    month: str
    kind: Literal["seen", "running", "forecast", "none"]
    count: int | None
    raw: Raw
    frp_mw: int | None
    median: int | None
    mean: int | None
    ratio: float | None
    level: int | None
    rank: int | None
    of: int | None
    partial: bool
    complete_through: str | None
    source: str
    converted: bool
    sensors: list[str]
    lo: int | None
    hi: int | None
    forecast: ForecastValue | None


class CurrentMonth(Month):
    to_date: ToDate


class Normal(BaseModel):
    month: int
    median: int | None
    mean: int | None
    p10: int | None
    p90: int | None
    years: int


class Year(BaseModel):
    year: int
    count: int
    complete: bool
    gaps: bool
    converted: bool = False  # every month of the year is MODIS converted to the VIIRS scale (the years before the VIIRS ones)


class Trend(BaseModel):
    first_year: int = Field(description="First of the ten years.")
    last_year: int = Field(description="Last of the ten years.")
    percent_per_year: int = Field(
        description="Slope of a straight line through the ten yearly totals, in % of their mean."
    )


class YearCount(BaseModel):
    year: int
    count: int


class MonthMedian(BaseModel):
    month: int
    median: int | None


class YearToDate(BaseModel):
    through: str
    count: int
    last_year: int
    ratio: float


class UnusualMonths(BaseModel):
    count: int
    last: str | None


class Season(BaseModel):
    season_months: list[int]
    season_share: float | None
    record_year: YearCount
    quiet_year: YearCount
    peak_month: MonthMedian
    quiet_month: MonthMedian
    average_year: int
    ytd: YearToDate | None
    unusual_months: UnusualMonths
    season_strength: float


class SeamSlice(BaseModel):
    """The 2012 seam (MODIS to VIIRS) in the slice that holds the area: how far our series departs from MODIS alone
    there, against the 90th percentile of the departures in years without a change. `fail` is not softened."""

    name: str
    kind: Literal["world", "zone", "country"]
    seam: str
    gap_pct: float | None
    threshold_pct: float | None
    as_is_jump: float | None  # the jump of the series spliced without our factors, times
    status: Literal["pass", "fail", "insufficient"]


class Quality(BaseModel):
    """Expected error and unharmonized share are fractions (0.25 is 25 %)."""

    expected_error: float | None
    confidence: Literal["high", "medium", "low"] | None
    unharmonized_share: float
    basis: str
    seam: SeamSlice | None = None


class YearSpan(BaseModel):
    first: int
    last: int


class Accuracy(BaseModel):
    """Leave-one-year-out check of the forecast; errors are fractions."""

    fit_years: YearSpan
    blind_years: YearSpan
    year_error: float
    normal_year_error: float
    month_log_error: float
    normal_month_log_error: float
    month_improvement: float


class Forecast(BaseModel):
    first_month: str
    last_month: str
    accuracy: Accuracy | None
    model_horizons: int = 0  # the model serves this many months of the area, from its first month (the forecast starts at the month after the running one); 0 when it does not
    model_months: int = 0  # how many months of this forecast come from the model: all of the first K, the rest is the median
    trained_at: str | None = None
    trained_through: str | None = None  # the last month the model has seen
    basis: Literal["climatology", "model"] = "climatology"  # a code for the interface to word: the median of past years; the model for `model_months` months, then the median


class Score(BaseModel):
    month_log_error: float
    year_error: float
    direction_accuracy: float
    direction_samples: int


class CheckMonth(BaseModel):
    month: str
    real: float
    model: float
    normal: float


class Check(BaseModel):
    """The conversion checked blind on years the factors were not fitted on."""

    fit_years: YearSpan
    blind_years: YearSpan
    months: list[CheckMonth]
    climatology: Score
    poisson: Score
    boosting: Score


class Preset(BaseModel):
    id: str
    kind: Literal["forecast", "year", "season"]
    first_month: str
    last_month: str


class Calendar(BaseModel):
    area: AreaOut
    first_month: str
    last_complete_date: str
    series: list[Month]
    normals: list[Normal]
    current_month: CurrentMonth
    yearly: list[Year]
    season: Season | None
    quality: Quality
    forecast: Forecast | None
    trend: Trend | None = None  # the last ten full years; null when the area is too quiet for one
    check: Check | None
    presets: list[Preset]
    data_version: str


class Sensor(BaseModel):
    id: str
    name: str
    first: str | None
    last: str | None
    retired_at: str | None


class Archive(BaseModel):
    first_month: str
    last_complete_date: str


class Example(BaseModel):
    """A remarkable month of a region, found in the data."""

    id: str
    region_id: str
    names: dict[str, str] = Field(description="The name of the region in en, fr, es and ru, as in `/api/regions`.")
    month: str
    era: str
    count: int
    median: int | None
    ratio: float | None
    rank: int | None
    of: int | None
    found: bool
    source_url: str | None


class ChatState(BaseModel):
    enabled: bool


class SeamHeadline(BaseModel):
    seam: str
    as_is_jump: float | None
    gap_pct: float | None
    threshold_pct: float | None  # null when there are too few joins without a change to compare with
    typical_change_pct: float | None
    status: Literal["pass", "fail", "insufficient"]
    slices: int
    passed: int
    failed: list[str]
    insufficient: list[str]
    text: str


class Seam2026(BaseModel):
    seam: str
    from_sensor: str
    to_sensor: str
    gap_pct: float | None
    threshold_pct: float | None
    status: Literal["pass", "fail", "insufficient"]
    days_before: int
    days_after: int


class SeamMeta(BaseModel):
    headline: SeamHeadline
    seam_2026: Seam2026


class Meta(BaseModel):
    data_version: str
    archive: Archive
    sensors: list[Sensor]
    gap_dates: list[str]
    examples: list[Example]
    chat: ChatState
    seam: SeamMeta | None = None
