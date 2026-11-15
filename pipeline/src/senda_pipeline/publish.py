"""senda-pipeline publish: copy a finished build into versions/<version>/ and switch the `current` symlink."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from . import chain, config, fit

TOP_FILES = (
    "cells.parquet",
    "regions.parquet",
    "monthly.parquet",
    "series_monthly.parquet",
    "factors.parquet",
    "cell_groups.parquet",
    "harmonization.json",
    "seam.json",
    "events.json",
)
TOP_DIRS = ("series_daily", "rows")
VERSION_NAME = re.compile(r"\d{8}-[0-9a-f]{12}")
RETIRED = {"viirs_snpp": "2026-11-02"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _month_text(m: int) -> str:
    return f"{2000 + m // 12:04d}-{m % 12 + 1:02d}"


def _stats(folder: Path) -> dict:
    sm = pl.scan_parquet(folder / "series_monthly.parquet")
    cells = pl.scan_parquet(folder / "cells.parquet").select("cell_id")
    total = sm.select(pl.len()).collect().item()
    outside = sm.join(cells, on="cell_id", how="anti").select(pl.len()).collect().item()
    hotspots = sm.select((pl.col("n_day").cast(pl.Int64) + pl.col("n_night").cast(pl.Int64)).sum()).collect().item()
    return {
        "series_monthly_rows": total,
        "outside_land": outside,
        "series_hotspots": hotspots or 0,
        "cells": cells.select(pl.len()).collect().item(),
        "kgroups": pl.scan_parquet(folder / "cell_groups.parquet").select(pl.col("kgroup").n_unique()).collect().item(),
    }


def _manifest(folder: Path, version: str, files: dict[str, str]) -> dict:
    days = pl.read_parquet(folder / "days.parquet")
    last_complete = chain.last_complete_date(days)
    sensors = {}
    for sensor in sorted(days["sensor"].unique().to_list()):
        seen = days.filter((pl.col("sensor") == sensor) & (pl.col("rows") > 0))["utc_date"]
        sensors[sensor] = {
            "first": seen.min().isoformat() if len(seen) else None,
            "last": seen.max().isoformat() if len(seen) else None,
            "retired_at": RETIRED.get(sensor),
        }
    first_month = pl.scan_parquet(folder / "series_monthly.parquet").select(pl.col("month").min()).collect().item()
    if first_month is not None:  # the series starts at chain.SERIES_START (the first month of MODIS Terra)
        start = chain.SERIES_START
        first_month = max(int(first_month), (start.year - 2000) * 12 + start.month - 1)
    return {
        "version": version,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "last_complete_date": last_complete.isoformat(),
        "first_month": None if first_month is None else _month_text(int(first_month)),
        "sensors": sensors,
        "incomplete_months": chain.incomplete_months(days, chain.SERIES_START, last_complete + timedelta(days=1)),
        "gap_dates": [d.isoformat() for d in chain.gap_dates(days)],
        "stats": _stats(folder),
        "files": files,
    }


def _sources(work: Path) -> dict[str, Path]:
    built = work / "built"
    out = {name: built / name for name in TOP_FILES if (built / name).exists()}
    for folder in TOP_DIRS:
        for path in sorted((built / folder).rglob("*.parquet")):
            out[path.relative_to(built).as_posix()] = path
    out["days.parquet"] = work / "days.parquet"
    missing = [n for n in ("cells.parquet", "series_monthly.parquet", "factors.parquet", "cell_groups.parquet", "harmonization.json", "days.parquet") if n not in out or not out[n].exists()]
    if missing:
        raise FileNotFoundError(f"cannot publish, missing: {', '.join(missing)}")
    return out


def run(work: Path, data_root: Path) -> str:
    """Copy the build into versions/<version>/, write manifest.json last, switch `current`. Returns the version."""
    versions = data_root / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    tmp = versions / f".tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        for rel, src in _sources(work).items():
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, tmp / rel)
        hashes = {rel: sha256(tmp / rel) for rel in sorted(p.relative_to(tmp).as_posix() for p in tmp.rglob("*") if p.is_file())}
        digest = hashlib.sha256("\n".join(f"{rel} {h}" for rel, h in hashes.items()).encode()).hexdigest()[:12]
        last_complete = chain.last_complete_date(pl.read_parquet(tmp / "days.parquet"))
        version = f"{last_complete:%Y%m%d}-{digest}"
        harm = json.loads((tmp / "harmonization.json").read_text())
        harm["version"] = version
        fit.write_json(tmp / "harmonization.json", harm)
        hashes["harmonization.json"] = sha256(tmp / "harmonization.json")
        fit.write_json(tmp / "manifest.json", _manifest(tmp, version, hashes))
        final = versions / version
        if final.exists():
            shutil.rmtree(tmp)
        else:
            tmp.rename(final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    old = data_root / "current"
    previous = old.resolve().name if old.is_symlink() else None
    if previous == version:
        print(f"up to date: {version}")
        return version
    link = data_root / ".current.tmp"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(Path("versions") / version)
    current = data_root / "current"
    if current.exists() and not current.is_symlink():
        link.unlink()
        raise SystemExit(f"{current} is not a symlink; move it away first")
    os.replace(link, current)
    # the new version and the one it replaced stay, older ones go; only version-named folders are touched
    config.prune_dirs(versions, VERSION_NAME, {version, previous or version})
    return version


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="senda-pipeline publish")
    ap.add_argument("--data", required=True, help="data root")
    args = ap.parse_args(argv)
    p = config.paths(args.data)
    print(run(p.work, p.root))
    return 0

