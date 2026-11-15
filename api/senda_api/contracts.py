"""Shapes of the live routes' answers, kept by hand.

The routes return plain dicts; these models are what `openapi.json` promises, and the tests check each answer
against them."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schemas import Calendar, CheckMonth, Trend, YearSpan


class Out(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ActionEvent(Out):
    event: Literal["action"]
    data: Action


class AreaCalendarWidget(Out):
    type: Literal["area_calendar"]
    data: Calendar


class AreaInfo(Out):
    id: str = Field(description="ISO alpha-2 country, ISO 3166-2 region, X-<ne_id> or `drawn`.")
    kind: Literal["country", "province", "world", "drawn"] = Field(description="What the area is.")
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="Area bounds; null when unknown."
    )
    timezone: str | None = Field(default=None, description="IANA zone; null when unknown.")
    covered: bool | None = Field(default=None, description="Coverage; null when unknown.")
    forecast_available: bool = Field(
        description="False when the area has no forecast and no blind check."
    )




class AreaStats(Out):
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="Bounds; null when unknown."
    )
    timezone: str | None = Field(
        default=None, description="IANA zone; null when unknown."
    )
    covered: bool | None = Field(default=None, description="Coverage; null when unknown.")
    source: Literal["calendar", "world"] = Field(
        description="`calendar`: the numbers of the calendar; `world`: from the 1 degree world grid."
    )
    cells: int = Field(description="Grid cells whose centre lies inside the area.")
    summary: Summary | None = Field(description="Present for `calendar`.")
    world: WorldAreaStats | None = Field(description="Present for `world`.")


class AreaStatsWidget(Out):
    type: Literal["area_stats"]
    data: AreaStats


class ArtifactStatus(Out):
    name: str = Field(description="Artifact name.")
    version: str | None = Field(
        description="First 12 characters of the sha256 of the loaded file; null when not loaded."
    )
    built_at: str | None = Field(description="When the pipeline built this version.")
    loaded_at: str | None = Field(description="When this process loaded it.")
    error: str | None = Field(description="Why the newest published version is not in use, if it is not.")


class AtDryness(Out):
    vpd_kpa: float
    hdw: float
    category: int
    color: str


class AtRain(Out):
    mm_per_h: float
    category: int
    color: str


class AtWind(Out):
    speed_kmh: float
    gust_kmh: float
    from_deg: int
    category: int
    color: str


class CalendarCheck(Out):
    area: AreaInfo
    fit_years: YearSpan
    blind_years: YearSpan
    months: list[CheckMonth]
    climatology: MethodScore = Field(description="Baseline: the plain monthly mean.")
    poisson: MethodScore = Field(description="MODIS counts converted to the VIIRS scale with the factors fitted on the fit years.")
    boosting: MethodScore = Field(description="MODIS counts as they are, not converted.")


class CalendarLocalNames(Out):
    en: str
    ru: str
    es: str
    fr: str = Field(default="")


class CellMap(Out):
    type: Literal["FeatureCollection"] = Field(default="FeatureCollection")
    month: str
    kind: Literal["seen", "forecast", "year_total"] = Field(
        description="`year_total`: the value is the year's, not the month's."
    )
    features: list[MapFeature] = Field(description="Cells, the smallest value first.")
    attribution: str | None


class ChatDetail(Out):
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[ChatMessage]


class ChatMessage(Out):
    seq: int = Field(description="Number of the message in its chat, from 1.")
    role: Literal["user", "assistant"]
    text: str = Field(description="The question, or the whole answer text, as it was written.")
    widgets: list[Widget] = Field(description="Widgets of an answer, in order.")
    actions: list[Action] = Field(description="Board actions of an answer, in order.")
    created_at: str


class ChatSummary(Out):
    id: str
    title: str
    created_at: str
    updated_at: str


class CircleShape(Out):
    id: str = Field(
        description="Name the server gives the shape: `A1`, `A2` and so on, running through the whole chat. The answer text refers to a shape as `[label](shape:A3)`."
    )
    label: str | None = Field(
        default=None, description="Short caption on the map; the answer text refers to the shape by it."
    )
    note: str | None = Field(default=None, description="A longer note, shown on request.")
    label_at: tuple[float, float] = Field(
        description="Where to put the caption: the pole of inaccessibility of a polygon, the centre of a circle, the middle of a line by its length, the point itself."
    )
    kind: Literal["circle"]
    role: Literal["safe_zone", "area"] = Field(default="area")
    center: tuple[float, float]
    radius_km: float


class Comparison(Out):
    largest: str = Field(description="Country id with the highest average year.")
    smallest: str = Field(description="Country id with the lowest average year.")
    ratio: float = Field(description="Largest over smallest.")
    densest: str = Field(description="Country id with the most detections per area.")
    sparsest: str = Field(description="Country id with the fewest per area.")
    density_ratio: float = Field(description="Densest over sparsest.")


class Config(Out):
    covered_countries: list[CoveredCountry]
    languages: list[str]
    archive_years: list[int]
    default_area: str


class Contour(Out):
    hours: int = Field(description="Hours after the pass.")
    polygons: list[list[list[tuple[float, float]]]] = Field(
        description="Where the front is expected to be: the footprint of the fire widened by its ellipse at the speed the model uses. A GeoJSON MultiPolygon without the wrapper: every part is a list of closed rings, the outer ring first and then its holes; a footprint that falls apart gives several parts."
    )
    area_ha: float = Field(description="Area inside the ring, hectares, at the speed used.")


class CountriesWidget(Out):
    type: Literal["countries"]
    data: WorldCountries


class CountryAnswer(Out):
    id: str = Field(description="ISO 3166-1 alpha-2 code; X-<ne_id> where ISO is absent.")
    timezone: str | None = Field(default=None, description="IANA zone; null when unknown.")
    covered: bool | None = Field(default=None, description="Coverage; null when unknown.")
    names: CalendarLocalNames
    area_km2: int
    average_per_year: float = Field(description="Mean detections per year over the record.")
    density_per_1000_km2: float = Field(description="Average detections per year per 1000 square kilometres.")
    peak_month: int = Field(description="Calendar month (1 to 12) that has the most detections on average.")
    last_year_total: float = Field(description="Detections in the last year of the record.")
    trend_ratio: float | None = Field(
        description="Mean of the last five years over mean of the first five; null if that is zero."
    )
    yearly: list[YearTotal] = Field(description="Every year of the record.")
    seasonal: list[float] = Field(description="Mean detections of each calendar month, January first.")
    years: list[CountryYear] = Field(description="The years asked for, in order.")
    bbox: tuple[float, float, float, float] | None = Field(
        description="Frame for the map; only when countries are asked for by id."
    )
    geometry: Polygon | MultiPolygon | None = Field(description="Outline; only when countries are asked for by id.")
    cells: list[WorldCell] | None = Field(
        description="1 degree cells inside the outline, smallest value first; only by id."
    )


class CountryYear(Out):
    year: int
    total: float = Field(description="Detections in the year.")
    vs_average: float | None = Field(description="Total over the country's average year; null when that is zero.")
    peak_month: int = Field(description="Calendar month (1 to 12) with the most detections that year.")
    monthly: list[float] = Field(description="Detections of each month, January first.")


class Coverage(Out):
    first_day: str = Field(description="First day with data.")
    last_day: str = Field(description="Last day with data; later days are not here yet.")


class CoveredCountry(Out):
    id: str
    names: dict[str, str]
    bbox: tuple[float, float, float, float]




class DayCount(Out):
    date: str
    clusters: int
    detections: float = Field(description="Detections in the scale of VIIRS S-NPP, the same count the month is made of.")


class DayFires(Out):
    date: str
    area: str
    total: int = Field(description="Clusters of the day in the area.")
    shown: int = Field(description="Clusters in `fires`: the biggest ones, at most `limit`.")
    coverage: Coverage
    fires: list[FireCluster]
    attribution: str | None


class Detection(Out):
    position: tuple[float, float]
    pass_index: int
    frp_mw: float = Field(description="Fire radiative power, megawatts.")


class DoneData(Out):
    chat_id: str = Field(description="The chat the answer belongs to; new for `id=new`.")


class DoneEvent(Out):
    event: Literal["done"]
    data: DoneData


class DrawAction(Out):
    type: Literal["draw"]
    shapes: list[PolygonShape | LineShape | PointShape | CircleShape]
    replace: bool = Field(default=False, description="True erases what the assistant drew before, then draws.")




class ErrorBody(Out):
    code: str
    message: str
    fields: list[FieldError] | None = Field(default=None)
    covered_countries: list[CoveredCountry] | None = Field(default=None)


class ErrorEvent(Out):
    event: Literal["error"]
    data: ErrorBody = Field(description="The same shape as an HTTP error,.")


class Factor(Out):
    name: Literal["rain_month", "rain_prev_3_months", "rain_prev_12_months", "temperature_anomaly_c", "year_trend"] = (
        Field(description="Input of the model.")
    )
    multiplier: float = Field(
        description="How much this input moves the forecast: above 1 raises it, below 1 lowers it."
    )


class FieldError(Out):
    loc: list[str | int]
    message: str


class FireCluster(Out):
    id: str = Field(description="`YYYYMMDD-N`: the N-th cluster of the day, by time of detection.")
    lon: float
    lat: float
    first_detection_at: str = Field(
        description="When the satellite first saw the cluster that day (UTC). Not the moment of ignition: VIIRS passes about twice a day, so the fire may be up to half a day older."
    )
    detections: float = Field(
        description="VIIRS S-NPP scale: MODIS counts before the VIIRS handover are multiplied by the calendar's monthly ratio."
    )
    detections_raw: int = Field(description="Detections as the sensor counted them.")
    sensor: Literal["modis", "viirs"]
    frp_mw: int = Field(description="Fire radiative power of the cluster, megawatts.")
    province: str | None = Field(description="Province the cluster lies in, null outside them.")
    timezone: str


class FireDetail(Out):
    source: Literal["live", "demo"]
    summary: FireSummary
    pass_index: int = Field(description="The pass this view is about.")
    pass_time: str
    detections: list[Detection] = Field(description="Hot spots of the fire up to the pass.")
    outline: list[tuple[float, float]] | None = Field(
        description="Closed outline the spread model works on; null before it can be drawn."
    )
    scar: list[list[list[tuple[float, float]]]] | None = Field(
        description="Burn scar as polygons (rings of [longitude, latitude])."
    )
    core: list[list[list[tuple[float, float]]]] | None = Field(
        description="What the last two passes saw burning, as polygons."
    )
    spread: Spread | None
    weather: Weather | None = Field(
        description="Hourly weather at the fire centre; null when there is none for this fire (a live fire before the `weather` artifact has its point). The plan needs it."
    )
    detections_by_day: dict[str, int]
    attribution: str | None
    timezone: str


class FireDetailWidget(Out):
    """The numbers of one fire; the detections, the burn scar, the outline and the vegetation
    grid are left out: the web asks `GET /api/fires/{id}` for them."""

    type: Literal["fire_detail"]
    data: FireDetail


class FireList(Out):
    source: Literal["live", "demo"] = Field(description="`demo` is the example: Corrientes, 17 to 19 February 2022.")
    available: bool = Field(description="False when there is no such data (no live snapshot yet).")
    updated_at: str | None = Field(description="When the data was built; null when not available.")
    days: list[str]
    passes: list[PassInfo]
    fires: list[FireSummary] = Field(description="The largest first.")
    attribution: str | None


class FireListWidget(Out):
    type: Literal["fire_list"]
    data: FireList


class FireSeries(Out):
    speed_kmh: list[float]
    gust_kmh: list[float]
    from_deg: list[int] = Field(description="Direction the wind blows from, degrees from north.")
    wind_category: list[int] = Field(description="Band of the wind layer's legend, per hour.")
    precip_mm: list[float]
    vpd_kpa: list[float]
    hdw: list[float] = Field(
        description="Hot-Dry-Windy index at the surface: vapour pressure deficit in hPa times wind in m/s."
    )
    dryness_category: list[int] = Field(description="Band of the dryness legend, per hour.")
    temperature_c: list[float]
    humidity_pct: list[float]
    fire_id: str
    position: tuple[float, float] = Field(description="Where the weather was taken: the centre of the fire.")


class FireSummary(Out):
    id: str = Field(description="Identifier, for example `20261110-f72476`.")
    center: tuple[float, float]
    nearest_place: NearestPlace
    detection_count: int = Field(description="Detections over the whole window.")
    area_ha: int = Field(
        description="Area of the burn scar at the last pass, hectares: the figure of the map; the same everywhere (list, card, plan)."
    )
    first_detection_at: str
    last_detection_at: str
    growth: list[GrowthPoint] = Field(description="The fire after each pass of the window.")
    timezone: str


class FireWeather(Out):
    available: bool
    start: str | None = Field(description="UTC time of hour 0 of every series.")
    hours: int
    fires: list[FireSeries]


class ForecastBlock(Out):
    months: int = Field(description="Forecast months in the period.")
    total: float = Field(description="Forecast total of those months.")
    normal: float = Field(description="Usual total of those months.")
    rain_vs_normal: float = Field(
        description="Expected rain as a ratio to normal (1 is normal), weighted by usual fires."
    )
    factors: list[Factor] = Field(description="What drives the forecast, the strongest first.")


class ForecastCheckWidget(Out):
    type: Literal["forecast_check"]
    data: CalendarCheck




class GridBounds(Out):
    bounds: tuple[float, float, float, float] = Field(description="[west, south, east, north] of the layer pictures.")
    coordinates: list[tuple[float, float]] = Field(
        description="The four corners (north-west, north-east, south-east, south-west), for a MapLibre `image` source."
    )
    width: int = Field(description="Pixels of a layer picture.")
    height: int
    start: str
    end: str
    hours: int
    cycle: str
    wind_field: WindFieldInfo






class GrowthPoint(Out):
    pass_index: int
    time: str = Field(description="Time of the pass.")
    detections: int = Field(description="Detections of the fire up to and including this pass.")
    pass_detections: int = Field(description="Detections of the fire in this pass alone.")
    area_ha: int = Field(description="Area of the burn scar up to this pass, hectares: the figure of the map.")
    frp_mw: int = Field(description="Fire radiative power of the latest pass with detections, megawatts.")


class Health(Out):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "down"]
    schema_revision: Literal["ok", "outdated", "unknown"]
    artifacts: list[ArtifactStatus] = Field(description="Version and state of every artifact the API reads.")






class LegendBand(Out):
    id: int = Field(description="Number of the band; a value's `category` is this.")
    low: float = Field(description="The band starts at this value (inclusive).")
    high: float | None = Field(description="The band ends here (exclusive); null for the last.")
    name: WeatherLocalNames
    color: str = Field(description="`#rrggbb`.")


class LegendLayer(Out):
    layer: Literal["wind", "rain", "dryness"]
    unit: str
    name: WeatherLocalNames
    description: WeatherLocalNames
    opacity: float = Field(description="How opaque the map layer looks best, 0 to 1.")
    bands: list[LegendBand]


class LineShape(Out):
    id: str = Field(
        description="Name the server gives the shape: `A1`, `A2` and so on, running through the whole chat. The answer text refers to a shape as `[label](shape:A3)`."
    )
    label: str | None = Field(
        default=None, description="Short caption on the map; the answer text refers to the shape by it."
    )
    note: str | None = Field(default=None, description="A longer note, shown on request.")
    label_at: tuple[float, float] = Field(
        description="Where to put the caption: the pole of inaccessibility of a polygon, the centre of a circle, the middle of a line by its length, the point itself."
    )
    kind: Literal["line"]
    role: Literal["approach", "escape", "path", "line"] = Field(
        default="line",
        description="`approach`: an arrow to the fire; `escape`: a way away from the fire; `path`: a way to go; the three are drawn with an arrow at the end. `line`: just a line.",
    )
    points: list[tuple[float, float]]


class MapFeature(Out):
    type: Literal["Feature"] = Field(default="Feature")
    properties: MapProperties
    geometry: Point


class MapProperties(Out):
    v: float = Field(description="Detections in the cell (expected detections for a forecast month).")
    w: float | None = Field(description="Heat weight, 0 to 1, for a forecast month; null otherwise.")


class MethodScore(Out):
    month_log_error: float
    year_error: float
    direction_accuracy: float = Field(description="Share of months in which above or below normal was right.")
    direction_samples: int


class ModelAccuracy(Out):
    fit_years: YearSpan = Field(description="Years the checked model was fitted on.")
    blind_years: YearSpan = Field(description="Years it predicted without seeing them.")
    year_error: float = Field(description="Median relative error of yearly totals per province (0.38 is 38 %).")
    normal_year_error: float = Field(description="The same error of the plain monthly mean.")
    month_log_error: float = Field(description="Mean absolute error of log(1 + detections) per province and month.")
    normal_month_log_error: float = Field(description="The same error of the plain monthly mean.")
    month_improvement: float = Field(
        description="1 - month_log_error / normal_month_log_error: how much closer than the normal."
    )


class MonthDays(Out):
    month: str
    area: str
    coverage: Coverage
    days: list[DayCount] = Field(description="Every day of the month with at least one cluster.")
    attribution: str | None


class MonthDetail(Out):
    area: AreaInfo
    month: str
    calendar_month: int = Field(description="1 to 12.")
    kind: Literal["seen", "forecast", "none"]
    value: float | None = Field(description="Detections seen, or the forecast median.")
    normal: float | None
    ratio: float | None = Field(description="Value over normal; null when there is no normal.")
    rank: Rank | None = Field(description="Place among the same calendar month of every year; seen months only.")
    years: list[MonthYear] = Field(description="This calendar month in every year of the record and the forecast.")
    top_provinces: list[TopProvince] = Field(
        description="Three provinces with the most, for the whole country and a seen month."
    )
    share_of_country: float | None = Field(
        description="For a province and a seen month: its share of the country, 0 to 1."
    )
    forecast: MonthForecast | None
    attribution: str | None


class MonthDetailWidget(Out):
    type: Literal["month_detail"]
    data: MonthDetail


class MonthForecast(Out):
    low: float
    high: float
    normal: float
    rain_vs_normal: float | None = Field(description="Expected rain as a ratio to normal (1 is normal); null: the forecast has no rain in it.")
    factors: list[Factor]




class MonthPoint(Out):
    month: str = Field(description="Month, YYYY-MM.")
    kind: Literal["seen", "forecast", "none"] = Field(
        description="`seen`: counted by the satellites; `forecast`: the model's expectation; `none`: between the archive and the forecast, no data yet."
    )
    value: float | None = Field(description="Detections seen, or the forecast median. Null for `none`.")
    normal: float | None = Field(description="Usual detections of this calendar month over all years of the record.")
    model: float | None = Field(
        description="What the model said: its blind run on the test years of the check, the forecast median ahead. Null elsewhere."
    )
    low: float | None = Field(description="Low end of the forecast range; forecast months only.")
    high: float | None = Field(description="High end of the forecast range; forecast months only.")




class MonthYear(Out):
    year: int
    month: str = Field(description="This calendar month in that year, YYYY-MM.")
    kind: Literal["seen", "forecast", "none"]
    value: float | None
    low: float | None
    high: float | None


class MultiPolygon(Out):
    type: Literal["MultiPolygon"]
    coordinates: list[list[list[tuple[float, float]]]] = Field(description="Polygons, each a list of closed rings.")


class NearestPlace(Out):
    name: str
    distance_km: float = Field(description="Straight-line distance from the fire centre.")
    location: tuple[float, float]
    direction: int = Field(
        description="Compass point: 0 north, 1 north-east, 2 east, 3 south-east, 4 south, 5 south-west, 6 west, 7 north-west."
    )


class OpenPlanAction(Out):
    type: Literal["open_plan"]
    fire_id: str
    crews: int | None = Field(default=None, description="Crews the model planned for.")
    hours: int | None = Field(default=None, description="Hours the model planned for.")


class PassInfo(Out):
    index: int = Field(description="Number of the satellite pass, from 0.")
    time: str = Field(description="UTC time of the first detection of the pass.")
    detection_count: int = Field(description="Detections of the pass over the whole search area.")


class PeriodInfo(Out):
    kind: Literal["month", "quarter", "year", "forecast", "whole_record", "custom"] = Field(
        description="`quarter` and `year` are calendar ones; `forecast` is the whole forecast horizon; `whole_record` is the first to the last month of the archive."
    )
    first_month: str = Field(description="First month, YYYY-MM.")
    last_month: str = Field(description="Last month, YYYY-MM.")
    months: int = Field(description="Number of months in the period.")




class PeriodSummaryWidget(Out):
    type: Literal["period_summary"]
    data: Summary




class Point(Out):
    type: Literal["Point"] = Field(default="Point")
    coordinates: tuple[float, float] = Field(description="[longitude, latitude].")


class PointGeometry(Out):
    type: Literal["Point"]
    coordinates: tuple[float, float]


class PointShape(Out):
    id: str = Field(
        description="Name the server gives the shape: `A1`, `A2` and so on, running through the whole chat. The answer text refers to a shape as `[label](shape:A3)`."
    )
    label: str | None = Field(
        default=None, description="Short caption on the map; the answer text refers to the shape by it."
    )
    note: str | None = Field(default=None, description="A longer note, shown on request.")
    label_at: tuple[float, float] = Field(
        description="Where to put the caption: the pole of inaccessibility of a polygon, the centre of a circle, the middle of a line by its length, the point itself."
    )
    kind: Literal["point"]
    position: tuple[float, float]


class Polygon(Out):
    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]] = Field(
        description="Closed rings of [longitude, latitude]; the first is the outer boundary."
    )


class PolygonShape(Out):
    id: str = Field(
        description="Name the server gives the shape: `A1`, `A2` and so on, running through the whole chat. The answer text refers to a shape as `[label](shape:A3)`."
    )
    label: str | None = Field(
        default=None, description="Short caption on the map; the answer text refers to the shape by it."
    )
    note: str | None = Field(default=None, description="A longer note, shown on request.")
    label_at: tuple[float, float] = Field(
        description="Where to put the caption: the pole of inaccessibility of a polygon, the centre of a circle, the middle of a line by its length, the point itself."
    )
    kind: Literal["polygon"]
    role: Literal["safe_zone", "area"] = Field(default="area")
    rings: list[list[tuple[float, float]]] = Field(
        description="Closed rings of [longitude, latitude]: the outer ring first, then holes."
    )






class ProvinceRow(Out):
    id: str = Field(description="Province code, for example `AR-W`.")
    names: CalendarLocalNames
    total: float = Field(description="Detections in the period (forecast median for months ahead).")
    normal: float = Field(description="Usual total of the same months.")
    ratio: float | None = Field(description="Total over normal; null when there is no normal.")
    share: float = Field(description="Share of all provinces' total, 0 to 1.")
    year_normal: float = Field(description="Usual detections per year.")


class ProvinceTable(Out):
    first_month: str
    last_month: str
    approximate: bool = Field(description="True when the period includes forecast months.")
    whole: bool = Field(description="True when the period is the whole archive: show the share, not the ratio to the normal.")
    sort: Literal["total", "ratio", "name"]
    total: float = Field(description="Sum over the listed provinces.")
    rows: list[ProvinceRow]
    attribution: str | None


class ProvinceTableWidget(Out):
    type: Literal["province_table"]
    data: ProvinceTable


class Range(Out):
    low: float = Field(description="Low end of the likely range of the total.")
    high: float = Field(description="High end of the likely range of the total.")


class Rank(Out):
    place: int = Field(description="Place of this period among the same months of every year, 1 is the most.")
    of: int = Field(description="How many years are compared.")


class Record(Out):
    first_year: int = Field(description="First year of the record.")
    last_year: int = Field(description="Last year of the record.")
    viirs_first_year: int = Field(
        description="First year taken from VIIRS S-NPP; the years before come from MODIS (Terra until July 2002, then Aqua)."
    )


class Region(Out):
    id: str = Field(description="ISO 3166-2 code: `AR` for the country, `AR-W` for Corrientes.")
    kind: Literal["country", "province", "region"]
    country_id: str | None = Field(default=None)
    names: dict[str, str]
    type: str | None = Field(description="Key into `types`; null when the type has no translation.")
    timezone: str
    covered: bool
    bbox: tuple[float, float, float, float] = Field(
        description="[west, south, east, north]. The outline is `/api/regions/{id}/geometry`."
    )
    fires_now: int = Field(description="Fires inside the region now (the example with `demo=1`).")


class RegionGeometry(Out):
    id: str
    geometry: Polygon | MultiPolygon
    bbox: tuple[float, float, float, float]
    timezone: str
    covered: bool


class RegionList(Out):
    regions: list[RegionListItem]
    types: dict[str, dict[str, TypeLabel]] = Field(description="Labels of the `type` keys used above, per language.")


class RegionListItem(Out):
    id: str
    country_id: str | None = Field(default=None)
    kind: str
    names: dict[str, str]
    type: str | None = Field(description="Key into `types`; null when the type has no translation.")
    covered: bool


class RegionListWidget(Out):
    type: Literal["region_list"]
    data: RegionList


class AccessRoute(Out):
    """The way to a fire: drive from the nearest fire station (or place), then walk from the end of the road to the edge."""

    origin_kind: Literal["station", "place"] = Field(
        description="`station`: a fire station; `place`: none was found, the route starts at the fire's nearest place."
    )
    origin_source: Literal["osm", "google", "place"] = Field(
        description="Where the start comes from: OpenStreetMap, Google Places (name only), or the fire's nearest place."
    )
    route_source: Literal["osrm", "google"] = Field(
        description="Where the route comes from: OSRM (with the line), or Google Routes (kilometres and minutes only)."
    )
    station_name: str = Field(description="Name of the fire station, or of the place when `origin_kind` is `place`.")
    station_location: tuple[float, float] | None = Field(description="[longitude, latitude] of the start; null when it comes from Google.")
    drive_min: int
    drive_km: float
    walk_km: float = Field(description="Straight line from the end of the road to the edge of the fire.")
    walk_min: int = Field(description="At 3.5 km/h.")
    total_min: float
    fire_edge_point: tuple[float, float] = Field(description="The point of the fire outline the route aims at.")
    road_end_point: tuple[float, float] | None = Field(description="The point of the road nearest to it; null when the route comes from Google.")
    road_path: list[tuple[float, float]] | None = Field(description="The road route, [longitude, latitude] points; null when the route comes from Google: it is not drawn on our map.")
    attribution: str = Field(description="The credit of the sources that were used.")


class LandClass(Out):
    id: int = Field(description="0: no data (not painted); 1 to 10: ESA WorldCover class / 10.")
    name: CalendarLocalNames
    color: str = Field(pattern=r"^#[0-9a-f]{6}$", description="Colour of the class, `#rrggbb`.")


class LandShare(Out):
    id: int = Field(description="Class id, as in the legend.")
    share_pct: float = Field(description="Share of the area inside the fire outline that has data, percent.")


class LandCover(Out):
    """Vegetation under and around a fire: ESA WorldCover 2021 at about 80 m."""

    bbox: tuple[float, float, float, float] = Field(description="[west, south, east, north], degrees.")
    width: int = Field(description="Cells from west to east.")
    height: int = Field(description="Cells from north to south.")
    data: str = Field(
        description="`width * height` characters, one per cell, rows from north to south and cells from west to east: the class id as a digit, `:` for 10 (class id = character code - 48)."
    )
    classes: list[LandClass] = Field(description="The legend: names in four languages, colours.")
    shares: list[LandShare] = Field(description="Classes under the fire outline, the biggest first; empty when the outline has no data.")
    attribution: str


class FileInfo(Out):
    id: str = Field(description="Download it from `GET /api/chats/{chat_id}/files/{id}`.")
    name: str = Field(description="A safe file name: letters, digits, dot, dash, underscore.")
    mime: str
    size: int = Field(description="Bytes.")
    rows: int | None = Field(description="Data rows of a CSV; null for a report.")
    kind: Literal["monthly", "days", "fires", "report"]


class FileWidget(Out):
    """A file the assistant prepared in this chat: a CSV of data or a Markdown report."""

    type: Literal["file"]
    data: FileInfo


class Regions(Out):
    regions: list[Region] = Field(description=(
        "Without `q`, `country` or `kind`: the countries. With `country`: that country, then its provinces. "
        "With `q`: the best matches, at most `limit` (50 when not given)."))
    types: dict[str, dict[str, TypeLabel]] = Field(
        description="Labels of the `type` keys used by the regions, per language, sent once.")
    attribution: str | None








class SelectFireAction(Out):
    type: Literal["select_fire"]
    fire_id: str


class SetAreaAction(Out):
    type: Literal["set_area"]
    area: str = Field(description="`AR`, a province such as `AR-W`, or a country code.")


class SetPeriodAction(Out):
    type: Literal["set_period"]
    first_month: str
    last_month: str


class ShowWeatherAction(Out):
    type: Literal["show_weather"]
    fire_id: str | None = Field(default=None, description="The fire to open; none means the one that is open.")
    layers: list[Literal["wind", "rain", "dryness"]] | None = Field(
        default=None, description="Weather layers to switch on; none leaves them as they are."
    )
    hour: str | None = Field(
        default=None,
        description="The hour to put the player at, UTC as the weather addresses take it (`2026-10-30T14:00:00`); none means now.",
    )


class Spread(Out):
    rate_m_per_h: float = Field(description="Rate of spread of the head, metres per hour.")
    observed: bool = Field(
        description="True when the speed used was measured between the last two passes; false when it comes from the weather (`rate_source`)."
    )
    rate_source: Literal["measured", "weather"] = Field(
        description="Where the speed used comes from: `weather`, the McArthur grass-fire meter (temperature, humidity, wind, dryness of the grass), or `measured`, the movement of the edge between the last two passes, taken only when it is at most three times the speed from the weather."
    )
    rate_weather_m_per_h: float | None = Field(default=None, description="Not computed: null.")
    rate_measured_m_per_h: float | None = Field(
        description="The speed measured between the last two passes; null with one pass or when the edge did not move."
    )
    length_to_breadth: float | None = Field(description="How elongated the fire is under the wind at the pass; null without wind data.")
    wind: Wind | None = Field(description="Weather at the fire at the pass; null without weather data.")
    contours: list[Contour] = Field(description="The front after 1, 3 and 6 hours.")
    current_area_ha: float = Field(
        description="Area of the burn scar at this pass: the same number as `area_ha` of the fire in the list."
    )


class StepData(Out):
    tool: Literal[
        "area_calendar",
        "area_stats",
        "build_plan",
        "countries",
        "draw_on_map",
        "fire_detail",
        "fire_weather",
        "forecast",
        "list_regions",
        "live_fires",
        "month_detail",
        "month_weather",
        "period_stats",
        "prepare_file",
        "place_weather",
        "provinces",
        "weather_in_area",
    ] = Field(description="The tool the model is calling; the interface says what it is doing.")


class StartData(Out):
    chat_id: str = Field(description="The chat the answer belongs to; a new one for `id=new`. Sent before anything else.")


class StartEvent(Out):
    event: Literal["start"]
    data: StartData


class StepEvent(Out):
    event: Literal["step"]
    data: StepData


class Summary(Out):
    area: AreaInfo
    period: PeriodInfo
    totals: Totals
    verdict: Verdict
    year_ago: YearAgo | None = Field(
        description="The same months a year before; null when the record does not reach back."
    )
    rank: Rank | None = Field(description="Null when fewer than three years can be compared.")
    series: list[MonthPoint] = Field(description="One entry per month of the period.")
    peak: MonthPoint | None = Field(description="The month with the most detections.")
    forecast_range: Range | None = Field(
        description="Likely range of the total, for a period made only of forecast months."
    )
    forecast: ForecastBlock | None = Field(description="Present when the period has forecast months.")
    trend: Trend | None = Field(description="Null when the area is too quiet for a trend.")
    accuracy: ModelAccuracy | None = Field(description="Null when the area has no forecast.")
    whole_record: WholeRecord | None = Field(description="Present only when the period is the whole record.")
    typical: Typical
    record: Record
    attribution: str | None = Field(description="Credits of the data, when the manifest names them.")




class TextData(Out):
    text: str = Field(description="A piece of the answer text to append.")


class TextEvent(Out):
    event: Literal["text"]
    data: TextData


class TimeSpan(Out):
    start: str = Field(description="UTC time of the first hour.")
    end: str = Field(description="UTC time of the last hour.")
    hours: int
    updated_at: str = Field(description="When the data was built.")
    cycle: str | None = Field(description="The GFS run the hours ahead come from.")


class TopProvince(Out):
    id: str
    names: CalendarLocalNames
    value: float = Field(description="Detections in the month.")


class Totals(Out):
    seen: float = Field(description="Detections counted in the period.")
    forecast: float = Field(description="Forecast detections of the period's months ahead.")
    total: float = Field(description="`seen` plus `forecast`.")
    normal: float = Field(description="What the same months usually add up to.")
    approximate: bool = Field(description="True when the total includes forecast months.")



class TypeLabel(Out):
    one: str
    other: str


class Typical(Out):
    year_total: float = Field(description="Usual detections per year.")
    peak_month: int = Field(description="Calendar month (1 to 12) that usually has the most.")




class Verdict(Out):
    level: Literal["none", "near", "below", "above", "far_above"] = Field(
        description="`none`: no normal to compare with; `near`: within 10 % of the normal; `below`/`above`: less/more than the normal; `far_above`: twice the normal or more."
    )
    ratio: float | None = Field(description="Total over normal; null when there is no normal.")
    standing: Literal["record", "top", "quietest", "bottom"] | None = Field(
        description="Among at least five years: `record` is the most, `top` is among the three most, `quietest` is the least, `bottom` is among the three least. Null otherwise."
    )
    forecast_range: Literal["below_normal", "above_normal"] | None = Field(
        description="For a forecast-only period: the whole likely range is below or above normal."
    )


class Weather(Out):
    source: Literal["point", "grid"] = Field(
        description="`grid`: the grid of NOAA GFS at the fire's centre. `point`: weather taken at the fire itself."
    )
    start: str = Field(description="UTC time of the first hour.")
    wind_speed_kmh: list[float]
    wind_from_deg: list[int]
    temperature_c: list[float]
    humidity_pct: list[int]


class WeatherAt(Out):
    time: str = Field(description="The hour the values are for.")
    position: tuple[float, float]
    wind: AtWind
    rain: AtRain
    dryness: AtDryness
    temperature_c: float
    humidity_pct: float


class WeatherLegend(Out):
    available: bool = Field(description="False until the weather artifacts are published.")
    attribution: str | None = Field(
        description="Credits of the weather data (NOAA GFS): show them next to the map."
    )
    grid: TimeSpan | None = Field(description="The hours of the map layers; null if missing.")
    fires: TimeSpan | None = Field(description="The hours of the weather at the fires.")
    layers: list[LegendLayer]


class WeatherLocalNames(Out):
    en: str
    ru: str
    es: str


class WholeRecord(Out):
    total: float = Field(description="Detections over the whole record.")
    average_year: float = Field(description="Average detections per year.")
    strongest_year: YearValue = Field(description="The year with the most detections.")
    quietest_year: YearValue = Field(description="The year with the fewest.")


class WidgetEvent(Out):
    event: Literal["widget"]
    data: Widget


class WindowArea(Out):
    id: str | None = Field(description="Region id; null for an area the person drew.")
    name: str = Field(description="The name the assistant was given for the area.")


class WindowDates(Out):
    start: str = Field(description="First date counted, YYYY-MM-DD.")
    end: str = Field(description="Last date counted: the last complete day when the window runs past it.")


class WindowStats(Out):
    """Detections of a date window against the same dates of the earlier full years, as `get_window` gives them."""

    area: WindowArea
    window: WindowDates
    count: int | None = Field(description="Detections in the window; null when no day of it has data.")
    median: int | None = Field(description="Median of the same dates of the earlier years; null with too few years.")
    p10: int | None
    p90: int | None
    rank: int | None = Field(description="Place of the window among those years, 1 the most.")
    of: int | None = Field(description="How many years the place is among.")
    ratio: float | None = Field(description="Count over median; null without a median.")
    years: int = Field(description="Earlier years compared.")
    partial: bool = Field(description="The window runs past the last complete day.")
    complete_through: str | None = Field(description="The last complete day, when the window is partial.")


class WindowStatsWidget(Out):
    type: Literal["window_stats"]
    data: WindowStats


class MonthWeatherWidget(Out):
    type: Literal["month_weather"]
    data: ClimateMonth


class Wind(Out):
    speed_kmh: float
    from_deg: float = Field(description="Direction the wind blows from, degrees clockwise from north.")
    temperature_c: float
    humidity_pct: float
    at: str = Field(description="The moment this weather is for: the start of the pass on screen, UTC.")


class WindFeature(Out):
    type: Literal["Feature"]
    geometry: PointGeometry
    properties: WindPointProperties


class WindFieldInfo(Out):
    width: int = Field(description="Pixels of `wind-field.png`: one per grid cell.")
    height: int
    u_min: float = Field(description="m/s the value 0 of the red channel stands for.")
    u_max: float = Field(description="m/s the value 255 of the red channel stands for.")
    v_min: float
    v_max: float


class WindPointProperties(Out):
    speed_kmh: float
    gust_kmh: float
    from_deg: int = Field(description="Direction the wind blows from; rotate the arrow by it.")
    category: int = Field(description="Band of the wind legend.")
    color: str = Field(description="`#rrggbb` of the band.")


class WindPoints(Out):
    type: Literal["FeatureCollection"]
    time: str = Field(description="The hour the wind is for.")
    features: list[WindFeature]


class WorkPlanWidget(Out):
    type: Literal["work_plan"]
    data: FirePlan


class WorldAreaStats(Out):
    cells: int = Field(description="Grid cells whose centre lies inside the area.")
    approximate: bool = Field(description="True for an area smaller than a cell: it gets its share of its cell.")
    average_per_year: float
    peak_month: int = Field(description="Calendar month (1 to 12) with the most detections.")
    last_year_total: float
    yearly: list[YearTotal]


class WorldCell(Out):
    lon: float = Field(description="Longitude of the cell centre.")
    lat: float = Field(description="Latitude of the cell centre.")
    value: float = Field(description="Detections in the cell: in `cells_year`, or per year on average.")


class WorldCountries(Out):
    first_year: int
    last_year: int
    source: str = Field(description="What the counts are: instrument, collection and detection type.")
    countries: list[CountryAnswer]
    missing_years: list[int] = Field(description="Years asked for that are outside the record.")
    cells_year: int | None = Field(description="Year the cell values belong to; null means the yearly average.")
    comparison: Comparison | None = Field(description="Two or more countries and no year asked for.")
    year_comparison: YearComparison | None = Field(description="Two or more countries and one year.")
    attribution: str | None


class YearAgo(Out):
    year: int = Field(description="Year the same months fell in a year before (of their first month).")
    first_month: str = Field(description="First month of that period, YYYY-MM.")
    last_month: str = Field(description="Last month of that period, YYYY-MM.")
    total: float = Field(description="Detections in those months.")
    ratio: float | None = Field(description="This period over that one; null when that was zero.")


class YearComparison(Out):
    largest: str
    smallest: str
    ratio: float = Field(description="Largest over smallest in the chosen year.")


class YearTotal(Out):
    year: int
    total: float = Field(description="Detections in the year.")


class YearValue(Out):
    year: int = Field(description="Year.")
    value: float = Field(description="Detections of the period in that year.")




Action = SetPeriodAction | SetAreaAction | SelectFireAction | OpenPlanAction | ShowWeatherAction | DrawAction
ChatEvent = StartEvent | StepEvent | TextEvent | WidgetEvent | ActionEvent | DoneEvent | ErrorEvent
Widget = (
    PeriodSummaryWidget
    | ProvinceTableWidget
    | MonthDetailWidget
    | ForecastCheckWidget
    | CountriesWidget
    | AreaStatsWidget
    | AreaCalendarWidget
    | RegionListWidget
    | FireListWidget
    | FireDetailWidget
    | WorkPlanWidget
    | FileWidget
    | MonthWeatherWidget
    | WindowStatsWidget
)


def ok(model: Any) -> dict:
    """`responses=` of a route whose answer is a plain dict: documents the shape, validates nothing at run time."""
    return {200: {"model": model}}


MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


class LatLon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float
    lon: float


class AreaSelector(BaseModel):
    """Which area, in exactly one of four forms: a catalog `id`; a `bbox`; a `polygon`; a `point` with `radius_km`."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, min_length=1, max_length=64, description="ISO country, ISO 3166-2 region, `WORLD`.")
    bbox: tuple[float, float, float, float] | None = Field(default=None, description="[west, south, east, north].")
    polygon: Polygon | MultiPolygon | None = None
    point: LatLon | None = Field(default=None, description="The centre of a circle; needs `radius_km`.")
    radius_km: float | None = Field(default=None, description="Radius of the circle around `point`, kilometres.")

    @model_validator(mode="after")
    def one_form(self) -> AreaSelector:
        given = {k for k in ("id", "bbox", "polygon", "point", "radius_km") if getattr(self, k) is not None}
        if given not in ({"id"}, {"bbox"}, {"polygon"}, {"point", "radius_km"}):
            raise ValueError("give exactly one of: id, bbox, polygon, or point with radius_km")
        return self

    def as_dict(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


class AreaPeriodRequest(BaseModel):
    """An area and, optionally, a period of months (`YYYY-MM`, both ends included)."""

    model_config = ConfigDict(populate_by_name=True)

    area: AreaSelector
    from_: str | None = Field(default=None, alias="from", pattern=MONTH)
    to: str | None = Field(
        default=None, pattern=MONTH,
        description="Last month. Beyond the last month of the answer (the end of the forecast, or of the data where there is none) it is cut to that month; a `from` after it is refused with 400 `invalid_period`.")


class AreaMonthRequest(BaseModel):
    """An area in any form and one month (`YYYY-MM`): the drawn-area twin of the `area`/`month` query."""

    area: AreaSelector
    month: str = Field(pattern=MONTH)




class ErrorResponse(BaseModel):
    """The body of every error answer."""

    error: ErrorBody


CSV_RESPONSE = {200: {"description": "Hotspots as CSV", "content": {"text/csv": {"schema": {"type": "string"}}}}}
FILE_RESPONSE = {200: {"description": "A file the chat prepared", "content": {"text/csv": {"schema": {"type": "string"}}, "text/markdown": {"schema": {"type": "string"}}}}}
PNG_RESPONSE = {200: {"description": "A PNG picture", "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}}}
EVENT_STREAM = {200: {"description": "Server-sent events", "content": {"text/event-stream": {"schema": {"type": "string"}}}}}


class PlanWind(Out):
    speed_kmh: float
    from_deg: float = Field(description="Direction the wind blows from, degrees clockwise from north.")
    at: str = Field(description="The moment the wind is for: the start of the pass the plan is made at, UTC; the same as the card's `spread.wind.at` of that pass.")


class PlanEntry(Out):
    position: tuple[float, float]
    from_direction: int = Field(description="Compass point of the entry, 0 north, 1 north-east, ... 7 north-west.")


class PlanFlank(Out):
    side: Literal[0, 1]
    line: list[tuple[float, float]]
    length_m: int
    reach_h: float | None = Field(description="Hours until the front reaches the end of the flank; null within the horizon.")


class PlanSafeZone(Out):
    position: tuple[float, float]
    distance_m: int
    on_burned_ground: bool


class PlanTarget(Out):
    kind: Literal["hot"]
    hot_spot: int = Field(description="Number of the hot spot in `hot_spots`.")
    chosen_by_planner: bool = Field(description="True when the hot spot is the planner's, not the operator's mark.")


class PlanCrew(Out):
    number: int
    side: Literal[0, 1] | None = Field(description="Always null: crews go to hot spots, not along a flank.")
    target: PlanTarget
    entry: tuple[float, float]
    entry_source: Literal["op", "planner"]
    entry_mark: int | None
    entry_forced: bool = Field(description="An entry the planner blocked and the operator overruled.")
    hot_mark: int | None = Field(description="Number of the operator's hot mark, null for a hot spot of the planner.")
    work_point: tuple[float, float]
    route: list[tuple[float, float]] = Field(description="Way in: a trail over land cover, or two points without it.")
    on_trail: bool = Field(description="True when `route` is a trail found over land cover.")
    crosses_wet_ground: bool = Field(description="The straight way would cross water or marsh that the trail goes round.")
    length_m: int = Field(description="Length of the way in.")
    walk_min: int
    long_walk: bool = Field(description="Walking takes longer than the work window.")
    leave_in_h: float | None = Field(description="Hours until the front reaches the work point; null within the horizon.")
    distance_to_active_m: int | None = Field(description="For a work point inside the fire: distance to the nearest fire of the last two passes.")
    escape: list[tuple[float, float]]
    safe_point: tuple[float, float]
    safe_distance_m: int
    safe_on_burned_ground: bool
    escape_threatened_in_h: float | None = Field(description="Hours until the front reaches the way out, if within the window.")
    held: list[str] = Field(description="Kinds of the blocks that hold the crew back (`issues[].kind`).")
    status: Literal["ok", "forced", "block"] = Field(description="`forced`: sent although blocked, by the operator's override.")
    land: list[LandShare] | None = Field(
        description="The one or two land classes the way in crosses most (ESA WorldCover, legend of `GET /api/fires/{id}/land-cover`); null when the map cannot be read now."
    )


class PlanHotMark(Out):
    number: int
    position: tuple[float, float]


class PlanHotSpot(Out):
    number: int
    position: tuple[float, float]
    chosen_by_planner: bool
    frp_mw: float | None = Field(description="Fire radiative power of the detection; null for the operator's mark.")


class PlanRejected(Out):
    mark: int
    position: tuple[float, float]


class PlanIssue(Out):
    level: Literal["block", "risk", "info"]
    kind: Literal["outside", "in", "fc", "wind", "stale", "head", "nozone", "escfire", "noland", "nopath", "long", "share"] = Field(
        description="`in`/`fc`: an entry inside the fire or reached by the front; `wind`: wind of 30 km/h or more; `head`: the "
        "front arrives before the crew; `nopath`: no trail over land cover; `long`: the walk takes longer than the window; "
        "`nozone`: no burned ground to retreat to; `escfire`: the way out is threatened; `share`: more crews than hot spots; "
        "`stale`: a newer pass exists; `outside`: marks far from the fire; `noland`: no land cover, ways are straight lines."
    )
    crew: int | None = None
    mark: int | None = None
    key: str | None = Field(default=None, description="What to send in `overrides` to overrule this block.")
    forced: bool | None = None
    hours: float | None = None
    speed_kmh: float | None = None
    count: int | None = None
    until_min: int | None = None
    walk_min: int | None = None
    distance_m: int | None = None
    hot_spot: int | None = None
    crews: int | None = None
    hot_spots: int | None = None


class PlanReport(Out):
    area_ha: int
    detections_last_pass: int
    last_pass: int
    hot_spots: list[int] = Field(description="Hot spots the crews are sent to.")
    all_on_burned_ground: bool
    spread_km_per_h: float
    growth_ha: int
    leave_in_h: float | None
    safe_min_m: int
    safe_max_m: int


class FirePlan(Out):
    """A work plan at one pass of a fire: trails over land cover, from the detections, the measured speed and the GFS wind."""

    source: Literal["live", "demo"]
    fire_id: str
    pass_index: int
    pass_time: str
    hours: Literal[1, 3, 6]
    wind: PlanWind
    contours: list[Contour]
    entry: PlanEntry
    flanks: list[PlanFlank]
    safe_zone: PlanSafeZone
    safe_zones: list[list[tuple[float, float]]] = Field(description="Outlines of the burned ground that serves as safety zone.")
    crews: list[PlanCrew]
    hot_spots: list[PlanHotSpot]
    hot_marks: list[PlanHotMark]
    rejected_entries: list[PlanRejected]
    issues: list[PlanIssue]
    report: PlanReport
    nearest_place: NearestPlace | None
    straight_line_only: bool = Field(description="True when there was no land cover: every way is a straight line.")
    attribution: str | None


class ClimateBand(Out):
    id: int
    low: float
    high: float | None
    name: WeatherLocalNames
    color: str


class ClimateLayer(Out):
    layer: Literal["temperature", "rain"]
    kind: Literal["anomaly"] = Field(description="The layer shows the deviation from the normal of the month.")
    unit: str
    name: WeatherLocalNames
    description: WeatherLocalNames
    opacity: float
    bands: list[ClimateBand]


class ClimateLegend(Out):
    available: bool
    attribution: str
    first_month: str
    last_month: str = Field(description="The newest month with data.")
    month_layers: list[ClimateLayer]


class ClimateQuantity(Out):
    key: Literal["temperature_c", "rain_mm"]
    unit: str
    value: float
    normal: float = Field(description="The mean of this calendar month over the normal years.")
    anomaly: float | None = Field(
        description="`value - normal`, or for rain `value / normal`; null for rain when the normal is 5 mm or less."
    )
    anomaly_kind: Literal["difference", "ratio"]
    change_pct: int | None = Field(
        default=None, description="For rain: how far from the normal in percent (-40 is 40 % less); null otherwise."
    )
    rank: int = Field(description="Place among the same calendar month of the years, 1 the most.")
    of_years: int


class ObservedMonth(Out):
    quantities: list[ClimateQuantity]
    normal_first_year: int
    normal_last_year: int


class ClimateMonth(Out):
    """The weather of a month in an area, averaged over it."""

    area: str
    month: str
    kind: Literal["observed", "none"] = Field(description="`none`: there is no data for this month.")
    observed: ObservedMonth | None
    attribution: str | None


class ClimateBounds(Out):
    bounds: tuple[float, float, float, float]
    coordinates: list[tuple[float, float]] = Field(
        description="North-west, north-east, south-east, south-west: for a MapLibre image source."
    )
    width: int
    height: int
