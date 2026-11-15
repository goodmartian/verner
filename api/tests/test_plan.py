import itertools
import math

import numpy as np
import pytest

from senda_api import plan
from senda_api.errors import ApiError

LON0, LAT0 = 20.0, 10.0
KX = 111_320.0 * math.cos(math.radians(LAT0))


def ll(x, y):
    return LON0 + x / KX, LAT0 + y / 111_320.0


def disk(cx, cy, r, step=300.0):
    g = np.arange(-r, r + 1, step)
    pts = [(cx + x, cy + y) for x in g for y in g if x * x + y * y <= r * r]
    return np.array(pts)


def make_view(wind=(10.0, 270.0), rate=1000.0, upto=2, latest=2) -> plan.FireView:
    """A fire that burned out in the west (pass 0) and still burns in the east (passes 1 and 2); wind from the west."""
    old, new = disk(0, 0, 2000), disk(2600, 0, 900)
    pts = np.vstack([old, new])
    pass_of = np.array([0] * len(old) + [1] * (len(new) // 2) + [2] * (len(new) - len(new) // 2))
    lon, lat = zip(*(ll(x, y) for x, y in pts), strict=True)
    return plan.FireView(
        fire_id="20261114-abc",
        pass_index=upto,
        latest_pass=latest,
        pass_time="2026-11-14T10:00:00+00:00",
        lon=np.array(lon),
        lat=np.array(lat),
        pass_of=pass_of,
        rate_m_per_h=rate,
        wind=lambda h: wind,
        place={"name": "Somewhere", "distance_km": 5.0, "direction": 3},
        frp=np.arange(len(pts), dtype=float)[::-1] + 1.0,  # the strongest detection is the first one
    )


CELL = 0.001  # degrees: about 110 m


def land(lake=None, gap=None, side=0.12, klass="3", forest=None):
    """A land cover source over the fire: grass everywhere, an optional north-south lake across the whole map at
    x metres `lake` (width 600 m) with an opening at y metres `gap` (low, high), an optional forest square."""
    n = int(2 * side / CELL)
    west, north = LON0 - side, LAT0 + side
    rows = []
    for r in range(n):
        y = (LAT0 + side - (r + 0.5) * CELL - LAT0) * 111_320.0
        row = []
        for c in range(n):
            x = (west + (c + 0.5) * CELL - LON0) * KX
            k = klass
            if forest and forest[0] <= x <= forest[1] and forest[2] <= y <= forest[3]:
                k = "1"
            if lake is not None and abs(x - lake) <= 300 and not (gap and gap[0] <= y <= gap[1]):
                k = "8"
            row.append(k)
        rows.append("".join(row))
    grid = {"width": n, "height": n, "bbox": [west, LAT0 - side, LON0 + side, north], "classes": "".join(rows)}
    return lambda box: grid


def water_on(route, lake):
    """Points of the route (as metres) inside the lake band, sampled every 10 m."""
    pts = np.array([metres(p) for p in route])
    out = []
    for a, b in itertools.pairwise(pts):
        n = max(2, int(np.hypot(*(b - a)) / 10))
        out += [(a + (b - a) * t) for t in np.linspace(0, 1, n)]
    return [q for q in out if abs(q[0] - lake) < 270]


def req(**kw):
    return plan.PlanRequest.model_validate(kw)


def metres(pos):
    return (pos[0] - LON0) * KX, (pos[1] - LAT0) * 111_320.0


def test_entry_is_windward_and_head_is_downwind():
    v = make_view()
    out = plan.make_plan(v, req())
    west_edge = v.lon.min()
    assert out["entry"]["position"][0] < west_edge  # west of the outline: wind from the west
    assert out["entry"]["from_direction"] == 6  # the entry lies to the west of the fire
    c1, c3 = out["contours"][0], out["contours"][1]
    ring = lambda c: np.array(c["polygons"][0][0])
    east_growth = ring(c1)[:, 0].max() - v.lon.max()
    west_growth = v.lon.min() - ring(c1)[:, 0].min()
    assert east_growth > 3 * west_growth > 0  # the head is east of the fire, the back is short
    assert ring(c3)[:, 0].max() > ring(c1)[:, 0].max()


def test_contours_grow_and_are_one_calculation():
    v = make_view()
    out = plan.make_plan(v, req())
    areas = [c["area_ha"] for c in out["contours"]]
    assert [c["hours"] for c in out["contours"]] == [1, 3, 6]
    assert areas[0] < areas[1] < areas[2]
    assert plan.contours(v) == out["contours"]  # the fire card shows the same ellipses
    assert out["report"]["growth_ha"] > 0


def test_flanks_and_crews():
    out = plan.make_plan(make_view(), req(crews=3, hours=3))
    assert [f["side"] for f in out["flanks"]] == [0, 1]
    assert all(len(f["line"]) > 2 for f in out["flanks"])
    assert [c["number"] for c in out["crews"]] == [1, 2, 3]
    # crews go to the strongest hot spots, at least 1.5 km apart
    hots = out["hot_spots"]
    assert 1 <= len(hots) <= 3 and all(h["chosen_by_planner"] and h["frp_mw"] > 0 for h in hots)
    assert [h["frp_mw"] for h in hots] == sorted((h["frp_mw"] for h in hots), reverse=True)
    for a in hots:
        for b in hots:
            if a is not b:
                (ax, ay), (bx, by) = metres(a["position"]), metres(b["position"])
                assert np.hypot(ax - bx, ay - by) > plan.HOT_SPACING_M
    assert all(c["target"]["kind"] == "hot" and c["entry_source"] == "planner" for c in out["crews"])
    assert all(c["safe_on_burned_ground"] and c["escape"][0] == c["work_point"] for c in out["crews"])
    assert {i["kind"] for i in out["issues"]} >= {"share", "noland"}  # 3 crews, fewer hot spots, no land cover
    assert out["nearest_place"]["name"] == "Somewhere"
    assert out["source"] == "live" and out["attribution"] is None
    assert out["report"]["detections_last_pass"] > 0 and out["report"]["hot_spots"] == [h["number"] for h in hots]
    assert out["straight_line_only"] is True and all(not c["on_trail"] and c["land"] is None for c in out["crews"])
    assert out["crews"][0]["route"][0] == out["crews"][0]["entry"] and len(out["crews"][0]["route"]) == 2


def test_entry_mark_inside_fire_is_blocked_and_can_be_overruled():
    v = make_view()
    centre = [float(v.lon.mean()), float(v.lat.mean())]
    marks = [{"kind": "entry", "position": centre}]
    out = plan.make_plan(v, req(marks=marks, crews=1))
    block = next(i for i in out["issues"] if i["kind"] == "in")
    assert (block["level"], block["mark"], block["key"], block["forced"]) == ("block", 1, "e1", False)
    assert out["rejected_entries"] == [{"mark": 1, "position": centre}]
    assert out["crews"][0]["entry_source"] == "planner" and out["crews"][0]["status"] == "ok"
    forced = plan.make_plan(v, req(marks=marks, crews=1, overrides=["e1"]))
    assert next(i for i in forced["issues"] if i["kind"] == "in")["forced"] is True
    assert forced["rejected_entries"] == []
    crew = forced["crews"][0]
    assert (crew["entry_source"], crew["entry_forced"], crew["status"]) == ("op", True, "forced")


def test_entry_mark_and_hot_mark_are_used():
    v = make_view()
    entry = ll(-4000, 0)
    hot = ll(-500, 800)
    out = plan.make_plan(
        v, req(marks=[{"kind": "entry", "position": entry}, {"kind": "hot", "position": hot}], crews=2)
    )
    a, b = out["crews"]  # both crews share the one entry and the one hot spot (round robin)
    assert a["entry_source"] == "op" and a["entry_mark"] == 1 and a["hot_mark"] == 1 and a["target"]["hot_spot"] == 1
    assert b["entry_mark"] == 1 and b["hot_mark"] == 1
    assert a["route"][0] == [round(entry[0], 5), round(entry[1], 5)]
    assert out["hot_marks"][0]["number"] == 1 and out["hot_spots"][0]["chosen_by_planner"] is False
    assert out["hot_spots"][0]["frp_mw"] is None
    work = metres(a["work_point"])
    assert np.hypot(work[0] - metres(hot)[0] + plan.HOT_WORK_OFFSET_M, work[1] - metres(hot)[1]) < 40  # 150 m windward


def test_mark_far_away_is_outside():
    far = [LON0 + 2.0, LAT0]
    out = plan.make_plan(make_view(), req(marks=[{"kind": "hot", "position": far}]))
    assert {"level": "info", "kind": "outside", "count": 1} in out["issues"]
    assert out["hot_marks"] == [] and out["hot_spots"][0]["chosen_by_planner"] is True


def test_work_area_chooses_the_hot_spots():
    v = make_view()
    east = [ll(1800, -2000), ll(3800, -2000), ll(3800, 2000), ll(1800, 2000)]
    west = [ll(-2500, -2000), ll(-1000, -2000), ll(-1000, 2000), ll(-2500, 2000)]
    inside = plan.make_plan(v, req(area=east, crews=1))["hot_spots"][0]["position"]
    assert 1800 <= metres(inside)[0] <= 3800
    outside = plan.make_plan(v, req(area=west, crews=1))["hot_spots"][0]["position"]
    assert metres(outside)[0] > 1000  # no detection of the last pass inside: the planner takes them from everywhere


def test_wind_issue_from_30_kmh():
    kinds = lambda wind: {i["kind"] for i in plan.make_plan(make_view(wind=wind), req())["issues"]}
    assert "wind" in kinds((35.0, 270.0))
    assert "wind" in kinds((30.0, 270.0))
    assert "wind" not in kinds((10.0, 270.0))


def test_one_pass_has_no_plan():
    v = make_view(rate=None)
    with pytest.raises(ApiError) as e:
        plan.make_plan(v, req())
    assert e.value.status == 409 and e.value.code == "plan_unavailable"
    assert plan.contours(v) == []


def test_safe_zone_is_clear_of_active_fire():
    v = make_view()
    out = plan.make_plan(v, req(crews=2))
    active = np.array([metres(p) for p in zip(v.lon[v.pass_of >= 1], v.lat[v.pass_of >= 1], strict=True)])
    burned = [c for c in out["crews"] if c["safe_on_burned_ground"]]
    assert burned
    for c in burned:
        x, y = metres(c["safe_point"])
        assert np.hypot(active[:, 0] - x, active[:, 1] - y).min() >= plan.ACTIVE_CLEARANCE_M - 1


def test_no_burned_ground_falls_back_behind_entry():
    v = make_view(upto=1, latest=1)  # nothing is two passes old at pass 1... pass 0 is exactly one older
    v.pass_of = np.where(v.pass_of == 0, 1, v.pass_of)  # everything is live
    out = plan.make_plan(v, req())
    assert not out["safe_zone"]["on_burned_ground"]
    assert any(i["kind"] == "nozone" for i in out["issues"])
    sx, _ = metres(out["safe_zone"]["position"])
    ex, _ = metres(out["entry"]["position"])
    assert sx < ex  # 300 m behind the entry, against the wind


def test_stale_pass_by_hours_behind():
    def stale(hours):
        v = make_view(upto=2, latest=5)
        v.hours_behind = hours
        return [i for i in plan.make_plan(v, req())["issues"] if i["kind"] == "stale"]

    assert stale(7.5) == [{"level": "info", "kind": "stale", "count": 3, "hours": 7.5}]
    assert len(stale(plan.STALE_H)) == 1  # the threshold itself counts
    assert stale(2.0) == [] and stale(0.0) == []


def test_one_area_everywhere():
    v = make_view()
    v.area_ha = 1000.0  # the figure of the fire card, counted by cells
    out = plan.make_plan(v, req(hours=3))
    assert out["report"]["area_ha"] == 1000
    areas = [c["area_ha"] for c in out["contours"]]
    assert areas[0] > 1000 and areas[0] < areas[1] < areas[2]
    assert abs((areas[1] - 1000) - out["report"]["growth_ha"]) <= 1  # contour = card area + growth
    assert plan.contours(v) == out["contours"]
    assert plan.make_plan(make_view(), req())["report"]["area_ha"] > 0  # no card figure: the outline's own area


def test_head_arrives_before_the_crew_and_the_block_can_be_overruled():
    # a very fast fire: the front reaches the work point sooner than the crew can walk to it
    out = plan.make_plan(make_view(rate=20_000.0), req(marks=[{"kind": "hot", "position": ll(8000, 300)}]))
    head = next(i for i in out["issues"] if i["kind"] == "head")
    assert head["level"] == "block" and head["key"] == "h1" and head["forced"] is False
    assert out["crews"][0]["status"] == "block" and out["crews"][0]["held"] == ["head"]
    forced = plan.make_plan(
        make_view(rate=20_000.0), req(marks=[{"kind": "hot", "position": ll(8000, 300)}], overrides=["h1"])
    )
    assert forced["crews"][0]["status"] == "forced" and forced["crews"][0]["held"] == []
    assert next(i for i in forced["issues"] if i["kind"] == "head")["forced"] is True


def test_issues_sorted_blocks_first():
    out = plan.make_plan(make_view(wind=(35.0, 270.0), rate=20_000.0, upto=2, latest=4), req())
    levels = [plan.LEVELS[i["level"]] for i in out["issues"]]
    assert levels == sorted(levels)


def test_trail_goes_round_the_lake():
    # a lake across the whole map between the fire and the hot spots, open only far in the north
    gap = (6000.0, 8000.0)
    lake = -4500.0
    out = plan.make_plan(make_view(), req(crews=1, marks=[{"kind": "entry", "position": ll(-6500, 0)}]), land=land(lake, gap))
    crew = out["crews"][0]
    assert out["straight_line_only"] is False and "noland" not in {i["kind"] for i in out["issues"]}
    assert crew["on_trail"] and crew["crosses_wet_ground"]
    assert not water_on(crew["route"], lake) or all(gap[0] - 150 <= q[1] <= gap[1] + 150 for q in water_on(crew["route"], lake))
    crossing = [q for q in water_on(crew["route"], lake) if abs(q[0] - lake) < 5]
    assert crossing and all(gap[0] <= q[1] <= gap[1] for q in crossing)  # crosses the lake in the opening only
    straight = float(np.hypot(*(np.array(metres(crew["route"][-1])) - np.array(metres(crew["route"][0])))))
    assert crew["length_m"] > 1.4 * straight and crew["walk_min"] > 60
    assert next(c["id"] for c in crew["land"]) == 3  # grass


def test_no_way_over_the_water_is_nopath():
    out = plan.make_plan(
        make_view(), req(crews=1, marks=[{"kind": "entry", "position": ll(-6500, 0)}]), land=land(-4500.0)
    )
    crew = out["crews"][0]
    block = next(i for i in out["issues"] if i["kind"] == "nopath")
    assert (block["level"], block["crew"], block["key"], block["forced"]) == ("block", 1, "p1", False)
    assert not crew["on_trail"] and len(crew["route"]) == 2 and crew["held"] == ["nopath"] and crew["status"] == "block"
    forced = plan.make_plan(
        make_view(), req(crews=1, marks=[{"kind": "entry", "position": ll(-6500, 0)}], overrides=["p1"]), land=land(-4500.0)
    )
    assert forced["crews"][0]["status"] == "forced"


def test_without_land_cover_the_way_is_straight_and_says_so():
    def none(box):
        raise plan.landcover.LandError("no network")

    for source in (None, none):
        out = plan.make_plan(make_view(), req(), land=source)
        assert out["straight_line_only"] is True
        assert {"level": "info", "kind": "noland"} in out["issues"]
        assert all(len(c["route"]) == 2 and not c["on_trail"] and c["land"] is None for c in out["crews"])
        assert not any(i["kind"] == "nopath" for i in out["issues"])


def test_trail_land_share_and_walk_time():
    forest = (-9000.0, 9000.0, -2500.0, 2500.0)  # slows the walk: forest costs 2.5 km/h, grass 3.5 km/h
    plain = plan.make_plan(make_view(), req(crews=1), land=land())["crews"][0]
    wood = plan.make_plan(make_view(), req(crews=1), land=land(forest=forest))["crews"][0]
    assert plain["on_trail"] and wood["on_trail"]
    assert wood["walk_min"] > plain["walk_min"] and wood["land"][0]["id"] == 1
    assert plain["land"][0] == {"id": 3, "share_pct": 100.0}


def test_big_fire_plans_in_seconds():
    import time

    n = 90  # a fire of about 15 km across: a map of 400 x 400 cells
    rows = np.linspace(-7000, 7000, n)
    pts = np.array([(x, y) for x in rows for y in rows if x * x + y * y <= 7000**2])
    lon, lat = zip(*(ll(x, y) for x, y in pts), strict=True)
    pass_of = np.where(pts[:, 0] > 2000, 2, np.where(pts[:, 0] > 0, 1, 0))
    v = plan.FireView(
        fire_id="big", pass_index=2, latest_pass=2, pass_time="2026-11-14T10:00:00+00:00", lon=np.array(lon),
        lat=np.array(lat), pass_of=pass_of, rate_m_per_h=1500.0, wind=lambda h: (15.0, 270.0),
        frp=np.arange(len(pts), dtype=float),
    )
    started = time.perf_counter()
    out = plan.make_plan(v, req(crews=4, marks=[{"kind": "entry", "position": ll(-9000, -9000)}]), land=land(side=0.2))
    assert time.perf_counter() - started < 10
    assert all(c["on_trail"] for c in out["crews"])


def test_blob_outlines_are_valid_polygons_of_a_cell():
    from shapely.geometry import Polygon

    from senda_api.blob import blob_of

    rng = np.random.default_rng(7)
    gx, gy = 0.0012, 0.0011
    shapes = 0
    for _ in range(300):
        n = int(rng.integers(1, 40))
        centre = rng.uniform(-60, 60, 2)
        spread = rng.choice([0.003, 0.01, 0.03])
        pts = [
            (float(centre[0] + dx + sx), float(centre[1] + dy + sy))
            for dx, dy in rng.normal(0, spread, (n, 2))
            for sx in (-0.0019, 0.0019)
            for sy in (-0.0017, 0.0017)
        ]
        for polygon in blob_of(pts, gx, gy) or []:
            poly = Polygon(polygon[0])
            assert poly.is_valid and poly.area >= gx * gy
            shapes += 1
    assert shapes > 200
