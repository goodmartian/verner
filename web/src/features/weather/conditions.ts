import { localName } from '../../i18n/lang';
import type { FireDetail, FireSeries, WeatherLegend } from '../../api/types';
import type { Lang } from '../../i18n/lang';
import { weatherAt } from '../fires/text';
import { seriesIndex } from './time';

export type LegendKind = 'wind' | 'rain' | 'dryness';

export interface Band {
  name: string;
  color: string;
}

/** The band of a layer's legend a category of the server stands for. */
export function bandOf(
  legend: WeatherLegend | undefined,
  layer: LegendKind,
  category: number | undefined,
  lang: Lang,
): Band | null {
  const band = legend?.layers
    .find((item) => item.layer === layer)
    ?.bands.find((item) => item.id === category);
  return band ? { name: localName(band.name, lang), color: band.color } : null;
}

/** What the weather is at a fire in an hour; a value the server has not is null. */
export interface Conditions {
  speed: number | null;
  from: number | null;
  gust: number | null;
  precip: number | null;
  hdw: number | null;
  temperature: number | null;
  humidity: number | null;
  wind: Band | null;
  dryness: Band | null;
}

export const NONE: Conditions = {
  speed: null,
  from: null,
  gust: null,
  precip: null,
  hdw: null,
  temperature: null,
  humidity: null,
  wind: null,
  dryness: null,
};

/** The series of a fire at an hour; null when the hour is not in it. */
export function conditionsAt(
  series: FireSeries,
  start: string | null,
  hour: string,
  legend: WeatherLegend | undefined,
  lang: Lang,
): Conditions | null {
  const index = seriesIndex(start, series.speed_kmh.length, hour);
  if (index === null) return null;
  return {
    speed: series.speed_kmh[index] ?? null,
    from: series.from_deg[index] ?? null,
    gust: series.gust_kmh[index] ?? null,
    precip: series.precip_mm[index] ?? null,
    hdw: series.hdw[index] ?? null,
    temperature: series.temperature_c[index] ?? null,
    humidity: series.humidity_pct[index] ?? null,
    wind: bandOf(legend, 'wind', series.wind_category[index], lang),
    dryness: bandOf(legend, 'dryness', series.dryness_category[index], lang),
  };
}

/** The conditions of the card of a fire: the series of the weather layers when the fire has them, else what the fire itself carries (wind and air only). */
export function fireConditions(
  detail: FireDetail,
  series: FireSeries | undefined,
  start: string | null,
  hour: string,
  legend: WeatherLegend | undefined,
  lang: Lang,
): Conditions {
  if (series) return conditionsAt(series, start, hour, legend, lang) ?? NONE;
  const own = weatherAt(detail, detail.source === 'demo' ? undefined : hour);
  return own
    ? {
        ...NONE,
        speed: own.speed,
        from: own.from,
        temperature: own.temperature,
        humidity: own.humidity,
      }
    : NONE;
}
