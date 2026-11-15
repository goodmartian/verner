"""Chat tools: thin wrappers over the same pure functions the routes call. They only read.

Schemas use only the keys the Claude API accepts for tools. Array bounds, number ranges and string lengths
are described in words and checked here (pydantic, strict), and a failed check goes back to the model as a tool error.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import access as access_module
from .. import areas, calendar, events, fires, landcover, plan, regions, seam, summary, window
from ..climate import Climate
from ..climate_routes import month_weather
from ..errors import ApiError, clean
from ..fires_routes import fire_card_of, plan_of
from ..months import month_label, parse_date
from ..settings import Settings
from ..store import Store
from ..weather import Weather
from . import drawing, files, fire_tools, plan_tools

MAX_RESULT_CHARS = 9000
MAX_UNUSUAL = 20
SERIES_MAX_MONTHS = 36

_AREA = {
    "anyOf": [
        {"type": "object", "properties": {"id": {"type": "string", "description": "Region id from find_region, for example AR-W. WORLD means the whole world."}},
         "required": ["id"], "additionalProperties": False},
        {"type": "object", "properties": {"bbox": {"type": "array", "items": {"type": "number"},
                                                    "description": "Exactly 4 numbers: west, south, east, north in degrees."}},
         "required": ["bbox"], "additionalProperties": False},
        {"type": "object", "properties": {
            "point": {"type": "object", "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                      "required": ["lat", "lon"], "additionalProperties": False},
            "radius_km": {"type": "number", "description": "Circle radius around the point, from 1 to 1500."}},
         "required": ["point", "radius_km"], "additionalProperties": False},
        {"type": "object", "properties": {"drawn": {"type": "string", "description": (
            "Name of an area the person drew on the map, as the board line gives it, for example U1. Its corners stay "
            "with the server. Use it for any question about a drawn or selected area.")}},
         "required": ["drawn"], "additionalProperties": False},
    ]
}


def resolve_area(selector: Any, store: Store, drawn: dict[str, dict] | None = None) -> areas.Area:
    """The area a tool was given. `{"drawn": "U1"}` is an area the person drew: its corners came with the question."""
    if isinstance(selector, dict) and set(selector) == {"drawn"}:
        name = str(selector["drawn"])
        polygon = (drawn or {}).get(name)
        if polygon is None:
            known = ", ".join(drawn or {}) or "none"
            raise ApiError(404, "not_found", f"There is no drawn area {name}. Drawn areas of this question: {known}.")
        found = areas.parse({"polygon": polygon}, store)
        return replace(found, name=f"Drawn area {name}")
    return areas.parse(selector, store)


def _month(description: str) -> dict:
    return {"type": "string", "description": description}


TOOLS: list[dict] = [
    {
        "name": "find_region",
        "description": "Find countries and regions by name, in any language, and get the region id the other tools take. "
                       "Returns up to 10 matches with id, kind, country_name, name and bbox. Use it when the person names "
                       "a place that the board line does not already give with its id. If several match, take the likely "
                       "one and say in a few words which you took, or ask one short question when the choice changes the "
                       "answer. The person sees a card with the list of the regions found, so the text does not list them "
                       "again.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Part of a name."},
                           "limit": {"type": "integer", "description": "How many matches, 1 to 10. Default 5."}},
            "required": ["query"], "additionalProperties": False,
        },
    },
    {
        "name": "get_calendar",
        "description": "Burning calendar of one area: detections per month on the harmonized scale, the normal (median) "
                       "of each calendar month, the ratio to the normal, the running month, the fire season, yearly totals "
                       "with the ratio to the average year, unusual months (twice the normal or more), the trend, the "
                       "quality of the data and, without `to`, the forecast. Counts are detections (hot pixels). Use it "
                       "to explain an area, to find unusual years and months, to compare periods and for "
                       "the forecast.\n"
                       "Period and card: the card under the answer follows the arguments, so pass the period the person "
                       "asked about: from=YYYY-01 and to=YYYY-12 for one year, the first and the last month for some "
                       "months. With a period the card shows the area, the count of the period, the usual count of those "
                       "months (for a whole calendar year the average year), the percent against the usual, the place of "
                       "the period among the years and a chart of the months. With no period it shows the same figures for "
                       "the running month and bars of the years. Those figures and the months one by one are on the card, "
                       "so they are not the text; the card does not show why the period looks as it does: which few months "
                       "made the difference. When period in the result is not the period you asked for (the archive does "
                       "not reach it), the card shows the period of the result, so the answer opens by saying there is no "
                       "data for what the person asked and which period it shows instead.\n"
                       "Running month: current_month is the running (partial) month and complete_through its last complete "
                       "day. Its to_date block compares it with the same dates of earlier years (count, median, ratio, rank; "
                       "through is the last complete day), which is the fair comparison: for a partial month the first and "
                       "main comparison is current_month.to_date. current_month.ratio and median are for a whole month; "
                       "for a partial month they are at most a caveat.\n"
                       "Forecast: forecast.months are the six months ahead, each with median, low, high, its method (model, "
                       "or climatology: the median of past years) and the error err_pct of that method at that month. "
                       "forecast.model says whether the area was in the model's check (checked: false for a drawn area or "
                       "an area outside the check, where the forecast is the median of past years only), for how many "
                       "months ahead the model is used (used_for_months), per month of the check the model's error "
                       "model_err_pct against base_err_pct of the median of past years and whether the model is used there "
                       "(used), and the month it was trained through (trained_through). The model is gradient boosting on "
                       "boxes of one degree, fit on the harmonized monthly counts at each data update and not run on "
                       "request. A forecast figure is a median with its low to high; when checked is false, the forecast "
                       "there is the median of past years only, which is worth saying. The errors, the check and "
                       "trained_through are for a question about how good the forecast is.\n"
                       "Quality (for questions about accuracy, trust, the sensors or the seam, or when confidence is not "
                       "high; an answer about a period leaves it out): quality.expected_error is a fraction (0.25 means "
                       "25 percent) and quality.confidence its level. quality.seam is this area's check of the splice of the sensors at 2012: gap_pct is how far "
                       "the series departs from MODIS alone at the seam, threshold_pct the usual departure in years without "
                       "a change, status pass, fail or insufficient. seam_check is the same check for the world and the "
                       "2026 change from S-NPP to NOAA-20. When they are asked about, report a fail as a fail.\n"
                       "trend is the slope over the last ten full years (first_year to last_year, name them) in percent "
                       "per year; null means the area is too quiet for one.",
        "input_schema": {
            "type": "object",
            "properties": {"area": _AREA, "from": _month("First month, YYYY-MM. Default: the start of the archive."),
                           "to": _month("Last month, YYYY-MM. Default: the current month, and the answer then also has "
                                         "forecast.months: the six months ahead, each with its method and error. "
                                         "Leave it out for any question about the forecast.")},
            "required": ["area"], "additionalProperties": False,
        },
    },
    {
        "name": "get_window",
        "description": "Count of detections in an exact window of dates (at most 366 days) in one area, against the median "
                       "of the same dates in every earlier full year, with p10 and p90 of those years, the ratio, the rank "
                       "among the years (rank, of), partial and complete_through when the window runs into days that are "
                       "not complete yet. Use it for a span of days or weeks: some dates of a month, the last weeks. The "
                       "person sees a card with the count, the usual count of the same dates, the percent against it and "
                       "the place among the years; those are not the text. The card does not say whether that is usual "
                       "for those dates or not: that is the conclusion.",
        "input_schema": {
            "type": "object",
            "properties": {"area": _AREA, "start": _month("First date, YYYY-MM-DD."), "end": _month("Last date, YYYY-MM-DD.")},
            "required": ["area", "start", "end"], "additionalProperties": False,
        },
    },
    {
        "name": "check_event",
        "description": "Check whether one month of one area is a known unusual season: the month is among the top 3 of the "
                       "same calendar month over the archive and at least 2 times its normal. Returns count, normal, ratio, "
                       "rank and the verdict in the field unusual. For the running month (partial) the normal, the ratio "
                       "and the rank are of the same dates of the earlier years. Use it when the person asks about one "
                       "month: whether it is unusual, how it compares, why it looks the way it does. The person sees a card "
                       "with the month: its count, the percent against its normal, its place among the years and bars of "
                       "the same month in every year; those figures are not the text. The text gives the verdict in plain "
                       "words (usual, high, unusual) and what the card cannot say. The rule behind the verdict (top 3, "
                       "twice the normal) is for a person who asks how it is decided, not for the answer.",
        "input_schema": {
            "type": "object",
            "properties": {"area": _AREA, "month": _month("Month, YYYY-MM.")},
            "required": ["area", "month"], "additionalProperties": False,
        },
    },
    {
        "name": "get_month_weather",
        "description": "The weather of one month over an area, from the ERA5 reanalysis: the mean temperature (temperature_c) "
                       "and the rain (rain_mm) of the month, each with its normal (the same calendar month over the normal "
                       "years), how far it is from the normal (difference_c for the temperature, change_from_normal_pct "
                       "for the rain: -40 means 40 percent less rain than normal) and its rank among the years (rank 1 is "
                       "the hottest or the wettest). kind none means there is no weather data for that month: the last "
                       "months of the archive are not there yet: say so in one sentence and offer the last month that has "
                       "it. Use it when the person asks about rain, drought, heat or the weather of a month or a season, "
                       "and when the person asks what was different about a month of detections that stands out: then put "
                       "the two side by side, with the value, the normal and how far from it as the tool gives them. The "
                       "weather and the detections are shown together, not one as the cause of the other, so the text "
                       "does not say the weather caused the burning or its lack. The person sees a card with the rain and "
                       "the temperature of the month, each with its normal and how far it is from it; the text says what "
                       "that means (a dry month, a usual one) rather than the figures again.",
        "input_schema": {
            "type": "object",
            "properties": {"area": _AREA, "month": _month("Month, YYYY-MM.")},
            "required": ["area", "month"], "additionalProperties": False,
        },
    },
    fire_tools.LIST_FIRES,
    fire_tools.GET_FIRE,
    plan_tools.MAKE_PLAN,
    plan_tools.DRAW_ON_MAP,
    plan_tools.OPEN_PLAN,
    files.PREPARE_FILE,
    files.WRITE_REPORT,
]


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Outcome:
    result: dict
    file: dict | None = None  # the file this call made, as the interface shows it
    widget: dict | None = None  # what the interface shows in the answer
    action: dict | None = None  # what the interface does on the board: draw, open the plan


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class _FindRegion(_Strict):
    query: str = Field(min_length=1, max_length=100)
    limit: int = Field(5, ge=1, le=10)


class _Calendar(_Strict):
    area: dict[str, Any]
    from_: str | None = Field(None, alias="from")
    to: str | None = None


class _Window(_Strict):
    area: dict[str, Any]
    start: str
    end: str


class _ListFires(_Strict):
    region: str = Field(areas.WORLD_ID, min_length=1, max_length=64)
    sort_by: Literal["area_ha", "growth", "front_speed", "wind", "place"] = "area_ha"
    limit: int = Field(5, ge=1, le=fire_tools.MAX_ROWS)


class _GetFire(_Strict):
    fire_id: str = Field(min_length=1, max_length=64)


class _PrepareFile(_Strict):
    kind: Literal["monthly", "days", "fires"]
    area: dict[str, Any] = Field(default_factory=lambda: {"id": areas.WORLD_ID})
    region: str = Field(areas.WORLD_ID, min_length=1, max_length=64)
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    month: str | None = None


class _WriteReport(_Strict):
    title: str = Field(min_length=1, max_length=120)
    area: dict[str, Any] = Field(default_factory=lambda: {"id": areas.WORLD_ID})
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    text: str = Field(min_length=1, max_length=files.MAX_BYTES // 10)


class _Event(_Strict):
    area: dict[str, Any]
    month: str


class _Draw(_Strict):
    shapes: list[dict[str, Any]]
    replace: bool = False


class _OpenPlan(_Strict):
    fire_id: str = Field(min_length=1, max_length=64)
    crews: int = Field(2, ge=1, le=20)
    hours: Literal[1, 3, 6] = 3


def _sig(value: Any) -> Any:
    if isinstance(value, float):
        return float(f"{value:.6g}")
    if isinstance(value, dict):
        return {k: _sig(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sig(v) for v in value]
    return value


def _size(view: dict) -> int:
    return len(json.dumps(view, ensure_ascii=False, separators=(",", ":")))


def calendar_view(cal: dict, first: int, last: int) -> dict:
    """The compressed calendar the model sees: not the full series, the geometry or the raw sensor counts."""
    series = [e for e in cal["series"] if e["count"] is not None]
    average = cal["season"].get("average_year")
    unusual = sorted(
        ({k: e[k] for k in ("month", "count", "median", "ratio", "level", "rank", "of")}
         for e in series if not e["partial"] and e["ratio"] is not None and e["ratio"] >= 2),
        key=lambda e: -e["ratio"],
    )[:MAX_UNUSUAL]
    cur = cal["current_month"]
    view: dict[str, Any] = {
        "area": {k: cal["area"][k] for k in ("id", "name", "area_km2", "approximate")},
        "period": {"from": month_label(first), "to": month_label(last)},
        "quality": {k: cal["quality"][k] for k in ("expected_error", "confidence", "unharmonized_share", "seam")},
        "current_month": {**{k: cur[k] for k in ("month", "count", "median", "ratio", "level", "rank", "of", "partial",
                                                 "complete_through")}, "to_date": cur.get("to_date")},
        "normals": [{k: n[k] for k in ("month", "median", "p10", "p90")} for n in cal["normals"]],
        "season": cal["season"],
        "yearly": [{"year": y["year"], "count": y["count"], "complete": y["complete"],
                    "ratio_to_average": round(y["count"] / average, 2) if average else None} for y in cal["yearly"]],
        "unusual_months": unusual,
        "trend": cal["trend"],
        "data_version": cal["data_version"],
    }
    ahead = [{"month": e["month"], **e["forecast"]} for e in cal["series"] if e["forecast"]]
    if ahead and cal["forecast"]:
        view["forecast"] = {"months": ahead, **{k: cal["forecast"][k] for k in ("model_horizons", "model_months", "trained_through", "basis", "model")}}
    if len(series) <= SERIES_MAX_MONTHS:
        view["series"] = [{"month": e["month"], "count": e["count"], "median": e["median"], "ratio": e["ratio"],
                           "level": e["level"]} for e in series]
    else:
        view["series_omitted"] = True
    view = _sig(view)
    if _size(view) > MAX_RESULT_CHARS and "series" in view:
        del view["series"]
        view["series_omitted"] = True
    if _size(view) > MAX_RESULT_CHARS:
        view["unusual_months"] = view["unusual_months"][:10]
    if _size(view) > MAX_RESULT_CHARS:
        for n in view["normals"]:
            n.pop("p10", None)
            n.pop("p90", None)
    return view


class ToolBox:
    def __init__(self, store: Store, settings: Settings, weather: Callable[[], Weather | None] = lambda: None,
                 files: dict | None = None, check: Callable[[str], list[str]] = lambda text: [],
                 land: Callable[[], landcover.LandCover | None] = lambda: None,
                 access: Callable[[], access_module.Access | None] = lambda: None, drawn: int = 0,
                 requests: dict[str, dict] | None = None, areas_drawn: dict[str, dict] | None = None,
                 climate: Callable[[], Climate | None] = lambda: None):
        self.climate = climate  # the weather of months, when it is published
        self.areas_drawn = dict(areas_drawn or {})  # what the person drew, by name (U1): GeoJSON polygons
        self.next_shape = drawn + 1  # shapes are named A1, A2, ... through the whole chat
        self.shapes_left = drawing.MAX_SHAPES  # an answer draws this many more
        self.plans: dict[str, dict] = {}  # the plans made in this answer, by fire id: what the drawing refers to
        self.requests = dict(requests or {})  # the last make_plan arguments of the chat, by fire id; kept with the chat
        self.land = land
        self.access = access
        self.files = {} if files is None else files  # the files of the chat
        self.made = 0
        self.check = check  # numbers of a text that no tool result has
        self.store = store
        self.settings = settings
        self.weather = weather
        self._run = {"find_region": self._find_region, "get_calendar": self._get_calendar,
                     "get_window": self._get_window, "check_event": self._check_event,
                     "get_month_weather": self._month_weather,
                     "list_fires": self._list_fires, "get_fire": self._get_fire,
                     "make_plan": self._make_plan, "draw_on_map": self._draw_on_map, "open_plan": self._open_plan,
                     "prepare_file": self._prepare_file, "write_report": self._write_report}

    def run(self, name: str, args: Any) -> Outcome:
        handler = self._run.get(name)
        if handler is None:
            raise ToolError("unknown_tool", f"There is no tool named {name}.")
        if not isinstance(args, dict):
            raise ToolError("invalid_input", "The tool input must be an object.")
        try:
            return handler(args)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            raise ToolError("invalid_input", f"Invalid input at {where}: {first['msg']}") from None
        except (ApiError, files.FileError) as exc:
            raise ToolError(exc.code, exc.message) from None

    def _area(self, selector: dict) -> areas.Area:
        return resolve_area(selector, self.store, self.areas_drawn)

    def _find_region(self, args: dict) -> Outcome:
        a = _FindRegion.model_validate(args)
        found = regions.find(self.store, a.query, a.limit)
        return Outcome(clean({"regions": [{k: r.get(k) for k in ("id", "kind", "country_name", "name", "bbox")}
                                          for r in found]}))

    def _list_fires(self, args: dict) -> Outcome:
        a = _ListFires.model_validate(args)
        try:
            out = clean(_sig(fire_tools.list_fires(self.store, self.weather, a.region, a.sort_by, a.limit)))
        except KeyError:
            raise ToolError("not_found", f"There is no region {a.region}.") from None
        # the card lists the fires of the answer, in its order: the list of the Fires screen, cut to them
        live = fires.live_of(self.store)
        shown = [live.find(row["id"]) for row in out["fires"]]
        listing = live.listing(a.region, [f for f in shown if f is not None])
        return Outcome(out, widget={"type": "fire_list", "data": clean(listing)} if listing["fires"] else None)

    def _get_fire(self, args: dict) -> Outcome:
        a = _GetFire.model_validate(args)
        found = fire_tools.get_fire(self.store, self.weather, a.fire_id, self.land, self.access)
        if found is None:
            raise ToolError("not_found", f"There is no live fire {a.fire_id}.")
        # the card of the Fires screen; the points, the scar and the outline stay with the screen (FireDetailWidget)
        card = fire_card_of(self.store, self.weather(), a.fire_id, None)
        card.update(detections=[], outline=None, scar=None, core=None)
        return Outcome(clean(_sig(found)), widget={"type": "fire_detail", "data": clean(card)})

    def _plan(self, fire_id: str, request: plan.PlanRequest) -> dict:
        made = clean(plan_of(self.store, self.weather(), self.land(), fire_id, request))
        self.plans[fire_id] = made
        return made

    def _plan_for(self, fire_id: str) -> dict:
        """The plan a drawing refers to: the one made in this answer, else the one the chat made last (its arguments are
        kept), else two crews for three hours."""
        if fire_id in self.plans:
            return self.plans[fire_id]
        return self._plan(fire_id, plan.PlanRequest.model_validate(self.requests.get(fire_id, {"crews": 2, "hours": 3})))

    def _make_plan(self, args: dict) -> Outcome:
        a = plan_tools.MakePlan.model_validate(args)
        made = self._plan(a.fire_id, a)
        self.requests[a.fire_id] = a.model_dump(mode="json", by_alias=True, exclude={"fire_id"}, exclude_none=True)
        summary = plan_tools.digest(made)
        # the forecast at the fire for the hours of the work: the rain, the gusts, the wind at the end of the window
        summary["weather_in_window"] = fire_tools.fire_weather_ahead(self.store, self.weather(), a.fire_id, made["hours"])
        return Outcome(clean(_sig(summary)), widget=plan_tools.widget(made))

    def _draw_on_map(self, args: dict) -> Outcome:
        a = _Draw.model_validate(args)
        built = drawing.build(self.store, self.weather, self._plan_for, a.shapes, self.next_shape, self.shapes_left)
        self.next_shape += len(built.shapes)
        self.shapes_left -= len(built.shapes)
        warnings = drawing.warnings_for(self.store, self.weather, built.shapes, built.from_plan)
        action = {"type": "draw", "shapes": [s.model_dump(mode="json") for s in built.shapes], "replace": a.replace}
        drew = [{"id": s.id, "label": s.label, "kind": s.kind, **built.info.get(s.id, {})} for s in built.shapes]
        return Outcome({"drew": drew, "warnings": warnings}, action=action)

    def _open_plan(self, args: dict) -> Outcome:
        a = _OpenPlan.model_validate(args)
        if fires.live_of(self.store).find(a.fire_id) is None:
            raise ToolError("not_found", f"There is no live fire {a.fire_id}.")
        return Outcome({"opened": True, "crews": a.crews, "hours": a.hours},
                       action={"type": "open_plan", "fire_id": a.fire_id, "crews": a.crews, "hours": a.hours})

    def _file(self, name: str, text: str, mime: str, kind: str, rows: int | None) -> dict:
        meta = files.keep(self.files, self.made, name, text, mime, kind, rows)
        self.made += 1
        return meta

    def _prepare_file(self, args: dict) -> Outcome:
        a = _PrepareFile.model_validate(args)
        if a.kind == "fires":
            try:
                name, text, rows, totals = files.live_fires(self.store, self.weather, a.region)
            except KeyError:
                raise ToolError("not_found", f"There is no region {a.region}.") from None
            columns, mime = files.FIRE_COLUMNS, files.CSV_MIME
        elif a.kind == "days":
            if a.month is None:
                raise ToolError("invalid_input", "kind days needs month, YYYY-MM.")
            name, text, rows, totals = files.days(self.store, self._area(a.area), a.month)
            columns, mime = files.DAY_COLUMNS, files.CSV_MIME
        else:
            first, last = calendar.resolve_period(self.store, a.from_, a.to)
            name, text, rows, totals = files.monthly(self.store, self._area(a.area), first, last)
            columns, mime = files.MONTH_COLUMNS, files.CSV_MIME
        meta = self._file(name, text, mime, a.kind, len(rows))
        return Outcome(clean(_sig(files.described(meta, columns, rows, totals))), meta)

    def _write_report(self, args: dict) -> Outcome:
        a = _WriteReport.model_validate(args)
        bad = self.check(a.text)
        if bad:
            raise ToolError("unverified_numbers", f"These numbers are in no tool result: {', '.join(bad[:10])}. "
                                                  "Write the report again with numbers from the tools only.")
        first, last = calendar.resolve_period(self.store, a.from_, a.to)
        name, text = files.report(self.store, self._area(a.area), first, last, a.title, a.text)
        meta = self._file(name, text, files.MD_MIME, "report", None)
        return Outcome({"file": {"name": name, "kind": "report", "size": meta["size"]}}, meta)

    def _get_calendar(self, args: dict) -> Outcome:
        a = _Calendar.model_validate(args)
        area = self._area(a.area)
        first, last = calendar.resolve_period(self.store, a.from_, a.to)
        # without `to` the calendar runs on into the months ahead, so the forecast is in the answer
        cal = calendar.build(self.store, area, month_label(first), month_label(last) if a.to else None)
        view = calendar_view(cal, first, last)
        view["seam_check"] = seam.meta(self.store.seam)  # how far the splice of the sensors can be trusted; null without the check
        return Outcome(clean(view))

    def _get_window(self, args: dict) -> Outcome:
        a = _Window.model_validate(args)
        area = self._area(a.area)
        res = window.compare(self.store, area, parse_date(a.start, "start"), parse_date(a.end, "end"),
                             self.settings.window_max_area_km2)
        keys = ("count", "median", "p10", "p90", "rank", "of", "ratio", "years", "window", "partial",
                "complete_through", "data_version")
        out = clean(_sig({"area_name": area.name, **{k: res[k] for k in keys}}))
        # the card shows the same figures the model reads; a window with no day of data has none
        card = {"area": {"id": area.id, "name": area.name}, **{k: out[k] for k in keys if k != "data_version"}}
        return Outcome(out, widget=None if out["count"] is None else {"type": "window_stats", "data": card})

    def _month_weather(self, args: dict) -> Outcome:
        a = _Event.model_validate(args)
        area = self._area(a.area)
        calendar.resolve_period(self.store, a.month, a.month)  # the month is checked as a month of the archive
        grid = self.climate()
        if grid is None:
            raise ToolError("unavailable", "The weather of months is not available now.")
        # the answer of /api/climate/month, named by the id as there (`drawn` for a drawn area): it is also the card
        found = clean(_sig(month_weather(grid, area, area.id or "drawn", a.month)))
        out: dict[str, Any] = {"area_name": area.name, "month": a.month, "kind": found["kind"]}
        if found["observed"] is not None:
            seen = found["observed"]
            out["normal_years"] = {"first": seen["normal_first_year"], "last": seen["normal_last_year"]}
            for q in seen["quantities"]:
                row = {k: q[k] for k in ("value", "normal", "rank", "of_years")}
                if q["anomaly_kind"] == "ratio":  # the rain: the answer speaks in percent, rounded by the service
                    row["change_from_normal_pct"] = q["change_pct"]
                else:
                    row["difference_c"] = q["anomaly"]
                out[q["key"]] = row
        widget = {"type": "month_weather", "data": found} if found["kind"] == "observed" else None
        return Outcome(out, widget=widget)

    def _check_event(self, args: dict) -> Outcome:
        a = _Event.model_validate(args)
        area = self._area(a.area)
        first, _ = calendar.resolve_period(self.store, a.month, a.month)
        if not self.store.first_month <= first <= self.store.cur_month:
            raise ToolError("invalid_period", "That month is outside the archive.")
        # the month card of the calendar; the model reads its figures, so the text and the card say the same
        detail = clean(_sig(summary.month(self.store, area, calendar.series_of(self.store, area), a.month)))
        rank = detail["rank"] or {}
        value = detail["value"]
        out = {"area_name": area.name, "month": a.month, "count": int(value) if float(value).is_integer() else value,
               "median": detail["normal"], "ratio": detail["ratio"], "rank": rank.get("place"), "of": rank.get("of"),
               "partial": first == self.store.cur_month or first in self.store.incomplete,
               "unusual": events.is_found(detail["ratio"], rank.get("place")), "data_version": self.store.version}
        return Outcome(clean(out), widget={"type": "month_detail", "data": detail})
