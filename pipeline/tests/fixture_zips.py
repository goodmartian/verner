"""Builders of tiny FIRMS zips and API files for tests. `uv run python tests/fixture_zips.py <dir>` writes the
static scan fixtures to <dir> (tests/fixtures/zips)."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

VIIRS_HEAD = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight,type"
MODIS_HEAD = "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight,type"


def viirs(lat, lon, date, time, sat="N", conf="n", frp=1.5, dn="D", typ=0) -> str:
    return f"{lat},{lon},300.1,0.39,0.36,{date},{time},{sat},VIIRS,{conf},2,270.0,{frp},{dn},{typ}"


def modis(lat, lon, date, time, sat="Aqua", conf=60, frp=5.0, dn="D", typ=0) -> str:
    return f"{lat},{lon},302.1,1.1,1,{date},{time},{sat},MODIS,{conf},61.03,285.8,{frp},{dn},{typ}"


def write_zip(path: Path, members: dict[str, list[str]], head: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, rows in members.items():
            zf.writestr(name, "\n".join([head, *rows]) + "\n")
    return path


def write_api(path: Path, rows: list[str], head: str = VIIRS_HEAD, drop_type: bool = True) -> Path:
    """API file: NRT has no `type` column."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [head, *rows]
    if drop_type:
        lines = [",".join(line.split(",")[:-1]) for line in lines]
    path.write_text("\n".join(lines) + "\n")
    return path


def make_scan_fixtures(out: Path) -> None:
    """Two zips, two countries each. Counts used by test_scan are written next to every block."""
    # S-NPP 2025. Alpha: 2 distinct rows on 2025-04-01 and 1 on 2025-03-31 (a repeat of it is counted once);
    # dropped: low confidence, N21, type 3 sea row. Alpha static: one type 2 row. Beta: 1 row on 2025-04-01.
    alpha = [
        viirs(10.101, 20.101, "2025-03-31", "2000"),
        viirs(10.101, 20.101, "2025-03-31", "2000"),
        viirs(10.201, 20.201, "2025-04-01", "0100", conf="h", dn="N"),
        viirs(10.301, 20.301, "2025-04-01", "0100"),
        viirs(10.401, 20.401, "2025-04-01", "0100", conf="l"),
        viirs(10.501, 20.501, "2025-04-01", "0100", sat="N21"),
        viirs(11.001, 21.001, "2025-04-01", "0200", typ=2),
        viirs(11.501, 21.501, "2025-04-01", "0200", typ=3, conf="l"),
    ]
    beta = [viirs(-5.501, 30.501, "2025-04-01", "1230")]
    write_zip(
        out / "viirs-snpp_2025_fixture.zip",
        {"viirs-snpp/2025/viirs-snpp_2025_Alpha.csv": alpha, "viirs-snpp/2025/viirs-snpp_2025_Beta.csv": beta},
        VIIRS_HEAD,
    )
    # MODIS 2025. Gamma: Aqua conf 30 kept, conf 29 dropped, Terra kept as modis_terra, Aqua type 1 is static (conf 90).
    gamma = [
        modis(20.101, 40.101, "2025-04-01", "0916", conf=30),
        modis(20.201, 40.201, "2025-04-01", "0916", conf=29),
        modis(20.301, 40.301, "2025-04-01", "0916", sat="Terra"),
        modis(21.001, 41.001, "2025-04-01", "0916", conf=90, typ=1),
    ]
    delta = [modis(-30.101, 25.101, "2025-04-02", "1100", conf=85)]
    write_zip(
        out / "modis_2025_fixture.zip",
        {"modis/2025/modis_2025_Gamma.csv": gamma, "modis/2025/modis_2025_Delta.csv": delta},
        MODIS_HEAD,
    )


if __name__ == "__main__":
    make_scan_fixtures(Path(sys.argv[1]))
