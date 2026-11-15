"""Read FIRMS CSV (yearly country zips and API answers) and bring rows to one table."""

from __future__ import annotations

import io
import itertools
import re
import zipfile
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import polars as pl

from senda_pipeline import grid

NORM = [
    "lat", "lon", "acq_utc", "utc_date", "local_date", "month", "cell_id", "cell01",
    "sensor", "frp_mw", "confidence", "daynight", "type", "source",
]  # fmt: skip
REQUIRED = ["latitude", "longitude", "acq_date", "acq_time", "satellite", "confidence", "frp"]
OPTIONAL = ["daynight", "type"]
SENSORS = {
    "aqua": "modis_aqua", "a": "modis_aqua",
    "terra": "modis_terra", "t": "modis_terra",
    "n": "viirs_snpp", "npp": "viirs_snpp", "suomi-npp": "viirs_snpp",
    "n20": "viirs_noaa20", "noaa-20": "viirs_noaa20",
}  # fmt: skip
MODIS = ["modis_aqua", "modis_terra"]  # numeric confidence 0..100
VIIRS_CONF = {"l": "l", "low": "l", "n": "n", "nominal": "n", "h": "h", "high": "h"}
VIIRS_KEEP = ["n", "nominal", "h", "high"]
ACQ_UTC =pl.Datetime("ms", "UTC")

Source = Literal["sp", "nrt"]


def _read_csv(data: bytes) -> pl.DataFrame:
    """All columns as text (robust to leading zeros and missing columns); only the used ones are kept."""
    head = data[: data.find(b"\n") if b"\n" in data else len(data)].decode("utf-8-sig").strip()
    names = [c.strip() for c in head.split(",")]
    if "latitude" not in names:
        raise ValueError(f"not a FIRMS CSV: header starts with {head[:40]!r}")
    want = [c for c in REQUIRED + OPTIONAL if c in names]
    return pl.read_csv(io.BytesIO(data), columns=want, infer_schema_length=0)


def iter_zip(path: Path) -> Iterator[pl.DataFrame]:
    """One raw table per CSV (one country) in the zip, in name order. Empty files are skipped."""
    with zipfile.ZipFile(path) as zf:
        for name in sorted(n for n in zf.namelist() if n.lower().endswith(".csv")):
            data = zf.read(name)
            if len(data.strip()) == 0:
                continue
            df = _read_csv(data)
            del data
            if df.height:
                yield df


def read_api_csv(path: Path) -> pl.DataFrame:
    """Raw table of an API answer. Raises ValueError when the file is not CSV data (error text instead)."""
    return _read_csv(Path(path).read_bytes())


def normalize(df: pl.DataFrame, source: Source) -> pl.DataFrame:
    """Raw FIRMS table -> NORM columns. Applies sensor, confidence and duplicate rules, not the `type` filter."""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")
    if source not in ("sp", "nrt"):
        raise ValueError(f"unknown source: {source}")
    for c in OPTIONAL:
        if c not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.String).alias(c))

    sensor = pl.col("satellite").str.strip_chars().str.to_lowercase().replace_strict(SENSORS, default=None)
    conf = pl.col("confidence").str.strip_chars().str.to_lowercase()
    conf_num = conf.cast(pl.Float64, strict=False)
    hhmm = pl.col("acq_time").str.strip_chars().str.split(".").list.first().str.zfill(4)
    typ = pl.col("type").cast(pl.Float64, strict=False).cast(pl.Int8, strict=False) if source == "sp" else pl.lit(None, pl.Int8)

    out = (
        df.lazy()
        .select(
            pl.col("latitude").cast(pl.Float64, strict=False).alias("lat"),
            pl.col("longitude").cast(pl.Float64, strict=False).alias("lon"),
            (pl.col("acq_date").str.strip_chars() + " " + hhmm)
            .str.strptime(pl.Datetime("ms"), "%Y-%m-%d %H%M", strict=False)
            .dt.replace_time_zone("UTC")
            .alias("acq_utc"),
            sensor.alias("sensor"),
            pl.col("frp").cast(pl.Float64, strict=False).alias("frp_mw"),
            conf.alias("conf"),
            conf_num.alias("conf_num"),
            pl.col("daynight").str.strip_chars().str.to_uppercase().alias("daynight"),
            typ.alias("type"),
        )
        .filter(
            pl.col("lat").is_between(-90, 90)
            & pl.col("lon").is_between(-180, 180)
            & pl.col("acq_utc").is_not_null()
            & pl.col("sensor").is_not_null()
        )
        .filter(
            pl.when(pl.col("sensor").is_in(MODIS))
            .then(pl.col("conf_num") >= 30)
            .otherwise(pl.col("conf").is_in(VIIRS_KEEP))
        )
        .with_columns(
            pl.when(pl.col("sensor").is_in(MODIS))
            .then(pl.col("conf_num").cast(pl.Int32, strict=False).cast(pl.String))
            .otherwise(pl.col("conf").replace_strict(VIIRS_CONF, default=None))
            .alias("confidence"),
            pl.when(pl.col("frp_mw") >= 0).then(pl.col("frp_mw")).cast(pl.Float32).alias("frp_mw"),
            pl.lit(source).alias("source"),
        )
        .unique(subset=["sensor", "lat", "lon", "acq_utc"], keep="first", maintain_order=False)
        .with_columns(
            pl.col("acq_utc").dt.date().alias("utc_date"),
            grid.local_dt(pl.col("acq_utc"), pl.col("lon")).dt.date().alias("local_date"),
            grid.cell_id(pl.col("lat"), pl.col("lon")),
            grid.cell01(pl.col("lat"), pl.col("lon")),
        )
        .with_columns(grid.month_expr(pl.col("local_date")).alias("month"))
        .select(NORM)
        .collect()
    )
    return out


_API_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d+)\.csv$")


def api_window(path: Path) -> tuple[date, date] | None:
    """UTC dates covered by an API file named <start>_<days>.csv, or None for another name."""
    m = _API_NAME.match(path.name)
    if not m:
        return None
    start = date.fromisoformat(m.group(1))
    return start, start + timedelta(days=int(m.group(2)) - 1)


def _check_disjoint(folder: Path) -> None:
    """Two files of one source folder covering a common UTC day would count that day twice."""
    wins = sorted((w, f.name) for f in folder.glob("*.csv") if (w := api_window(f)))
    for (a, an), (b, bn) in itertools.pairwise(wins):
        if b[0] <= a[1]:
            raise ValueError(f"{folder.name}: {an} and {bn} cover the same day")


def source_of_api_dir(name: str) -> Source:
    """`VIIRS_NOAA20_SP` -> sp, `MODIS_NRT` -> nrt."""
    if name.endswith("_SP"):
        return "sp"
    if name.endswith("_NRT"):
        return "nrt"
    raise ValueError(f"unknown API source folder: {name}")


def require_archives(zips: Path) -> None:
    """Stops the run when the yearly FIRMS archives are not there (an empty folder, or a link that leads nowhere after
    the data was copied to another machine): without them only this year's API windows are read, the history is lost
    and the run fails much later with an error that names no cause."""
    if not any(Path(zips).rglob("*.zip")):
        raise SystemExit(f"no FIRMS archives (*.zip) in {zips}: put the yearly country archives there, or point "
                         "SENDA_ZIPS at them")


def iter_normalized(zips: Path, api_dir: Path) -> Iterator[tuple[str, Source, pl.DataFrame]]:
    """Walk zips, then API folders. Yields (group, source, normalized table); a group is one zip or one API folder.

    API rows outside the UTC window in the file name are dropped, so overlapping windows cannot count a row twice.
    Files that are not CSV data (an error text saved by mistake) are skipped with a warning.
    """
    for z in sorted(Path(zips).rglob("*.zip")):
        for raw in iter_zip(z):
            yield z.name, "sp", normalize(raw, "sp")
    if not Path(api_dir).is_dir():
        return
    for d in sorted(p for p in Path(api_dir).iterdir() if p.is_dir()):
        try:
            src = source_of_api_dir(d.name)
        except ValueError:
            continue
        _check_disjoint(d)
        for f in sorted(d.glob("*.csv")):
            try:
                raw = read_api_csv(f)
            except ValueError as e:
                print(f"warning: skipped {d.name}/{f.name}: {e}")
                continue
            if raw.is_empty():
                continue
            df = normalize(raw, src)
            win = api_window(f)
            if win:
                df = df.filter(pl.col("utc_date").is_between(*win))
            yield d.name, src, df
