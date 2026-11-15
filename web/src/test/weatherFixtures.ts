import type { FireWeather, WeatherLegend } from '../api/types';
import { FIRE } from './fireFixtures';

const names = (en: string, ru: string, es: string) => ({ en, ru, es });

export const WEATHER_LEGEND: WeatherLegend = {
  available: true,
  attribution: 'Weather: NOAA GFS',
  grid: {
    start: '2026-10-27T00:00:00Z',
    end: '2026-10-31T06:00:00Z',
    hours: 103,
    updated_at: '2026-10-30T06:35:00Z',
    cycle: '2026-10-30T00:00:00Z',
  },
  fires: {
    start: '2026-10-27T00:00:00Z',
    end: '2026-10-31T23:00:00Z',
    hours: 120,
    updated_at: '2026-10-30T06:35:00Z',
    cycle: null,
  },
  layers: [
    {
      layer: 'wind',
      unit: 'km/h',
      name: names('Wind', 'Ветер', 'Viento'),
      description: names('Wind', 'Ветер', 'Viento'),
      opacity: 1,
      bands: [
        { id: 0, low: 0, high: 6, name: names('Calm', 'Штиль', 'Calma'), color: '#d9f0fb' },
        { id: 1, low: 6, high: null, name: names('Light', 'Слабый', 'Leve'), color: '#8fd0ef' },
      ],
    },
    {
      layer: 'rain',
      unit: 'mm/h',
      name: names('Precipitation', 'Осадки', 'Precipitación'),
      description: names('Precipitation', 'Осадки', 'Precipitación'),
      opacity: 0.7,
      bands: [
        { id: 0, low: 0, high: 0.1, name: names('None', 'Нет', 'Sin lluvia'), color: '#ffffff' },
        { id: 1, low: 0.1, high: null, name: names('Light', 'Слабые', 'Leve'), color: '#cfe6ff' },
      ],
    },
    {
      layer: 'dryness',
      unit: 'kPa',
      name: names('Dryness and heat', 'Сухость и жара', 'Sequedad y calor'),
      description: names('Dryness', 'Сухость', 'Sequedad'),
      opacity: 0.7,
      bands: [
        { id: 0, low: 0, high: 0.5, name: names('Humid', 'Влажно', 'Húmedo'), color: '#2f8f5b' },
        { id: 1, low: 0.5, high: null, name: names('Dry', 'Сухо', 'Seco'), color: '#9acb5a' },
      ],
    },
  ],
};

const hours = 48;
const series = <T>(value: T) => Array.from({ length: hours }, () => value);

/** The weather of the layers at the fixture fire: a steady 14 km/h from the east, gusting 22, dry, no rain. */
export const FIRE_WEATHER: FireWeather = {
  available: true,
  start: '2026-10-28T00:00:00Z',
  hours,
  fires: [
    {
      fire_id: FIRE.id,
      position: [-56.09, -28.455],
      speed_kmh: series(14),
      gust_kmh: series(22),
      from_deg: series(90),
      wind_category: series(1),
      precip_mm: series(0),
      vpd_kpa: series(0.8),
      hdw: series(31),
      dryness_category: series(1),
      temperature_c: series(24),
      humidity_pct: series(41),
    },
  ],
};
