"""What the weather layers are drawn with: bands of values, their names in three languages, colours.

Also the HDW index and `vpd_kpa`. The server decides the band and the colour of every value, so the
interface only paints. The bands are fixed (a range of values, the same in every hour).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

LAYERS = ("wind", "rain", "dryness")


@dataclass(frozen=True)
class Names:
    en: str
    ru: str
    es: str


@dataclass(frozen=True)
class Band:
    id: int
    low: float
    """The band holds the values from `low` up to the next band's `low`."""
    name: Names
    color: str
    """`#rrggbb`."""


@dataclass(frozen=True)
class LayerLegend:
    layer: str
    unit: str
    name: Names
    description: Names
    bands: tuple[Band, ...]
    opacity: float
    """How opaque the map layer looks best."""
    clear_first_band: bool = False
    """The first band is drawn as nothing (no rain)."""

    @property
    def lows(self) -> NDArray[np.float64]:
        return np.array([b.low for b in self.bands], dtype=np.float64)

    def band_of(self, values: NDArray[np.float64]) -> NDArray[np.int64]:
        """The index of the band of each value."""
        return np.clip(np.searchsorted(self.lows, values, side="right") - 1, 0, len(self.bands) - 1)


WIND = LayerLegend(
    layer="wind",
    unit="km/h",
    name=Names("Wind", "Ветер", "Viento"),
    description=Names(
        "Wind speed at 10 m; arrows show where it blows from",
        "Скорость ветра на 10 м; стрелки показывают, откуда он дует",
        "Velocidad del viento a 10 m; las flechas indican de dónde sopla",
    ),
    bands=(
        Band(0, 0, Names("Calm", "Штиль", "Calma"), "#d9f0fb"),
        Band(1, 6, Names("Light", "Слабый", "Débil"), "#8fd0ef"),
        Band(2, 20, Names("Moderate", "Умеренный", "Moderado"), "#4aa6dd"),
        Band(3, 30, Names("Strong", "Сильный", "Fuerte"), "#f2c14e"),
        Band(4, 40, Names("Very strong", "Очень сильный", "Muy fuerte"), "#e8743b"),
        Band(5, 50, Names("Storm", "Шторм", "Temporal"), "#b8222d"),
    ),
    opacity=1.0,
)

RAIN = LayerLegend(
    layer="rain",
    unit="mm/h",
    name=Names("Precipitation", "Осадки", "Precipitación"),
    description=Names(
        "Precipitation in the hour",
        "Осадки за час",
        "Precipitación en la hora",
    ),
    bands=(
        Band(0, 0, Names("None", "Нет", "Ninguna"), "#ffffff"),
        Band(1, 0.1, Names("Light", "Слабые", "Débil"), "#cfe6ff"),
        Band(2, 0.5, Names("Moderate", "Умеренные", "Moderada"), "#7db5f0"),
        Band(3, 2, Names("Heavy", "Сильные", "Fuerte"), "#3a7bd5"),
        Band(4, 5, Names("Very heavy", "Очень сильные", "Muy fuerte"), "#7a3fd1"),
        Band(5, 10, Names("Extreme", "Экстремальные", "Extrema"), "#c2188f"),
    ),
    opacity=0.7,
    clear_first_band=True,
)

DRYNESS = LayerLegend(
    layer="dryness",
    unit="kPa",
    name=Names("Dryness and heat", "Сухость и жара", "Sequedad y calor"),
    description=Names(
        "Vapour pressure deficit: how dry the air is, higher when it is hot and dry",
        "Дефицит давления пара: насколько сух воздух, выше в жару и сушь",
        "Déficit de presión de vapor: qué tan seco está el aire, mayor con calor y sequedad",
    ),
    bands=(
        Band(0, 0, Names("Humid", "Влажно", "Húmedo"), "#2f8f5b"),
        Band(1, 0.5, Names("Moderate", "Умеренно", "Moderado"), "#9acb5a"),
        Band(2, 1, Names("Dry", "Сухо", "Seco"), "#f2d04a"),
        Band(3, 2, Names("Very dry", "Очень сухо", "Muy seco"), "#ef8a3a"),
        Band(4, 3, Names("Extreme", "Экстремально", "Extremo"), "#c0272d"),
    ),
    opacity=0.7,
)

LEGENDS = {"wind": WIND, "rain": RAIN, "dryness": DRYNESS}


def hdw(vpd_kpa: NDArray[np.float64], wind_kmh: NDArray[np.float64]) -> NDArray[np.float64]:
    """Hot-Dry-Windy index at the surface: vapour pressure deficit (hPa) times wind (m/s)."""
    return np.asarray(vpd_kpa * 10.0 * (wind_kmh / 3.6), dtype=np.float64)


def rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def vpd_kpa(temperature_c: NDArray, humidity_pct: NDArray) -> NDArray:
    """Vapour pressure deficit from temperature and relative humidity (Tetens)."""
    saturation = 0.6108 * np.exp(17.27 * temperature_c / (temperature_c + 237.3))
    return np.asarray(saturation * (1 - np.clip(humidity_pct, 0, 100) / 100), dtype=np.float64)
