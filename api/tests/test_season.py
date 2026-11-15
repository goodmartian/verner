from senda_api import season

MEDIANS = [1, 1, 1, 1, 1, 1, 10, 20, 10, 1, 1, 1]


def build(medians=MEDIANS, years=range(2010, 2020), cur=None, cur_counts=None):
    """Series, normals and yearly lists in the shapes the calendar passes to season.summarize."""
    series, yearly = [], []
    for y in years:
        total = 0
        for m, c in enumerate(medians, 1):
            series.append({"month": f"{y}-{m:02d}", "count": c, "partial": False, "ratio": 1.0, "level": 1})
            total += c
        yearly.append({"year": y, "count": total, "complete": True})
    normals = [{"month": m, "median": c, "years": len(list(years))} for m, c in enumerate(medians, 1)]
    if cur:
        total = 0
        for m, (c, partial) in enumerate(cur_counts, 1):
            series.append({"month": f"{cur}-{m:02d}", "count": c, "partial": partial, "ratio": 1.0, "level": 1})
            total += c
        yearly.append({"year": cur, "count": total, "complete": False})
    return series, normals, yearly


def test_season_months_rule():
    out = season.summarize(*build())
    assert out["season_months"] == [7, 8, 9]
    assert out["peak_month"] == {"month": 8, "median": 20}
    assert out["quiet_month"] == {"month": 1, "median": 1}
    assert out["average_year"] == 49
    assert out["season_share"] == round(40 / 49, 2) == 0.82
    assert out["season_strength"] == 20.0
    assert out["record_year"] == {"year": 2010, "count": 49}  # ties go to the earliest year
    assert out["quiet_year"] == {"year": 2010, "count": 49}


def test_season_threshold_is_125_percent_of_average_month():
    medians = [10] * 12
    out = season.summarize(*build(medians))
    assert out["season_months"] == []  # nothing stands out of a flat year
    assert out["season_share"] is None


def test_never_burned_area_has_empty_season():
    out = season.summarize(*build([0] * 12))
    assert out["season_months"] == [] and out["season_share"] is None
    assert out["average_year"] == 0 and out["season_strength"] == 0.0
    assert out["ytd"] is None and out["unusual_months"] == {"count": 0, "last": None}


def test_fewer_than_three_base_years_gives_none():
    assert season.summarize(*build(years=range(2010, 2012))) is None


def test_unusual_needs_ten():
    series, normals, yearly = build()
    series.append({"month": "2020-05", "count": 9, "partial": False, "ratio": 3.0, "level": 3})
    assert season.summarize(series, normals, yearly)["unusual_months"] == {"count": 0, "last": None}
    series.append({"month": "2020-06", "count": 10, "partial": False, "ratio": 3.0, "level": 3})
    series.append({"month": "2020-07", "count": 40, "partial": True, "ratio": 2.0, "level": 3})
    series.append({"month": "2020-08", "count": 50, "partial": False, "ratio": 1.9, "level": 2})
    assert season.summarize(series, normals, yearly)["unusual_months"] == {"count": 2, "last": "2020-07"}


def test_ytd_uses_last_complete_month_of_current_year():
    cur = [(5, False)] * 10 + [(3, True)]  # Jan-Oct complete, November still running
    out = season.summarize(*build(years=range(2018, 2026), cur=2026, cur_counts=cur))
    assert out["ytd"] == {"through": "2026-10", "count": 50, "last_year": 47, "ratio": 1.06}


def test_ytd_ratio_with_zero_last_year():
    cur = [(5, False)] * 2
    out = season.summarize(*build([0] * 12, years=range(2018, 2026), cur=2026, cur_counts=cur))
    assert out["ytd"]["last_year"] == 0 and out["ytd"]["ratio"] == 5 * 2 / 1
    out = season.summarize(*build([0] * 12, years=range(2018, 2026), cur=2026, cur_counts=[(0, False)]))
    assert out["ytd"]["ratio"] == 1.0


def test_ytd_none_when_no_complete_month_this_year():
    out = season.summarize(*build(years=range(2018, 2026), cur=2026, cur_counts=[(1, True)]))
    assert out["ytd"] is None
