"""Runtime settings. Values come from the environment. The model key is read here and never printed."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _data_dir() -> Path:
    return Path(os.environ.get("SENDA_DATA", "../data/current"))


def _weather_dir() -> Path | None:
    found = os.environ.get("SENDA_WEATHER")
    return Path(found) if found else None


def _climate_dir() -> Path | None:
    found = os.environ.get("SENDA_CLIMATE")
    return Path(found) if found else None


def _reload_every() -> float:
    return float(os.environ.get("SENDA_RELOAD_S", "60"))


def _max_rows() -> int:
    # one year of the whole world is up to 19 million rows; two years, or all of them, are refused by this alone
    return int(os.environ.get("SENDA_MAX_EXPORT_ROWS", "20000000"))


def _export_per_hour() -> int:
    return int(os.environ.get("SENDA_EXPORT_PER_HOUR", "10"))


def _export_rows_per_day() -> int:
    return int(os.environ.get("SENDA_EXPORT_ROWS_PER_DAY", "200000000"))


def _chat_model() -> str:
    return os.environ.get("SENDA_CHAT_MODEL", "claude-sonnet-5-5")


def _chat_daily_usd() -> float:
    return float(os.environ.get("SENDA_CHAT_DAILY_USD", "10.0"))


def _chat_per_hour() -> int:
    return int(os.environ.get("SENDA_CHAT_PER_HOUR", "60"))


def _chat_per_day() -> int:
    return int(os.environ.get("SENDA_CHAT_PER_DAY", "200"))


def _chat_guard() -> bool:
    return os.environ.get("SENDA_CHAT_GUARD", "1") != "0"


def _database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def _google_key() -> str | None:
    return os.environ.get("GOOGLE_MAPS_API_KEY") or None


def _anthropic_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or None


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=_data_dir)
    weather_dir: Path | None = field(default_factory=_weather_dir)  # the folder `current` is in; None: next to the data
    climate_dir: Path | None = field(default_factory=_climate_dir)  # likewise for the monthly climate
    database_url: str | None = field(default_factory=_database_url, repr=False)  # Postgres of chats and plans
    google_maps_key: str | None = field(default_factory=_google_key, repr=False)  # Places and Routes, a fallback
    reload_every_s: float = field(default_factory=_reload_every)  # how often to look for a new data version; 0: never
    max_export_rows: int = field(default_factory=_max_rows)  # rows of one hotspot export
    export_per_hour: int = field(default_factory=_export_per_hour)  # hotspot exports per address; 0: no limit
    export_rows_per_day: int = field(default_factory=_export_rows_per_day)  # all hotspot rows per UTC day; 0: no cap
    export_slots: int = 2  # hotspot exports streaming at once on the server
    export_wait_s: float = 20.0  # how long one more waits for a slot
    window_max_area_km2: float = 3_000_000.0
    chat_model: str = field(default_factory=_chat_model)
    anthropic_api_key: str | None = field(default_factory=_anthropic_key, repr=False)
    chat_max_message_chars: int = 1500
    chat_max_history: int = 16  # messages in the request, the new question included
    chat_max_rounds: int = 6  # model calls per question; the last one runs without tools
    chat_max_tokens: int = 4000  # per model call; the thinking counts toward it
    chat_daily_usd: float = field(default_factory=_chat_daily_usd)  # model spend per UTC day; 0: no cap
    chat_deadline_s: float = 90.0  # per question
    chat_call_timeout_s: float = 45.0  # per model call
    chat_per_hour: int = field(default_factory=_chat_per_hour)  # accepted questions per address; 0: no limit
    chat_per_day: int = field(default_factory=_chat_per_day)  # the same over 24 hours
    chat_guard: bool = field(default_factory=_chat_guard)  # the off-topic and injection check; needs the model key
