import type { DayFires, MonthDays } from '../api/types';
import type { ClimateLegend } from '../features/climate/types';

const names = (en: string, ru: string, es: string) => ({ en, ru, es });

export const CLIMATE_LEGEND: ClimateLegend = {
  available: true,
  attribution: 'Weather: Copernicus ERA5; fire danger: ECMWF',
  first_month: '2003-01',
  last_month: '2026-09',
  month_layers: [
    {
      layer: 'temperature',
      kind: 'anomaly',
      unit: '°C',
      name: names('Temperature', 'Температура', 'Temperatura'),
      description: names('Temperature', 'Температура', 'Temperatura'),
      opacity: 0.7,
      bands: [
        { id: 0, low: -100, high: 0, name: names('Below', 'Ниже', 'Debajo'), color: '#2c4f9e' },
        { id: 1, low: 0, high: null, name: names('Above', 'Выше', 'Sobre'), color: '#c0272d' },
      ],
    },
  ],
};

export const MONTH_DAYS = {
  month: '2025-10',
  area: 'AR',
  coverage: { first_day: '2003-01-01', last_day: '2026-10-20' },
  days: [
    { date: '2025-10-03', clusters: 5, detections: 40 },
    { date: '2025-10-17', clusters: 44, detections: 300 },
    { date: '2025-10-18', clusters: 12, detections: 90 },
  ],
  attribution: null,
} as unknown as MonthDays;

export const DAY_FIRES = {
  date: '2025-10-17',
  area: 'AR',
  total: 44,
  shown: 2,
  coverage: { first_day: '2003-01-01', last_day: '2026-10-20' },
  fires: [
    {
      id: '20251017-1',
      lon: -60.1,
      lat: -27.3,
      first_detection_at: '2025-10-17T04:10:00Z',
      detections: 200,
      detections_raw: 150,
      sensor: 'viirs',
      frp_mw: 900,
      province: 'Santa Fe',
    },
    {
      id: '20251017-2',
      lon: -58.2,
      lat: -26.1,
      first_detection_at: '2025-10-17T17:30:00Z',
      detections: 80,
      detections_raw: 60,
      sensor: 'viirs',
      frp_mw: 300,
      province: null,
    },
  ],
  attribution: null,
} as unknown as DayFires;
