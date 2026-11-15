import { COUNTRY_ID, CONFIG_BBOX, INTEGER_ZONE } from './configFixtures';
import type { Calendar, Meta } from '../api/calendar';
import type { Check, MonthDetail, Regions, Summary } from '../api/types';

const names = (en: string, ru = en, es = en) => ({ en, ru, es, fr: en });
const AREA: Summary['area'] = {
  id: COUNTRY_ID,
  kind: 'country',
  forecast_available: true,
  bbox: CONFIG_BBOX,
  timezone: INTEGER_ZONE,
  covered: true,
};

export const REGIONS: Regions = {
  attribution: null,
  types: {},
  regions: [
    {
      id: COUNTRY_ID,
      kind: 'country',
      names: names('Argentina', 'Аргентина'),
      bbox: [-73.6, -55.1, -53.6, -21.8],
      timezone: INTEGER_ZONE,
      covered: true,
      type: null,
      fires_now: 4,
    },
    {
      id: 'AR-W',
      kind: 'province',
      names: names('Corrientes', 'Корриентес'),
      bbox: [-59.7, -30.7, -56.0, -27.3],
      timezone: INTEGER_ZONE,
      covered: true,
      type: null,
      fires_now: 1,
    },
  ],
};

const point = (month: string, value: number, normal: number) => ({
  month,
  kind: 'forecast' as const,
  value,
  normal,
  model: value,
  low: value / 2,
  high: value * 2,
});

export const SUMMARY: Summary = {
  area: AREA,
  period: { kind: 'forecast', first_month: '2026-10', last_month: '2027-03', months: 6 },
  totals: { seen: 0, forecast: 40303.9, total: 40303.9, normal: 81996, approximate: true },
  verdict: { level: 'below', ratio: 0.4915, standing: 'bottom', forecast_range: 'below_normal' },
  year_ago: { year: 2025, first_month: '2025-10', last_month: '2026-03', total: 1400, ratio: 28.8 },
  rank: { place: 21, of: 23 },
  series: [
    point('2026-10', 12707.6, 23818),
    point('2026-11', 8413.8, 15245),
    point('2026-12', 4918.1, 9749),
    point('2027-01', 5400, 11000),
    point('2027-02', 4800, 10000),
    point('2027-03', 4100, 9000),
  ],
  peak: null,
  forecast_range: { low: 14612, high: 74444 },
  forecast: { months: 6, total: 40303.9, normal: 81996, rain_vs_normal: 1.2, factors: [] },
  trend: { first_year: 2016, last_year: 2025, percent_per_year: -1 },
  accuracy: null,
  whole_record: null,
  typical: { year_total: 120000, peak_month: 9 },
  record: { first_year: 2003, last_year: 2025, viirs_first_year: 2012 },
  attribution: null,
};

export const MONTH: MonthDetail = {
  area: AREA,
  month: '2026-10',
  calendar_month: 10,
  kind: 'forecast',
  value: 12707.6,
  normal: 23818,
  ratio: 0.53,
  rank: null,
  years: [],
  top_provinces: [],
  share_of_country: null,
  forecast: null,
  attribution: null,
};

export const CHECK: Check = {
  area: AREA,
  fit_years: { first: 2003, last: 2022 },
  blind_years: { first: 2023, last: 2025 },
  months: [
    { month: '2023-01', real: 15920, model: 12135, normal: 12880 },
    { month: '2023-02', real: 17232, model: 12326, normal: 11017 },
  ],
  climatology: {
    month_log_error: 0.845,
    year_error: 0.715,
    direction_accuracy: 0.775,
    direction_samples: 741,
  },
  poisson: {
    month_log_error: 0.705,
    year_error: 0.379,
    direction_accuracy: 0.696,
    direction_samples: 741,
  },
  boosting: {
    month_log_error: 0.793,
    year_error: 0.576,
    direction_accuracy: 0.609,
    direction_samples: 741,
  },
};

type CalendarMonth = Calendar['series'][number];
const NO_RAW = { modis_terra: null, modis_aqua: null, viirs_snpp: null, viirs_noaa20: null };

/** A month of the answer of `POST /api/calendar`; what a test does not name is an ordinary month. */
export const monthOf = (month: string, over: Partial<CalendarMonth> = {}): CalendarMonth => ({
  month,
  kind: 'seen',
  count: 5000,
  raw: { ...NO_RAW, viirs_snpp: 5000 },
  frp_mw: null,
  median: 5000,
  mean: 5200,
  ratio: 1,
  level: 1,
  rank: 2,
  of: 3,
  partial: false,
  complete_through: null,
  source: 'sp',
  converted: false,
  sensors: ['viirs_snpp'],
  lo: null,
  hi: null,
  forecast: null,
  ...over,
});

const NONE = {
  kind: 'none' as const,
  count: null,
  raw: NO_RAW,
  median: null,
  mean: null,
  ratio: null,
  level: null,
  rank: null,
  of: null,
  sensors: [],
} satisfies Partial<CalendarMonth>;

/** The shape of the fixture area: a triangle. */
export const POLYGON = {
  type: 'Polygon' as const,
  coordinates: [
    [
      [0, 0],
      [2, 0],
      [2, 2],
      [0, 0],
    ],
  ],
};

export const CALENDAR: Calendar = {
  area: {
    id: COUNTRY_ID,
    name: 'Country',
    bbox: CONFIG_BBOX,
    area_km2: 12000,
    approximate: false,
    geometry: POLYGON,
  },
  first_month: '2025-01',
  last_complete_date: '2026-10-29',
  series: [
    monthOf('2025-01', { count: 0, median: 10, mean: 12, ratio: 0, level: 0, rank: 2, of: 3 }),
    monthOf('2025-02', NONE),
  ],
  normals: [{ month: 1, median: 10, mean: 12, p10: null, p90: null, years: 3 }],
  current_month: {
    ...monthOf('2026-10', { count: 15, median: 10, mean: 12, ratio: 1.5, rank: 1, partial: true }),
    to_date: { through: '2026-10-29', count: 15, median: 10, ratio: 1.5, rank: 1, of: 3 },
  },
  yearly: [{ year: 2025, count: 0, complete: true, gaps: false, converted: false }],
  trend: { first_year: 2016, last_year: 2025, percent_per_year: -1 },
  season: null,
  quality: {
    expected_error: 0.25,
    confidence: 'medium',
    unharmonized_share: 0.02,
    basis: 'fixture',
    seam: null,
  },
  forecast: null,
  check: null,
  presets: [],
  data_version: 'v1',
};

export const META: Meta = {
  data_version: 'v1',
  archive: { first_month: '2025-01', last_complete_date: '2026-10-29' },
  sensors: [],
  gap_dates: [],
  examples: [],
  chat: { enabled: false },
};
