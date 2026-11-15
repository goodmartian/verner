"""Chat tools about plans and the map: `make_plan` (the planner's plan for a fire, in a short summary), `open_plan` and
`draw_on_map`. The plan is the one `POST /api/fires/{id}/plan` gives (`fires_routes.plan_of`); the model gets a digest of
it and the interface gets the plan itself as a `work_plan` widget, so what the model says and what the screen draws are
the same plan."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict

from .. import plan
from . import drawing
from .fire_tools import COMPASS, NAMES

POINT = {"type": "array", "items": {"type": "number"}, "description": "[longitude, latitude]."}
DRAW_ITEM: dict[str, Any] = {
    "kind": {"type": "string", "enum": ["polygon", "line", "point", "circle", "reference"],
             "description": "What the shape is; `reference` builds it from `from`."},
    "label": {"type": "string", "description": "Short caption, up to 40 characters."},
    "note": {"type": "string", "description": "A longer note."},
    "rings": {"type": "array", "items": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
              "description": "Polygon: rings of [longitude, latitude], the outer first."},
    "points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
               "description": "Line: points of [longitude, latitude]."},
    "position": {**POINT, "description": "Point: [longitude, latitude]."},
    "center": {**POINT, "description": "Circle: [longitude, latitude]."},
    "radius_km": {"type": "number", "description": "Circle: radius from 0.1 to 300 km."},
    "role": {"type": "string", "enum": ["approach", "escape", "path", "line", "safe_zone", "area"],
             "description": "Line: `approach` an arrow to the fire, `escape` a way away from it, `path` a way to go (all "
                            "with an arrow at the end), `line` just a line. Polygon or circle: `safe_zone` ground meant to "
                            "be safe from the fire, `area` just a zone. Leave out for a plain line or area."},
    "approach_from": {**POINT, "description": "With `fire:`: an arrow from this point to the nearest edge of the fire."},
    "from": {"type": "string", "description": "Reference: `fire:<id>`, `area:<code>`, `route:<fire_id>`, `escape:<fire_id>` "
                                              "or `safe_zones:<fire_id>`."},
    "buffer_km": {"type": "number", "description": "With `fire:`: a buffer around the footprint, up to 50 km."},
    "forecast_hours": {"type": "integer", "enum": list(drawing.HOURS),
                       "description": "With `fire:`: the front the planner expects after this many hours."},
}

DRAW_ON_MAP = {
    "name": "draw_on_map",
    "description": "Draw shapes on the map in the colour of the assistant. Give plain shapes (`polygon` with rings of "
                   "[longitude, latitude], `line` with points, `point` with a position, `circle` with a center and "
                   "`radius_km`), or `reference` with `from`: `fire:<id>` (the footprint of a fire; with `buffer_km` a buffer "
                   "around it, with `forecast_hours` 1, 3 or 6 where the planner expects the front), `area:<code>` (the border "
                   "of a province), `route:<fire_id>` (the way in of the crews of the plan), `escape:<fire_id>` (their ways "
                   "out) or `safe_zones:<fire_id>` (the burned ground of the plan that serves as a safe zone); the three last "
                   "come from the plan made by make_plan in this answer, or from a plan of two crews and three hours. An "
                   "arrow to the fire is `fire:<id>` with `approach_from`. The server names the shapes A1, A2 and so on and "
                   "builds every reference; you write in the answer `[label](shape:A3)`. A safe zone (`role` safe_zone) and "
                   "a way out (`role` escape) that you give yourself are checked against the fire and its forecast: the "
                   "result says so when they are not safe. Draw only to show a zone, a buffer, where the fire goes, a way "
                   "or some places; give short labels. To show a plan on the map draw `route:<fire_id>`, "
                   "`escape:<fire_id>` and `safe_zones:<fire_id>`; to show where to retreat draw `escape:<fire_id>` and "
                   "`safe_zones:<fire_id>`. The result lists what was drawn (`drew`), with the figures of a plan's "
                   "drawings (trail_km, trail_min, way_out_km), and `warnings`: when you speak of what you drew, quote "
                   "those figures rather than any from memory, and say a WARNING plainly. The person sees the shapes on "
                   "the map, not as a card.",
    "input_schema": {
        "type": "object",
        "properties": {
            "shapes": {"type": "array", "description": f"Up to {drawing.MAX_SHAPES} shapes in an answer; each of "
                                                        f"{drawing.MAX_VERTICES} vertices at most.",
                       "items": {"type": "object", "properties": DRAW_ITEM, "required": ["kind"],
                                 "additionalProperties": False}},
            "replace": {"type": "boolean", "description": "True erases what the assistant drew before, then draws."},
        },
        "required": ["shapes"], "additionalProperties": False,
    },
}

OPEN_PLAN = {
    "name": "open_plan",
    "description": "Open the work plan of a fire on the board, with these crews and hours (the person sees the plan "
                   "screen; it does not make a plan for you: use make_plan for that).",
    "input_schema": {
        "type": "object",
        "properties": {"fire_id": {"type": "string", "description": "Fire id from list_fires."},
                       "crews": {"type": "integer", "description": "Number of crews, 1 to 20. Default 2."},
                       "hours": {"type": "integer", "enum": [1, 3, 6], "description": "Default 3."}},
        "required": ["fire_id"], "additionalProperties": False,
    },
}

MAKE_PLAN = {
    "name": "make_plan",
    "description": "Build the work plan of a live fire with the planner of Verner: where each crew enters, the trail it walks "
                   "over the land to a hot spot (what it crosses, how long), when the fire front reaches it, the way out to "
                   "burned ground and its length, and what is wrong with the plan (issues, with `key` for the blocks that can "
                   "be lifted). Use it for every request for a plan, a route, where to enter a fire or how to retreat, "
                   "with the fire id from list_fires and the crews and hours the person asked for (defaults: 2 crews, "
                   "3 hours); the planner reads the fire, the land and the wind, and a plan reasoned without it would "
                   "have none of them. Build again with changed arguments (another entry in marks, more crews, a block "
                   "lifted by its key in overrides) only when the person agrees to that improvement; never lift a block "
                   "on your own.\n"
                   "The result: wind (with from) and entry_from; front.area_ha_at_pass, the burned area at the last "
                   "satellite pass; front.spread_km_per_h; front.expected_growth_ha_in_window, a model forecast for the "
                   "window ahead, not something that happened (say it \"is expected to grow\", never \"grew\"); issues "
                   "(kinds nopath, long, share, nozone, wind, stale, noland and the blocks), held_blocks and "
                   "rejected_entries with the reason; per crew trail_km and trail_min, path_kind, land (what the path "
                   "crosses), crosses_wet_ground, front_reaches_work_in_h, way_out_km, way_out_on_burned_ground and "
                   "way_out_threatened_in_h; safe_zones (how many) and straight_line_only. `path_kind` says how a path "
                   "was found: \"found over land cover\" is the cheapest way over the vegetation classes of the map, "
                   "\"straight line\" means no map was read. Verner knows nothing about trails, roads or firebreaks, so a "
                   "path is never called an existing trail, a road, a track or a firebreak: say what it crosses and how "
                   "long it is. The summary has no people, equipment or water, so the text names none. "
                   "`weather_in_window` is the forecast of the weather model at the fire for the hours of the work: "
                   "rain_mm_total, max_gust_kmh, min_humidity_pct and points with the wind at some hours (null when the "
                   "forecast does not reach that far: then the text says nothing about the weather ahead).\n"
                   "The person gets the plan as a card with a small map, and on the board: the card shows the crews, "
                   "their entries, trails, times and ways out, so the text does not go through the crews. The text "
                   "says, in short prose: the issues in plain words, with a rejected entry and why, or that the planner "
                   "found none; a turn of the wind, strong gusts or rain in the window; one sentence on the main point "
                   "(where the front goes, or the crew that is most at risk); one improvement the summary supports, as "
                   "an offer; and last the sentence that the plan is an estimate and the decision is made on the spot.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fire_id": {"type": "string", "description": "Fire id from list_fires."},
            "crews": {"type": "integer", "description": "Number of crews, 1 to 20. Default 2."},
            "hours": {"type": "integer", "enum": [1, 3, 6], "description": "Length of the work window. Default 3."},
            "marks": {"type": "array", "description": "Places the person named: where a crew may enter, or where to work.",
                      "items": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["entry", "hot"]},
                                                                  "position": POINT},
                                "required": ["kind", "position"], "additionalProperties": False}},
            "area": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                     "description": "Work area: corners [longitude, latitude], at least 3. The planner takes hot spots from inside it."},
            "overrides": {"type": "array", "items": {"type": "string"},
                          "description": "Keys of blocks to lift, as in issues[].key of an earlier plan. Only when the person agrees."},
        },
        "required": ["fire_id"], "additionalProperties": False,
    },
}


class MakePlan(plan.PlanRequest):
    """The planner's request and the fire it is for (the schema offers no pass: the last one is planned)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    fire_id: str


def _place(card: dict | None) -> dict | None:
    return None if not card else {"name": card["name"], "distance_km": card["distance_km"],
                                  "direction": COMPASS[card["direction"]]}


def _land(shares: list[dict] | None) -> list[dict] | None:
    return None if not shares else [{"class": NAMES[s["id"]], "share_pct": s["share_pct"]} for s in shares]


def digest(made: dict) -> dict:
    """The plan as the model needs it: the figures it may quote, in kilometres and minutes, the issues first. No
    coordinates, no lines: the interface draws those."""
    held = [i["key"] for i in made["issues"] if i["level"] == "block" and not i["forced"]]
    rejected = [{"mark": r["mark"], "reason": next(i["kind"] for i in made["issues"] if i.get("mark") == r["mark"])}
                for r in made["rejected_entries"]]
    return {
        "fire_id": made["fire_id"], "nearest_place": _place(made["nearest_place"]), "window_hours": made["hours"],
        "wind": {**made["wind"], "from": COMPASS[round(made["wind"]["from_deg"] / 45) % 8]},
        "front": {"area_ha_at_pass": made["report"]["area_ha"], "spread_km_per_h": made["report"]["spread_km_per_h"],
                  "expected_growth_ha_in_window": made["report"]["growth_ha"]},
        "entry_from": COMPASS[round(made["entry"]["from_direction"]) % 8],
        "issues": made["issues"], "held_blocks": sorted(held), "rejected_entries": rejected,
        "hot_spots": [{"number": h["number"], "chosen_by_planner": h["chosen_by_planner"], "frp_mw": h["frp_mw"]}
                      for h in made["hot_spots"]],
        "crews": [{
            "number": c["number"], "hot_spot": c["target"]["hot_spot"], "status": c["status"], "held": c["held"],
            "entry_source": c["entry_source"], "entry_forced": c["entry_forced"],
            "trail_km": round(c["length_m"] / 1000, 2), "trail_min": c["walk_min"],
            "path_kind": "found over land cover" if c["on_trail"] else "straight line",
            "crosses_wet_ground": c["crosses_wet_ground"], "land": _land(c["land"]),
            "front_reaches_work_in_h": c["leave_in_h"],
            "way_out_km": round(c["safe_distance_m"] / 1000, 2), "way_out_on_burned_ground": c["safe_on_burned_ground"],
            "way_out_threatened_in_h": c["escape_threatened_in_h"],
        } for c in made["crews"]],
        "safe_zones": len(made["safe_zones"]), "straight_line_only": made["straight_line_only"],
    }


def widget(made: dict) -> dict:
    """The plan as the chat shows it: the screen's own `work_plan`."""
    return {"type": "work_plan", "data": made}
