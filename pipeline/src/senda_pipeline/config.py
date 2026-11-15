"""Paths and environment of the pipeline. Secrets are read here and never logged."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def load_env(path: Path | None = None) -> None:
    """Read KEY=VALUE lines of the repository .env into os.environ without overriding set variables."""
    env = path or REPO / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value:
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Paths:
    """Folders under the data root: data/_work (intermediate), data/versions, data/current."""

    root: Path

    @property
    def work(self) -> Path:
        return self.root / "_work"

    @property
    def built(self) -> Path:
        return self.work / "built"

    @property
    def api(self) -> Path:
        return self.work / "api"

    @property
    def versions(self) -> Path:
        return self.root / "versions"

    @property
    def current(self) -> Path:
        return self.root / "current"

    @property
    def zips(self) -> Path:
        return Path(os.environ.get("SENDA_ZIPS") or self.work / "zips")

    @property
    def geo(self) -> Path:
        return Path(os.environ.get("SENDA_GEO") or self.work / "geo")


def paths(data_root: str | Path) -> Paths:
    load_env()
    return Paths(Path(data_root).expanduser().resolve())


def firms_key() -> str:
    load_env()
    key = os.environ.get("FIRMS_MAP_KEY", "")
    if not key:
        raise SystemExit("FIRMS_MAP_KEY is not set. Put it into .env.")
    return key


def copernicus_key() -> str:
    """The Copernicus CDS token from .env, or "" when it is not set (the climate command then skips)."""
    load_env()
    return os.environ.get("COPERNICUS_API_KEY", "")


def prune_dirs(folder: Path, pattern: re.Pattern[str], keep: set[str], newest: int = 0) -> None:
    """Delete the sub-folders of `folder` whose names match `pattern`, except those in `keep` and the `newest` last by name."""
    names = sorted(p.name for p in folder.iterdir() if p.is_dir() and not p.is_symlink() and pattern.fullmatch(p.name))
    for name in set(names[: len(names) - newest] if newest else names) - keep:
        shutil.rmtree(folder / name)
