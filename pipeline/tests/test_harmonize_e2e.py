import json
import shutil

import numpy as np
import polars as pl
import pytest
import synth

from senda_pipeline import harmonize

SETS = {("modis_aqua", "era"), ("modis_aqua", "recent"), ("viirs_noaa20", "era"), ("modis_terra", "era")}
COUNTRY_K = {"AA": 6.0, "BB": 2.0}


def strict_json(path):
    def refuse(token):
        raise ValueError(f"NaN in JSON: {token}")

    return json.loads(path.read_text(), parse_constant=refuse)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    work = synth.write_work(tmp_path_factory.mktemp("zone"))
    harmonize.run(work)
    return work / "built"


@pytest.fixture(scope="module")
def built_country(tmp_path_factory):
    work = synth.write_work(tmp_path_factory.mktemp("country"), k_fn=lambda z, c, cm, dn: COUNTRY_K.get(c, 3.0))
    harmonize.run(work)
    return work / "built"


def kgroup_of(h, zone, country=None):
    return next(g["id"] for g in h["kgroups"] if g["zone"] == zone and g["country"] == country)


def test_factors_complete(built):
    f = pl.read_parquet(built / "factors.parquet")
    groups = f["kgroup"].unique().to_list()
    assert groups == list(range(len(groups)))
    assert f.height == len(groups) * 24 * len(SETS)
    for (sensor, window), part in f.group_by("sensor", "window"):
        assert (sensor, window) in SETS
        assert part.height == len(groups) * 24
        assert part.select("kgroup", "calmonth", "dn").unique().height == part.height
    assert {(s, w) for s, w in f.select("sensor", "window").unique().iter_rows()} == SETS
    assert f["k"].is_nan().sum() == 0 and f["k"].is_null().sum() == 0 and (f["k"] > 0).all()
    assert set(f["dn"].unique()) == {"D", "N"} and set(f["calmonth"].unique()) == set(range(1, 13))
    assert set(f["basis"].unique()) <= {"zone_month", "zone", "global", "country"}
    assert f.schema["kgroup"] == pl.Int32 and f.schema["calmonth"] == pl.Int8 and f.schema["k"] == pl.Float32


def test_factors_recover_the_truth(built):
    h = strict_json(built / "harmonization.json")
    f = pl.read_parquet(built / "factors.parquet")

    def ks(zone, sensor, window):
        g = kgroup_of(h, zone)
        return f.filter((pl.col("kgroup") == g) & (pl.col("sensor") == sensor) & (pl.col("window") == window))["k"]

    for zone, truth in (("resolve-01-n", 4.0), ("resolve-02-n", 3.0)):
        assert np.allclose(ks(zone, "modis_aqua", "era").to_numpy(), truth, rtol=1e-6)
        assert np.allclose(ks(zone, "modis_aqua", "recent").to_numpy(), truth, rtol=1e-6)
        assert np.allclose(ks(zone, "viirs_noaa20", "era").to_numpy(), 1.0, rtol=1e-6)
        assert np.allclose(ks(zone, "modis_terra", "era").to_numpy(), truth, rtol=1e-6)
    assert h["selection"]["bridge_window"] in ("all", "last3")
    assert h["selection"]["countries_used"] == 0  # exact data: the zone model leaves nothing to gain


def test_harmonization_json_schema(built):
    h = strict_json(built / "harmonization.json")
    assert {"version", "reference", "ladder", "selection", "validation", "country_decisions", "error_curve", "confidence_thresholds", "summary"} <= set(h)
    assert h["reference"] == "viirs_snpp"
    assert [r["level"] for r in h["ladder"]] == ["L0", "L1", "L2", "L3", "L4", "L5"]
    assert sum(r["chosen"] for r in h["ladder"]) == 1
    assert {"loyo_zone_wape", "loyo_country_wape", "forward_zone_wape", "forward_country_wape"} <= set(h["ladder"][0])
    assert {"lambda", "lambda_scores", "daynight", "bridge_window", "countries_used", "rules"} <= set(h["selection"])
    assert h["confidence_thresholds"] == {"high_wape": 0.15, "medium_wape": 0.35, "high_unharmonized_share": 0.05, "medium_unharmonized_share": 0.20}
    assert {"loyo_zone_wape_median", "forward_zone_wape_median", "naive_zone_wape_median", "zones_supported"} == set(h["summary"])
    assert h["summary"]["naive_zone_wape_median"] == pytest.approx(h["ladder"][0]["loyo_zone_wape"])
    assert {r["scenario"] for r in h["validation"]} == {"loyo", "forward", "bridge_loyo", "bridge_forward", "recent_forward", "terra_loyo"}
    assert {"scenario", "level", "entity", "wape", "bias", "spearman", "sign", "n_months", "actual", "mean_monthly_count"} <= set(h["validation"][0])
    assert h["error_curve"] and set(h["error_curve"][0]) == {"mean_monthly_count", "wape", "samples"}
    assert h["version"] == ""  # publish fills it in
    assert h["diagnostics"]["pair_rows_outside_cells"] == {
        "modis_aqua__viirs_snpp": 0, "viirs_noaa20__viirs_snpp": 0, "modis_terra__viirs_snpp": 0
    }
    zones = {r["entity"] for r in h["validation"] if r["level"] == "zone" and r["scenario"] == "loyo"}
    assert zones == {"resolve-01-n", "resolve-02-n"}


def test_terra_pair_is_fitted_and_checked_against_aqua(built):
    h = strict_json(built / "harmonization.json")
    t = h["terra"]
    assert t["limits"] == {"loyo_zone_wape": 0.15, "vs_aqua_world_bias_pct": 10.0, "vs_aqua_zone_wape": 0.20}
    assert [r["level"] for r in t["ladder"]] == ["L0", "L1", "L2", "L3", "L4", "L5"]
    # the same pair as Aqua: the same leave-one-year-out error
    aqua_loyo = sorted(r["wape"] for r in h["validation"] if r["scenario"] == "loyo" and r["level"] == "zone")
    terra_loyo = sorted(r["wape"] for r in h["validation"] if r["scenario"] == "terra_loyo" and r["level"] == "zone")
    assert terra_loyo == pytest.approx(aqua_loyo)
    assert t["terra_loyo"]["zone_wape_median"] == pytest.approx(float(np.median(aqua_loyo)))
    vs = t["terra_vs_aqua"]
    assert vs["months"] == ["2003-01", "2011-12"] and vs["n_months"] == 108
    # equal counts and equal factors: no error, no bias
    assert vs["world_bias_pct"] == pytest.approx(0.0, abs=1e-9) and vs["zone_wape_median"] == pytest.approx(0.0, abs=1e-9)
    assert t["accepted"] is True


def test_terra_rule():
    ok = {"world_bias_pct": -9.9, "zone_wape_median": 0.2}
    assert harmonize.terra_accepted(0.15, ok)
    assert not harmonize.terra_accepted(0.151, ok)
    assert not harmonize.terra_accepted(0.1, {**ok, "world_bias_pct": 10.5})
    assert not harmonize.terra_accepted(0.1, {**ok, "zone_wape_median": 0.21})
    assert not harmonize.terra_accepted(None, ok)


def test_ladder_error_falls_on_the_pipeline_data(built):
    h = strict_json(built / "harmonization.json")
    row = {r["level"]: r for r in h["ladder"]}
    assert row["L0"]["loyo_zone_wape"] > 0.5 and row["L3"]["loyo_zone_wape"] < 1e-6


def test_mean_monthly_count_is_the_raw_reference_count(built):
    """The axis of the error curve comes from monthly.parquet: raw viirs_snpp counts, 2012-02 to 2021-12."""
    h = strict_json(built / "harmonization.json")
    monthly = pl.read_parquet(built / "monthly.parquet").filter(pl.col("sensor") == "viirs_snpp")
    cells = pl.read_parquet(built / "cells.parquet")
    window = monthly.filter(pl.col("month").is_between((2012 - 2000) * 12 + 1, (2021 - 2000) * 12 + 11))
    want = (
        window.join(cells, on="cell_id").filter(pl.col("zone") == "resolve-01-n").select((pl.col("n_day") + pl.col("n_night")).sum()).item()
        / 119
    )
    got = next(r["mean_monthly_count"] for r in h["validation"] if r["level"] == "zone" and r["entity"] == "resolve-01-n" and r["scenario"] == "loyo")
    assert got == pytest.approx(want)


def test_cell_groups_cover_every_cell(built):
    cells = pl.read_parquet(built / "cells.parquet")
    cg = pl.read_parquet(built / "cell_groups.parquet")
    assert cg.height == cells.height and cg.schema == {"cell_id": pl.Int32, "kgroup": pl.Int32}
    assert set(cg["cell_id"]) == set(cells["cell_id"])
    h = strict_json(built / "harmonization.json")
    none_cells = cells.filter(pl.col("zone") == "none")["cell_id"]
    assert set(cg.filter(pl.col("cell_id").is_in(none_cells.to_list()))["kgroup"]) == {kgroup_of(h, "global")}
    assert set(cg["kgroup"]) <= set(pl.read_parquet(built / "factors.parquet")["kgroup"])


def test_a_country_that_gains_gets_its_own_group(built_country):
    h = strict_json(built_country / "harmonization.json")
    used = {d["country"] for d in h["country_decisions"] if d["use"]}
    assert used == {"AA", "BB"} and h["selection"]["countries_used"] == 2
    f = pl.read_parquet(built_country / "factors.parquet")
    for country, truth in COUNTRY_K.items():
        g = kgroup_of(h, "resolve-01-n", country)
        era = f.filter((pl.col("kgroup") == g) & (pl.col("sensor") == "modis_aqua") & (pl.col("window") == "era"))
        assert np.allclose(era["k"].to_numpy(), truth, rtol=1e-3) and set(era["basis"]) == {"country"}
        bridge = f.filter((pl.col("kgroup") == g) & (pl.col("sensor") == "viirs_noaa20"))
        assert np.allclose(bridge["k"].to_numpy(), 1.0, rtol=1e-6)  # bridge has no country rule: copies the zone
    cells = pl.read_parquet(built_country / "cells.parquet")
    cg = pl.read_parquet(built_country / "cell_groups.parquet").join(cells, on="cell_id")
    assert cg.filter(pl.col("country") == "AA")["kgroup"].n_unique() == 1
    assert cg.filter(pl.col("country") == "AA")["kgroup"][0] == kgroup_of(h, "resolve-01-n", "AA")
    assert cg.filter(pl.col("country") == "CC")["kgroup"][0] == kgroup_of(h, "resolve-02-n")
    # validation of a used country follows the rule that would have applied
    rows = [r for r in h["validation"] if r["scenario"] == "loyo" and r["level"] == "country" and r["entity"] in COUNTRY_K]
    assert rows and all(r["wape"] < 0.02 for r in rows)


def test_run_is_deterministic(built, tmp_path):
    before = (built / "harmonization.json").read_bytes()
    work = built.parent
    harmonize.run(work)
    assert (built / "harmonization.json").read_bytes() == before


def test_apply_only_rewrites_only_cell_groups(built, tmp_path):
    work = tmp_path / "w"
    shutil.copytree(built.parent, work)
    current = tmp_path / "current"
    current.mkdir()
    shutil.copyfile(built / "factors.parquet", current / "factors.parquet")
    shutil.copyfile(built / "harmonization.json", current / "harmonization.json")
    (work / "built" / "cell_groups.parquet").unlink()
    (work / "built" / "factors.parquet").unlink()
    (work / "built" / "harmonization.json").unlink()
    harmonize.apply_only(work, current)
    assert (work / "built" / "factors.parquet").read_bytes() == (built / "factors.parquet").read_bytes()
    assert (work / "built" / "harmonization.json").read_bytes() == (built / "harmonization.json").read_bytes()
    assert pl.read_parquet(work / "built" / "cell_groups.parquet").equals(pl.read_parquet(built / "cell_groups.parquet"))


def test_apply_only_needs_a_current_version(tmp_path):
    work = synth.write_work(tmp_path)
    with pytest.raises(SystemExit):
        harmonize.apply_only(work, tmp_path / "nothing")


def test_cli_apply_only(tmp_path):
    """`harmonize --data D` then `--apply-only` through the command line entry point."""
    work = synth.write_work(tmp_path, work_name="_work")
    assert harmonize.main(["--data", str(tmp_path)]) == 0
    (tmp_path / "versions" / "v").mkdir(parents=True)
    for name in ("factors.parquet", "harmonization.json"):
        shutil.copyfile(work / "built" / name, tmp_path / "versions" / "v" / name)
    (tmp_path / "current").symlink_to(tmp_path / "versions" / "v")
    (work / "built" / "cell_groups.parquet").unlink()
    assert harmonize.main(["--data", str(tmp_path), "--apply-only"]) == 0
    assert (work / "built" / "cell_groups.parquet").exists()

