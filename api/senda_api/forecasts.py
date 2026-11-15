"""The model forecast of a data version: `forecast.parquet` (p10, p50 and p90 of the months ahead, only for the areas and
horizons where the model passed its check against the calendar median) and `forecast.json` (when it was trained, on what,
how every area scored). A version without them has no model forecast: the calendar then says the median of the past years.
The files are the pipeline's; this module reads them and answers for one area.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from .areas import WORLD_ID
from .months import month_label, parse_month_label

COLUMNS = ("region_id", "month", "horizon", "p10", "p50", "p90", "err_pct")


def _id(name: str) -> str:
    """The pipeline calls the world `world`."""
    return WORLD_ID if name.lower() == WORLD_ID.lower() else name


@dataclass(eq=False)
class ModelForecast:
    doc: dict
    rows: dict[str, dict[str, dict]]
    """Area id -> month `YYYY-MM` -> p10, p50, p90, horizon and the test error in percent of that horizon; only the
    areas and months where the model passed its check."""
    validated: dict[str, dict]
    """Area id -> how it scored (`model_err_pct`, `base_err_pct`, one value for each horizon): every area that was checked,
    with or without a place in `rows`."""
    trained_through: int
    """Absolute number of the last month the model has seen."""

    def _checked(self, area_id: str | None, key: str, horizon: int) -> float | None:
        """One value of the check of an area at a horizon; None where it was not checked. The arrays of the check go by
        `model.horizons` of the file: the first value is the first horizon there, not horizon 1."""
        found = self.validated.get(area_id, {}).get(key) if area_id is not None else None
        horizons = self.doc.get("model", {}).get("horizons") or list(range(1, len(found or ()) + 1))
        return found[horizons.index(horizon)] if found and horizon in horizons and horizons.index(horizon) < len(found) else None

    def base_error(self, area_id: str | None, horizon: int) -> float | None:
        """Error of the calendar median at a horizon (months after the last one the model has seen) in the check of an
        area, in percent; None where it was not checked."""
        return self._checked(area_id, "base_err_pct", horizon)

    def model_error(self, area_id: str | None, horizon: int) -> float | None:
        """Error of the model at a horizon in the same check, in percent; None where it was not checked."""
        return self._checked(area_id, "model_err_pct", horizon)

    def months(self, area_id: str) -> int:
        """How many months, from the first the model forecasts, it serves for an area: its K; 0 when it does not."""
        return int(self.doc.get("model_horizons", {}).get(area_id, len(self.rows.get(area_id, ()))))

    def summary(self, area_id: str | None) -> dict:
        """What the model says for an area and how it was checked there, for the assistant: whether the area was in the
        check, how many months ahead the model serves (K), the months it could serve, and per horizon of the file its
        error against the error of the median of past years in the same check and whether it serves that month."""
        model = self.doc.get("model", {})
        months = model.get("months") or []
        checked = area_id is not None and area_id in self.validated
        out: dict = {"checked": checked, "used_for_months": self.months(area_id) if area_id is not None else 0,
                     "first_month": months[0] if months else None, "last_month": months[-1] if months else None,
                     "trained_through": month_label(self.trained_through), "trained_at": self.doc.get("trained_at")}
        if checked:
            served = self.rows.get(area_id, {})
            out["check"] = [{"month": month, "model_err_pct": self.model_error(area_id, h),
                             "base_err_pct": self.base_error(area_id, h), "used": month in served}
                            for h, month in zip(model.get("horizons") or (), months, strict=False)]
        return out


def load(root: Path) -> ModelForecast | None:
    """The forecast of a data version; None when it has none (both files must be there)."""
    table, document = root / "forecast.parquet", root / "forecast.json"
    if not (table.exists() and document.exists()):
        return None
    doc = json.loads(document.read_text())
    df = pl.read_parquet(table)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"forecast.parquet lacks columns {missing}")
    rows: dict[str, dict[str, dict]] = {}
    for rid, month, horizon, p10, p50, p90, err in df.select(COLUMNS).iter_rows():
        if not 0 <= p10 <= p50 <= p90:
            raise ValueError(f"forecast.parquet: {rid} {month} is not p10 <= p50 <= p90")
        rows.setdefault(_id(rid), {})[month] = {"horizon": int(horizon), "p10": float(p10), "p50": float(p50),
                                                "p90": float(p90), "err_pct": None if err is None else round(float(err), 1)}
    through = parse_month_label(str(doc["trained_through"]))
    return ModelForecast(doc, rows, {_id(k): v for k, v in doc.get("validated", {}).items()}, through)
