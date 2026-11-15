import { COUNTRY_ID } from '../../test/configFixtures';
import { describe, expect, it } from 'vitest';
import type { DayFires, MonthDays } from '../../api/types';
import { clusterCollection, daysByDate, monthDates, wholeDays } from './days';

describe('monthDates', () => {
  it('lists the days of the month, with the leap February', () => {
    expect(monthDates('2025-10')).toHaveLength(31);
    expect(monthDates('2025-02')).toHaveLength(28);
    expect(monthDates('2024-02')).toHaveLength(29);
    expect(monthDates('2025-10')[16]).toBe('2025-10-17');
  });
});

const DAYS = {
  month: '2025-10',
  area: COUNTRY_ID,
  days: [
    { date: '2025-10-03', clusters: 5, detections: 40 },
    { date: '2025-10-17', clusters: 44, detections: 300 },
  ],
} as unknown as MonthDays;

describe('days of fires', () => {
  it('keeps the days that had fires by their date', () => {
    expect(daysByDate(DAYS).get('2025-10-17')?.clusters).toBe(44);
    expect(daysByDate(null).size).toBe(0);
  });
});

describe('wholeDays', () => {
  const fractions = (values: number[]) =>
    ({
      days: values.map((detections, index) => ({
        date: `2025-10-${String(index + 1).padStart(2, '0')}`,
        clusters: 1,
        detections,
      })),
    }) as unknown as MonthDays;
  it('makes the days whole numbers that add up to the figure of the month', () => {
    // 1.4 + 1.4 + 1.4 + 0.8 = 5.0, and the figure of the month is 5: the sum of the rounded days would be 4
    const shown = wholeDays(fractions([1.4, 1.4, 1.4, 0.8]), 5);
    expect([...shown.values()].reduce((a, b) => a + b, 0)).toBe(5);
    expect(shown.get('2025-10-04')).toBe(1);
  });
  it('gives the units left over to the days with the largest fractions', () => {
    expect([...wholeDays(fractions([2.6, 2.3, 2.1]), 7).values()]).toEqual([3, 2, 2]);
  });
  it('only rounds the days when the figure of the month is another count', () => {
    expect([...wholeDays(fractions([10.2, 20.2]), 500).values()]).toEqual([10, 20]);
    expect(wholeDays(null, 5).size).toBe(0);
  });
});

describe('clusterCollection', () => {
  it('writes each cluster as a point with its size', () => {
    const day = {
      fires: [{ id: '20251017-1', lon: -60, lat: -27, detections: 200, frp_mw: 900 }],
    } as unknown as DayFires;
    expect(clusterCollection(day).features).toEqual([
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [-60, -27] },
        properties: { id: '20251017-1', detections: 200, frp: 900 },
      },
    ]);
    expect(clusterCollection(undefined).features).toEqual([]);
  });
});
