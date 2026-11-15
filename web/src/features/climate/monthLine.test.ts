import { describe, expect, it } from 'vitest';
import { translate } from '../../i18n/translate';
import { monthLine } from './monthLine';
import type { ClimateMonth } from './types';

const en = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) =>
  translate('en', key, values);
const ru = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) =>
  translate('ru', key, values);

// the answer of the server for one area, September 2026
const SEPTEMBER: ClimateMonth = {
  area: 'area-1',
  month: '2026-09',
  kind: 'observed',
  observed: {
    quantities: [
      {
        key: 'temperature_c',
        unit: '°C',
        value: 11.83,
        normal: 12.11,
        anomaly: -0.28,
        anomaly_kind: 'difference',
        change_pct: null,
        rank: 20,
        of_years: 24,
      },
      {
        key: 'rain_mm',
        unit: 'mm',
        value: 75.78,
        normal: 76,
        anomaly: 0.997,
        anomaly_kind: 'ratio',
        change_pct: 0,
        rank: 5,
        of_years: 24,
      },
    ],
    normal_first_year: 1993,
    normal_last_year: 2016,
  },
  attribution: 'Generated using Copernicus Climate Change Service information',
};

describe('monthLine', () => {
  it('says the temperature and the rain against the normal in one line', () => {
    expect(monthLine(en, 'en', SEPTEMBER)).toBe('−0.3 °C vs normal, rain 100 % of normal');
  });

  it('writes it in the language', () => {
    expect(monthLine(ru, 'ru', SEPTEMBER)).toBe('−0,3 °C к норме, осадки 100 % нормы');
  });

  it('leaves out the rain when the server gives no share of the normal', () => {
    const dry: ClimateMonth = {
      ...SEPTEMBER,
      observed: SEPTEMBER.observed && {
        ...SEPTEMBER.observed,
        quantities: SEPTEMBER.observed.quantities.map((item) =>
          item.key === 'rain_mm' ? { ...item, anomaly: null } : item,
        ),
      },
    };
    expect(monthLine(en, 'en', dry)).toBe('−0.3 °C vs normal');
  });

  it('says nothing for a month without weather, which is not a month that is loading', () => {
    const none: ClimateMonth = { ...SEPTEMBER, kind: 'none', observed: null, attribution: null };
    expect(monthLine(en, 'en', none)).toBeNull();
    expect(monthLine(en, 'en', undefined)).toBeNull();
  });
});
