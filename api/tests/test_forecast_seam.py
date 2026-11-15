"""The model forecast and the check of the seam between the sensors, on synthetic files of a data version."""

import dataclasses
import json

import polars as pl
import pytest
from fakes import ScriptedModel, call, parse_sse, say
from fastapi.testclient import TestClient

from senda_api import forecasts, seam
from senda_api.app import create_app
from senda_api.chat.tools import ToolBox
from senda_api.chat.verify import unverified
from senda_api.settings import Settings

# the fixture version has its running month 2026-11 and the forecast of the calendar runs 2026-12 to 2027-05. The model has
# seen to 2026-10 and forecasts the horizons 2 to 7, that is these six months: the running month is not forecast at all.
MONTHS = ["2026-12", "2027-01", "2027-02", "2027-03", "2027-04", "2027-05"]
HORIZONS = [2, 3, 4, 5, 6, 7]


def write_forecast(root, rows, validated=None, horizons=None):
    root.mkdir(parents=True, exist_ok=True)
    frame = [{"region_id": rid, "month": MONTHS[h - 2], "horizon": h, "p10": p10, "p50": p50, "p90": p90,
              "method": "model", "err_pct": err} for rid, h, p10, p50, p90, err in rows]
    pl.DataFrame(frame, schema={"region_id": pl.String, "month": pl.String, "horizon": pl.Int8, "p10": pl.Float32,
                                "p50": pl.Float32, "p90": pl.Float32, "method": pl.String,
                                "err_pct": pl.Float32}).write_parquet(root / "forecast.parquet")
    (root / "forecast.json").write_text(json.dumps({
        "version": "v1", "trained_at": "2026-11-13T10:00:00Z", "trained_through": "2026-10", "train_rows": 1000,
        "method_default": "climatology", "model": {"horizons": HORIZONS, "months": MONTHS}, "validated": validated or {},
        "use_model": {}, "model_horizons": horizons or {}}))


def with_files(store, tmp_path, rows=(), validated=None, horizons=None, seam_doc=None):
    root = tmp_path / "v"
    root.mkdir(parents=True, exist_ok=True)
    if rows or validated:
        write_forecast(root, rows, validated, horizons)
    if seam_doc is not None:
        (root / "seam.json").write_text(json.dumps(seam_doc))
    return dataclasses.replace(store, forecast=forecasts.load(root), seam=seam.load(root))


def board(store, area):
    client = TestClient(create_app(store=store))
    res = client.post("/api/calendar", json={"area": area})
    assert res.status_code == 200, res.text
    return res.json()


def ahead(body):
    return {e["month"]: e["forecast"] for e in body["series"] if e["kind"] == "forecast"}


def test_without_the_files_the_forecast_is_the_median(store, tmp_path):
    body = board(with_files(store, tmp_path), {"id": "XA"})
    assert all(f["method"] == "climatology" and f["err_pct"] is not None for f in ahead(body).values())
    f = body["forecast"]
    assert f["model_horizons"] == 0 and f["model_months"] == 0 and f["trained_at"] is None and f["basis"] == "climatology"
    assert body["quality"]["seam"] is None
    assert TestClient(create_app(store=store)).get("/api/meta").json()["seam"] is None


def test_model_months_take_the_values_of_the_file_and_the_rest_stay_the_median(store, tmp_path):
    rows = [("XA", 2, 1, 2, 3, 40.0), ("XA", 3, 11, 22, 33, 41.0), ("XA", 4, 12, 24, 36, 42.0)]
    validated = {"XA": {"base_err_pct": [50.0, 51.0, 52.0, 53.0, 54.0, 55.0], "model_err_pct": [40, 41, 42, 60, 60, 60]}}
    marked = with_files(store, tmp_path, rows, validated, {"XA": 3})
    body = board(marked, {"id": "XA"})
    got = ahead(body)
    assert got["2026-12"] == {"median": 2, "low": 1, "high": 3, "method": "model", "err_pct": 40.0}
    assert got["2027-01"] == {"median": 22, "low": 11, "high": 33, "method": "model", "err_pct": 41.0}
    assert got["2027-02"]["median"] == 24 and got["2027-02"]["method"] == "model"
    plain = board(store, {"id": "XA"})
    assert got["2027-03"]["method"] == "climatology" and got["2027-03"]["median"] == ahead(plain)["2027-03"]["median"]
    assert got["2027-03"]["err_pct"] == 53.0  # the median's error at horizon 5 in the check of the area
    f = body["forecast"]
    assert (f["model_horizons"], f["model_months"], f["trained_through"], f["basis"]) == (3, 3, "2026-10", "model")
    assert f["trained_at"] == "2026-11-13T10:00:00Z"
    assert f["first_month"] == "2026-12" and f["last_month"] == "2027-05"


def test_the_error_of_the_median_goes_by_the_horizons_of_the_file_all_six_of_them(store, tmp_path):
    validated = {"XA-W": {"base_err_pct": [11.0, 12.0, 13.0, 14.0, 15.0, 16.0], "model_err_pct": [20] * 6}}
    marked = with_files(store, tmp_path, [("XA", 2, 1, 2, 3, 1.0)], validated, {"XA": 1})
    got = ahead(board(marked, {"id": "XA-W"}))
    assert [got[m]["err_pct"] for m in MONTHS] == [11.0, 12.0, 13.0, 14.0, 15.0, 16.0]  # horizon 7 is the sixth value
    assert {f["method"] for f in got.values()} == {"climatology"}
    assert marked.forecast.base_error("XA-W", 7) == 16.0 and marked.forecast.base_error("XA-W", 1) is None
    assert marked.forecast.base_error("XA-W", 8) is None and marked.forecast.base_error("nowhere", 2) is None


def test_the_error_of_the_file_is_rounded_to_a_tenth(store, tmp_path):
    marked = with_files(store, tmp_path, [("XA", 2, 1, 2, 3, 10.6)], {}, {"XA": 1})
    assert ahead(board(marked, {"id": "XA"}))["2026-12"]["err_pct"] == 10.6


def test_an_area_the_model_does_not_cover_has_the_median_and_does_not_borrow_the_country(store, tmp_path):
    rows = [("XA", 2, 11, 22, 33, 41.0)]
    validated = {"XA-W": {"base_err_pct": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0], "model_err_pct": [20] * 6}}
    marked = with_files(store, tmp_path, rows, validated, {"XA": 1})
    west = board(marked, {"id": "XA-W"})
    assert {f["method"] for f in ahead(west).values()} == {"climatology"}
    assert ahead(west)["2026-12"]["err_pct"] == 10.0 and west["forecast"]["model_horizons"] == 0
    assert west["forecast"]["basis"] == "climatology"
    for area in ({"bbox": [20.1, 9.1, 21.9, 9.9]}, {"bbox": [22.0, 9.0, 23.0, 10.0]}):  # drawn, inside and across the border
        got = board(marked, area)
        assert {f["method"] for f in ahead(got).values()} == {"climatology"} and got["forecast"]["basis"] == "climatology"


def model_block(store, area):
    return ToolBox(store, Settings(anthropic_api_key=None)).run("get_calendar", {"area": area}).result["forecast"]["model"]


def test_the_assistant_sees_what_the_model_says_where_it_serves_the_area(store, tmp_path):
    rows = [("XA", 2, 1, 2, 3, 41.1), ("XA", 3, 11, 22, 33, 42.0), ("XA", 4, 12, 24, 36, 43.0)]
    validated = {"XA": {"model_err_pct": [41.1, 42.0, 43.0, 60.0, 61.0, 62.0], "base_err_pct": [51.0, 52.0, 53.0, 54.0, 55.0, 56.0]}}
    got = model_block(with_files(store, tmp_path, rows, validated, {"XA": 3}), {"id": "XA"})
    assert {k: got[k] for k in ("checked", "used_for_months", "first_month", "last_month", "trained_through", "trained_at")} == {
        "checked": True, "used_for_months": 3, "first_month": "2026-12", "last_month": "2027-05",
        "trained_through": "2026-10", "trained_at": "2026-11-13T10:00:00Z"}
    assert [r["month"] for r in got["check"]] == MONTHS
    assert [r["used"] for r in got["check"]] == [True, True, True, False, False, False]
    assert got["check"][0] == {"month": "2026-12", "model_err_pct": 41.1, "base_err_pct": 51.0, "used": True}
    assert got["check"][5] == {"month": "2027-05", "model_err_pct": 62.0, "base_err_pct": 56.0, "used": False}


def test_an_area_checked_and_not_served_has_its_check_by_the_horizons_of_the_file(store, tmp_path):
    validated = {"XA-W": {"base_err_pct": [11.0, 12.0, 13.0, 14.0, 15.0, 16.0], "model_err_pct": [21.0, 22.0, 23.0, 24.0, 25.0, 26.0]}}
    marked = with_files(store, tmp_path, [("XA", 2, 1, 2, 3, 1.0)], validated, {"XA": 1})
    got = model_block(marked, {"id": "XA-W"})
    assert got["checked"] is True and got["used_for_months"] == 0
    # the first value of the arrays is horizon 2, the first horizon of the file, not horizon 1
    assert got["check"][0] == {"month": "2026-12", "model_err_pct": 21.0, "base_err_pct": 11.0, "used": False}
    assert [r["model_err_pct"] for r in got["check"]] == [21.0, 22.0, 23.0, 24.0, 25.0, 26.0]
    assert not any(r["used"] for r in got["check"])
    assert marked.forecast.model_error("XA-W", 2) == 21.0 and marked.forecast.model_error("XA-W", 7) == 26.0
    assert marked.forecast.model_error("XA-W", 1) is None and marked.forecast.model_error("nowhere", 2) is None


def test_a_drawn_area_or_one_outside_the_check_is_not_checked(store, tmp_path):
    marked = with_files(store, tmp_path, [("XA", 2, 1, 2, 3, 1.0)], {"XA": {"base_err_pct": [1.0] * 6, "model_err_pct": [1.0] * 6}},
                        {"XA": 1})
    for area in ({"bbox": [20.1, 9.1, 21.9, 9.9]}, {"id": "XA-W"}):
        got = model_block(marked, area)
        assert got["checked"] is False and got["used_for_months"] == 0 and "check" not in got
        assert got["trained_through"] == "2026-10" and got["first_month"] == "2026-12"
    assert board(marked, {"id": "XA"})["forecast"].get("model") is None  # the board's schema leaves the block out


def test_an_answer_may_quote_the_check_of_the_model(store, tmp_path):
    rows = [("XA", 2, 1, 2, 3, 41.1)]
    validated = {"XA": {"model_err_pct": [41.1, 42.0, 43.0, 60.0, 61.0, 62.0], "base_err_pct": [51.0, 52.0, 53.0, 54.0, 55.0, 56.0]}}
    marked = with_files(store, tmp_path, rows, validated, {"XA": 1})
    out = ToolBox(marked, Settings(anthropic_api_key=None)).run("get_calendar", {"area": {"id": "XA"}}).result
    text = "Модель обучена по октябрь 2026 года; в декабре её ошибка 41,1 % против 51 % у медианы, в мае 62 % против 56 %."
    assert unverified(text, [out], []) == []
    assert unverified(text + " Ошибка модели 33,3 %.", [out], []) != []


def test_a_file_that_is_not_what_it_says_is_refused(store, tmp_path):
    root = tmp_path / "bad"
    write_forecast(root, [("XA", 2, 3, 2, 1, 1.0)])  # p10 > p50
    with pytest.raises(ValueError, match="p10 <= p50 <= p90"):
        forecasts.load(root)
    pl.DataFrame({"region_id": ["XA"]}).write_parquet(root / "forecast.parquet")
    with pytest.raises(ValueError, match="lacks columns"):
        forecasts.load(root)
    assert forecasts.load(tmp_path / "none") is None


# --- the seam ---


def slice_of(kind, name, gap, threshold, status, as_is=2.0):
    return {"kind": kind, "name": name, "seam": {"as_is": as_is, "ours": None if gap is None else 1 + gap, "modis": 1.0, "gap": gap, "as_is_gap": 1.0},
            "placebo_gap_p90_abs": threshold, "status": status}


SEAM = {
    "version": "",
    "headline": {"naive_jump": 6.2267, "ours_gap_pct": 1.8143, "placebo_gap_p90_abs_pct": 3.4588,
                 "placebo_typical_change_pct": 4.6852, "status": "pass",
                 "text": "Spliced as is, the series jumps 6.23 times at 2012-02."},
    "seam_2026": {"seam": {"gap": 0.0407187}, "placebo_gap_p90_abs": 0.0257940, "status": "fail", "before_days": 30,
                  "after_days": 11},
    "slices": [slice_of("world", "world", 0.0181, 0.0346, "pass", 6.2267), slice_of("country", "XA", 0.052, 0.03, "fail"),
               slice_of("zone", "z1", 0.01, 0.03, "pass"), slice_of("zone", "z2", None, None, "insufficient")],
    "failed": ["country:XA"], "insufficient": ["zone:z2"],
}


def test_meta_carries_the_headline_and_the_new_seam_and_fail_stays_fail(store, tmp_path):
    marked = with_files(store, tmp_path, seam_doc=SEAM)
    body = TestClient(create_app(store=marked)).get("/api/meta").json()["seam"]
    head = body["headline"]
    assert (head["as_is_jump"], head["gap_pct"], head["threshold_pct"], head["typical_change_pct"]) == (6.2267, 1.81, 3.46, 4.69)
    assert (head["status"], head["slices"], head["passed"]) == ("pass", 4, 2)
    assert head["failed"] == ["country:XA"] and head["insufficient"] == ["zone:z2"]
    new = body["seam_2026"]
    assert new == {"seam": "2026-11", "from_sensor": "viirs_snpp", "to_sensor": "viirs_noaa20", "gap_pct": 4.07,
                   "threshold_pct": 2.58, "status": "fail", "days_before": 30, "days_after": 11}


def test_the_calendar_says_the_seam_of_the_slice_of_the_area(store, tmp_path):
    marked = with_files(store, tmp_path, seam_doc=SEAM)
    country = board(marked, {"id": "XA"})["quality"]["seam"]
    assert country == {"name": "XA", "kind": "country", "seam": "2012-02", "gap_pct": 5.2, "threshold_pct": 3.0,
                       "as_is_jump": 2.0, "status": "fail"}
    assert board(marked, {"id": "WORLD"})["quality"]["seam"]["kind"] == "world"
    # a country with no slice of its own: its zone
    no_country = dict(SEAM, slices=[s for s in SEAM["slices"] if s["kind"] != "country"])
    zone = board(with_files(store, tmp_path, seam_doc=no_country), {"id": "XA"})["quality"]["seam"]
    assert zone["kind"] == "zone" and zone["status"] in {"pass", "insufficient"}
    none = dict(SEAM, slices=[s for s in SEAM["slices"] if s["kind"] == "world"])
    assert board(with_files(store, tmp_path, seam_doc=none), {"id": "XA"})["quality"]["seam"] is None


@pytest.mark.usefixtures("database")
def test_the_assistant_gets_the_method_the_error_and_the_seam(store, tmp_path):
    rows = [("XA", 2, 11, 22, 33, 41.0), ("XA", 3, 12, 24, 36, 42.0)]
    marked = with_files(store, tmp_path, rows, {}, {"XA": 2}, SEAM)
    model = ScriptedModel(call("get_calendar", {"area": {"id": "XA"}, "from": "2026-12", "to": "2027-02"}), say("Ok."))
    client = TestClient(create_app(store=marked, settings=Settings(anthropic_api_key=None), chat_model=model))
    got = parse_sse(client.post("/api/chats/new/messages", json={"text": "How far to trust the forecast and the splice?"}).text)
    assert got[-1][0] == "done"
    out = json.loads(model.tool_results(1)[0]["content"])
    months = {m["month"]: m for m in out["forecast"]["months"]}
    assert months["2026-12"] == {"month": "2026-12", "median": 22, "low": 11, "high": 33, "method": "model", "err_pct": 41.0}
    assert months["2027-01"]["method"] == "model" and months["2027-02"]["method"] == "climatology" and out["forecast"]["model_horizons"] == 2
    assert out["quality"]["seam"]["status"] == "fail" and out["seam_check"]["seam_2026"]["status"] == "fail"
    text = "Склейка 2026 года не проходит: отклонение 4,1 % при шуме 2,6 %; прогноз декабря по модели, ошибка 41 %."
    assert unverified(text, [out], []) == []
    assert unverified(text + " Скачок 9,9 раза.", [out], []) != []


def test_a_seam_file_with_missing_numbers_does_not_break_meta(store, tmp_path):
    head = dict(SEAM["headline"], placebo_gap_p90_abs_pct=None, placebo_typical_change_pct=None, status="insufficient",
                ours_gap_pct=float("nan"))
    new = dict(SEAM["seam_2026"], placebo_gap_p90_abs=None, status="insufficient")
    doc = dict(SEAM, headline=head, seam_2026=new, slices=[slice_of("world", "world", None, None, "insufficient", float("nan"))])
    marked = with_files(store, tmp_path, seam_doc=doc)
    res = TestClient(create_app(store=marked)).get("/api/meta")
    assert res.status_code == 200, res.text
    got = res.json()["seam"]
    assert (got["headline"]["gap_pct"], got["headline"]["threshold_pct"], got["headline"]["typical_change_pct"]) == (None, None, None)
    assert got["headline"]["status"] == "insufficient" and got["seam_2026"]["threshold_pct"] is None
    assert got["seam_2026"]["status"] == "insufficient"
    quality = board(marked, {"id": "WORLD"})["quality"]["seam"]
    assert quality["gap_pct"] is None and quality["as_is_jump"] is None and quality["status"] == "insufficient"
