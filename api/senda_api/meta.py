"""Reference documents: archive description and the harmonization method summary."""

from __future__ import annotations

from . import seam
from .months import month_label
from .regions import region_index
from .store import SENSOR_NAMES, Store


def meta(store: Store, chat_enabled: bool = False) -> dict:
    sensors = []
    for sensor_id, info in store.manifest.get("sensors", {}).items():
        sensors.append(
            {
                "id": sensor_id,
                "name": SENSOR_NAMES.get(sensor_id, sensor_id),
                "first": info.get("first"),
                "last": info.get("last"),
                "retired_at": info.get("retired_at"),
            }
        )
    return {
        "data_version": store.version,
        "archive": {
            "first_month": month_label(store.first_month),
            "last_complete_date": store.last_complete_date.isoformat(),
        },
        "sensors": sensors,
        "gap_dates": list(store.manifest.get("gap_dates", [])),
        "examples": [{**{k: v for k, v in e.items() if k != "region_name"}, "names": region_index(store).names[e["region_id"]]}
                     for e in store.events if e.get("found") is True],
        "chat": {"enabled": chat_enabled},
        "seam": seam.meta(store.seam),
    }
