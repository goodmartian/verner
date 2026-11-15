"""senda-pipeline verify: integrity checks of a published version. Returns a list of violations, empty when fine."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from . import chain, config, publish

OUTSIDE_LAND_MAX = 0.001
LADDER = ["L0", "L1", "L2", "L3", "L4", "L5"]
FACTOR_SETS = (("modis_aqua", "era"), ("modis_aqua", "recent"), ("viirs_noaa20", "era"), ("modis_terra", "era"))
HARMONIZATION_KEYS = ("version", "reference", "ladder", "selection", "validation", "error_curve", "confidence_thresholds", "summary")
EVENT_KEYS = {"id", "region_id", "month", "found"}
FORECAST_FILES = ("forecast.json", "forecast.parquet")
READY_FILE = "READY"  # the empty mark `update.sh` puts into a finished version for the API; a later run finds it there
FORECAST_KEYS = {"version", "trained_at", "trained_through", "train_rows", "method_default", "model", "rule", "tables", "validated", "use_model"}
FORECAST_COLUMNS = ["region_id", "month", "horizon", "p10", "p50", "p90", "method", "err_pct"]
REGIONS_COLUMNS = {"id", "kind", "country_id", "names_json", "bbox", "area_km2", "geometry_wkb"}

I32, I16, I8, F32, STR = pl.Int32, pl.Int16, pl.Int8, pl.Float32, pl.String
SCHEMAS = {
    "cells.parquet": {"cell_id": I32, "lat": F32, "lon": F32, "zone": STR, "country": STR, "land_frac": F32},
    "days.parquet": {"utc_date": pl.Date, "sensor": STR, "rows": I32, "ok": pl.Boolean, "chosen": pl.Boolean, "source": STR},
    "monthly.parquet": {"cell_id": I32, "month": I16, "sensor": STR, "n_day": I32, "n_night": I32, "frp_mw": F32},
    "series_monthly.parquet": {
        "cell_id": I32, "month": I16, "sensor": STR, "n_day": I32, "n_night": I32, "frp_day": F32, "frp_night": F32,
    },
    "factors.parquet": {"kgroup": I32, "sensor": STR, "calmonth": I8, "dn": STR, "window": STR, "k": F32, "basis": STR},
    "cell_groups.parquet": {"cell_id": I32, "kgroup": I32},
}
SERIES_DAILY = {"cell_id": I32, "local_date": pl.Date, "sensor": STR, "n_day": I32, "n_night": I32}
ROWS = {
    "lat": F32, "lon": F32, "acq_utc": pl.Datetime("ms", "UTC"), "local_date": pl.Date, "sensor": STR,
    "frp_mw": F32, "confidence": STR, "daynight": STR, "source": STR,
}
REQUIRED = ("cells.parquet", "regions.parquet", "days.parquet", "monthly.parquet", "series_monthly.parquet", "factors.parquet", "cell_groups.parquet", "harmonization.json")


def _schema_problem(path: Path, expected: dict, label: str) -> list[str]:
    try:
        got = dict(pl.read_parquet_schema(path))
    except pl.exceptions.PolarsError as exc:
        return [f"{label} cannot be read: {exc}"]
    if got == expected or (set(got) == set(expected) and all(got[k] == expected[k] for k in expected)):
        return []
    diff = [f"{k}: {got.get(k)} != {v}" for k, v in expected.items() if got.get(k) != v]
    diff += [f"extra column {k}" for k in got if k not in expected]
    return [f"schema {label}: " + "; ".join(diff)]


def check_files(folder: Path) -> list[str]:
    out = [f"missing {name}" for name in REQUIRED if not (folder / name).exists()]
    for name, expected in SCHEMAS.items():
        if (folder / name).exists():
            out += _schema_problem(folder / name, expected, name)
    if (folder / "regions.parquet").exists():
        cols = set(pl.read_parquet_schema(folder / "regions.parquet"))
        if cols != REGIONS_COLUMNS:
            out.append(f"schema regions.parquet: columns {sorted(cols)}")
    for sub, expected, pattern in (("series_daily", SERIES_DAILY, "year=*/part-*.parquet"), ("rows", ROWS, "year=*/tile=*/part-*.parquet")):
        files = sorted((folder / sub).glob(pattern))
        if not files:
            out.append(f"missing {sub}/")
        for f in files:
            out += _schema_problem(f, expected, f.relative_to(folder).as_posix())
    if (folder / "events.json").exists():
        try:
            events = json.loads((folder / "events.json").read_text())
        except ValueError:
            events = None
            out.append("events.json is not valid JSON")
        if events is not None and not (
            isinstance(events, list)
            and all(isinstance(e, dict) and EVENT_KEYS <= set(e) for e in events)
        ):
            out.append("events.json must be a list of objects with id, region_id, month, found")
    return out


def check_forecast(folder: Path, manifest: dict) -> list[str]:
    """forecast.json and forecast.parquet are optional (the `forecast` command writes them after publish); when they
    are there they must belong to this version and say what the API reads."""
    out = []
    path = folder / "forecast.json"
    if not path.exists() and not (folder / "forecast.parquet").exists():
        return out
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return ["forecast.json is missing or not valid JSON"]
    if not isinstance(doc, dict) or not FORECAST_KEYS <= set(doc):
        return [f"forecast.json lacks keys {sorted(FORECAST_KEYS - set(doc)) if isinstance(doc, dict) else 'all'}"]
    if doc["version"] != manifest.get("version"):
        out.append("forecast.json belongs to another version")
    if doc["method_default"] != "climatology":
        out.append("forecast.json: method_default must be climatology")
    table = folder / "forecast.parquet"
    if not table.exists():
        return [*out, "forecast.parquet is missing"]
    frame = pl.read_parquet(table)
    if frame.columns != FORECAST_COLUMNS:
        out.append(f"forecast.parquet: columns {frame.columns}")
    elif frame.height and (not (frame["method"] == "model").all() or frame["p50"].is_null().any()):
        out.append("forecast.parquet holds rows that are not a model forecast")
    else:
        for region, flags in doc["use_model"].items():
            k = sum(flags)
            if flags != [True] * k + [False] * (len(flags) - k) or doc.get("model_horizons", {}).get(region) != k:
                out.append(f"forecast.json: use_model of {region} is not a prefix of horizons or differs from model_horizons")
                break
        horizons = doc["model"].get("horizons", [])
        flagged = {(r, horizons[i]) for r, flags in doc["use_model"].items() for i, on in enumerate(flags) if on and i < len(horizons)}
        if flagged != set(zip(frame["region_id"].to_list(), frame["horizon"].to_list(), strict=True)):
            out.append("forecast.parquet rows differ from use_model of forecast.json")
    return out


def check_hashes(folder: Path, manifest: dict) -> list[str]:
    out = []
    listed = manifest.get("files", {})
    for rel, digest in listed.items():
        path = folder / rel
        if not path.exists():
            out.append(f"manifest lists {rel} but it is missing")
        elif publish.sha256(path) != digest:
            out.append(f"sha256 of {rel} differs from the manifest")
    present = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()} - {"manifest.json", "events.json", *FORECAST_FILES, READY_FILE}  # written after publish: events by the API script, forecast by `forecast`, the mark by update.sh
    out += [f"{rel} is not in the manifest" for rel in sorted(present - set(listed))]
    return out


def check_outside_land(folder: Path, manifest: dict) -> list[str]:
    sm = pl.scan_parquet(folder / "series_monthly.parquet")
    cells = pl.scan_parquet(folder / "cells.parquet").select("cell_id")
    total = sm.select(pl.len()).collect().item()
    outside = sm.join(cells, on="cell_id", how="anti").select(pl.len()).collect().item()
    out = []
    if total and outside / total > OUTSIDE_LAND_MAX:
        out.append(f"{outside} of {total} series_monthly rows are outside cells.parquet (limit 0.1 percent)")
    if manifest.get("stats", {}).get("outside_land") != outside:
        out.append(f"stats.outside_land is {manifest.get('stats', {}).get('outside_land')}, counted {outside}")
    return out


def check_sums(folder: Path) -> list[str]:
    month = pl.scan_parquet(folder / "series_monthly.parquet").group_by(
        (pl.col("month").cast(pl.Int32) // 12 + 2000).alias("year"), "sensor"
    ).agg((pl.col("n_day").cast(pl.Int64) + pl.col("n_night").cast(pl.Int64)).sum().alias("monthly"))
    day = pl.scan_parquet(str(folder / "series_daily" / "year=*" / "part-*.parquet"), hive_partitioning=False).group_by(
        pl.col("local_date").dt.year().cast(pl.Int32).alias("year"), "sensor"
    ).agg((pl.col("n_day").cast(pl.Int64) + pl.col("n_night").cast(pl.Int64)).sum().alias("daily"))
    both = month.join(day, on=["year", "sensor"], how="full", coalesce=True).fill_null(0).filter(pl.col("monthly") != pl.col("daily")).collect()
    return [f"series sums differ in {r['year']} {r['sensor']}: monthly {r['monthly']}, daily {r['daily']}" for r in both.iter_rows(named=True)]


def check_chosen(folder: Path) -> list[str]:
    days = pl.read_parquet(folder / "days.parquet")
    bad = days.group_by("utc_date").agg(pl.col("chosen").sum().alias("n")).filter(pl.col("n") > 1)
    return [f"{bad.height} dates have more than one chosen sensor, first {bad['utc_date'].min()}"] if bad.height else []


def check_factors(folder: Path) -> list[str]:
    factors = pl.read_parquet(folder / "factors.parquet")
    groups = pl.read_parquet(folder / "cell_groups.parquet")
    cells = pl.read_parquet(folder / "cells.parquet", columns=["cell_id"])
    out = []
    uncovered = cells.join(groups, on="cell_id", how="anti").height
    if uncovered:
        out.append(f"{uncovered} cells have no kgroup in cell_groups.parquet")
    need = groups.select("kgroup").unique()
    per = factors.group_by("kgroup", "sensor", "window").agg(
        pl.len().alias("n"),
        pl.struct("calmonth", "dn").n_unique().alias("u"),
        (pl.col("k").is_nan() | pl.col("k").is_null() | (pl.col("k") <= 0)).sum().alias("bad"),
    )
    for sensor, window in FACTOR_SETS:
        part = per.filter((pl.col("sensor") == sensor) & (pl.col("window") == window))
        missing = need.join(part.filter((pl.col("n") == 24) & (pl.col("u") == 24)), on="kgroup", how="anti").height
        if missing:
            out.append(f"{missing} kgroups lack a complete factor set for {sensor} {window}")
        bad = part.filter(pl.col("bad") > 0).height
        if bad:
            out.append(f"{bad} kgroups have a missing or non positive k for {sensor} {window}")
    return out


def _months_around(d: date) -> set[tuple[int, int]]:
    return {((x := d + timedelta(days=i)).year, x.month) for i in (-1, 0, 1)}


def check_incomplete(folder: Path, manifest: dict) -> list[str]:
    days = pl.read_parquet(folder / "days.parquet")
    chosen = set(days.filter(pl.col("chosen"))["utc_date"].to_list())
    if not chosen:
        return ["days.parquet has no chosen date"]
    last, start = max(chosen), chain.SERIES_START
    missing, d = [], start - timedelta(days=1)
    while d <= last + timedelta(days=1):
        if d not in chosen:
            missing.append(d)
        d += timedelta(days=1)
    expected = {m for g in missing for m in _months_around(g) if (start.year, start.month) <= m <= (last.year, last.month)}
    listed = {(int(s[:4]), int(s[5:7])) for s in manifest.get("incomplete_months", [])}
    out = []
    if listed != expected:
        fmt = lambda s: sorted(f"{y:04d}-{m:02d}" for y, m in s)
        out.append(f"incomplete_months differ from the dates: unexpected {fmt(listed - expected)}, missing {fmt(expected - listed)}")
    gaps = [g.isoformat() for g in missing if start <= g <= last]
    if manifest.get("gap_dates") != gaps:
        out.append("gap_dates differ from the dates of days.parquet")
    return out


def check_harmonization(folder: Path, manifest: dict) -> list[str]:
    try:
        h = json.loads((folder / "harmonization.json").read_text())
    except ValueError:
        return ["harmonization.json is not valid JSON"]
    out = [f"harmonization.json lacks {k}" for k in HARMONIZATION_KEYS if k not in h]
    levels = [r.get("level") for r in h.get("ladder", [])]
    if levels != LADDER:
        out.append(f"harmonization.json ladder levels are {levels}, expected {LADDER}")
    elif sum(bool(r.get("chosen")) for r in h["ladder"]) != 1:
        out.append("harmonization.json ladder must have exactly one chosen step")
    if h.get("version") != manifest.get("version"):
        out.append("harmonization.json version differs from the manifest")
    return out


def run(version_dir: Path) -> list[str]:
    """All violations found in `version_dir`; an empty list means the version is sound."""
    version_dir = Path(version_dir)
    if not (version_dir / "manifest.json").exists():
        return ["manifest.json is missing: the version was not completed"]
    manifest = json.loads((version_dir / "manifest.json").read_text())
    out: list[str] = []

    def guarded(check) -> None:
        try:
            out.extend(check())
        except Exception as exc:  # noqa: BLE001 - a broken file is a violation, not a crash
            out.append(f"check failed: {type(exc).__name__}: {exc}")

    guarded(lambda: check_files(version_dir))
    guarded(lambda: check_hashes(version_dir, manifest))
    guarded(lambda: check_forecast(version_dir, manifest))
    if any(v.startswith("missing") for v in out):
        return out
    for check in (
        lambda: check_outside_land(version_dir, manifest),
        lambda: check_sums(version_dir),
        lambda: check_chosen(version_dir),
        lambda: check_factors(version_dir),
        lambda: check_incomplete(version_dir, manifest),
        lambda: check_harmonization(version_dir, manifest),
    ):
        guarded(check)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline verify")
    ap.add_argument("--data", required=True, help="data root")
    ap.add_argument("--version", help="version name under versions/; default is current")
    args = ap.parse_args(argv)
    p = config.paths(args.data)
    folder = p.versions / args.version if args.version else p.current.resolve()
    violations = run(folder)
    for v in violations:
        print(v, file=sys.stderr)
    print("ok" if not violations else f"{len(violations)} violations", folder.name)
    return 1 if violations else 0
