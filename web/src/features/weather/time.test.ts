import { describe, expect, it } from 'vitest';
import { inSpan, nearestHour, seriesIndex, tailHours, thisHour, weatherMoment } from './time';

describe('hours', () => {
  it('rounds a pass to the nearest hour and floors the present one', () => {
    expect(nearestHour(Date.parse('2026-10-30T14:42:00Z'))).toBe('2026-10-30T15:00:00Z');
    expect(nearestHour(Date.parse('2026-10-30T14:29:00Z'))).toBe('2026-10-30T14:00:00Z');
    expect(thisHour(Date.parse('2026-10-30T14:42:00Z'))).toBe('2026-10-30T14:00:00Z');
  });

  it('finds an hour in a series and nothing beyond its ends', () => {
    const start = '2026-10-27T00:00:00Z';
    expect(seriesIndex(start, 120, '2026-10-27T05:00:00Z')).toBe(5);
    expect(seriesIndex(start, 120, '2026-10-26T23:00:00Z')).toBeNull();
    expect(seriesIndex(start, 120, '2026-11-01T00:00:00Z')).toBeNull();
    expect(seriesIndex(null, 120, start)).toBeNull();
  });

  it('knows whether an hour is within the span of the data', () => {
    const span = { start: '2026-10-27T00:00:00Z', end: '2026-10-31T06:00:00Z' };
    expect(inSpan(span, '2026-10-31T06:00:00Z')).toBe(true);
    expect(inSpan(span, '2026-10-31T07:00:00Z')).toBe(false);
    expect(inSpan(null, span.start)).toBe(false);
  });
});

describe('tailHours', () => {
  it('runs from now to the end every three hours', () => {
    const hours = tailHours('2026-10-30T06:00:00Z', '2026-10-31T06:00:00Z');
    expect(hours).toHaveLength(9);
    expect(hours[0]).toBe('2026-10-30T06:00:00Z');
    expect(hours.at(-1)).toBe('2026-10-31T06:00:00Z');
  });

  it('ends with the last hour of the data when it is not on the step', () => {
    expect(tailHours('2026-10-30T06:00:00Z', '2026-10-30T11:00:00Z')).toEqual([
      '2026-10-30T06:00:00Z',
      '2026-10-30T09:00:00Z',
      '2026-10-30T11:00:00Z',
    ]);
  });

  it('is empty when the data ends before now', () => {
    expect(tailHours('2026-10-30T06:00:00Z', '2026-10-30T04:00:00Z')).toEqual([]);
  });
});

describe('weatherMoment', () => {
  const now = '2026-10-30T06:00:00Z';
  const pass = '2026-10-29T14:42:00Z';

  it('is the present hour while the player is closed', () => {
    expect(weatherMoment({ player: false, clock: null, pass, forecast: 0, now })).toBe(now);
  });

  it('follows the pass, rounded to the hour, with the front forecast added', () => {
    expect(weatherMoment({ player: true, clock: null, pass, forecast: 0, now })).toBe(
      '2026-10-29T15:00:00Z',
    );
    expect(weatherMoment({ player: true, clock: null, pass, forecast: 3, now })).toBe(
      '2026-10-29T18:00:00Z',
    );
  });

  it('follows the hour picked in the forecast tail', () => {
    const clock = '2026-10-30T18:00:00Z';
    expect(weatherMoment({ player: true, clock, pass, forecast: 0, now })).toBe(clock);
  });
});
