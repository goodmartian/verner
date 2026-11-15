import { describe, expect, it } from 'vitest';
import {
  FRACTIONAL_ZONE,
  INTEGER_ZONE,
  QUARTER_ZONE,
  ZONE_OFFSETS,
  makeConfig,
} from '../test/configFixtures';
import { dayStart, dayTicks, HOUR, nextDayStart } from '../features/timeline/scale';
import { formatLocalTime, localDay, utcOffsetLabel } from './time';

describe('place time', () => {
  it('labels UTC offsets without an IANA identifier, including DST and fractional hours', () => {
    const winter = Date.parse('2026-01-15T12:00:00Z');
    const summer = Date.parse('2026-07-15T12:00:00Z');
    expect(utcOffsetLabel(INTEGER_ZONE, winter)).toBe(ZONE_OFFSETS.integerWinter);
    expect(utcOffsetLabel(INTEGER_ZONE, summer)).toBe(ZONE_OFFSETS.integerSummer);
    expect(utcOffsetLabel(FRACTIONAL_ZONE, winter)).toBe(ZONE_OFFSETS.fractional);
    expect(utcOffsetLabel(QUARTER_ZONE, winter)).toBe(ZONE_OFFSETS.quarter);
  });
  it('uses the place zone with its Intl label, including fractional offsets', () => {
    const locale = makeConfig().languages[0]?.locale;
    if (!locale) throw new Error('The fixture needs a locale');
    expect(formatLocalTime('en', '2026-01-15T12:00:00Z', INTEGER_ZONE)).toMatch(/05:00.*GMT-7/);
    expect(formatLocalTime('fr-CA', '2026-01-15T12:00:00Z', FRACTIONAL_ZONE)).toMatch(
      /08.*30.*UTC−3:30/,
    );
    expect(formatLocalTime('en', '2026-01-15T12:00:00Z', null)).toBe('');
    expect(formatLocalTime(locale, '2026-01-15T12:00:00Z', QUARTER_ZONE)).toMatch(
      /17:45.*GMT\+5:45/,
    );
    expect(dayStart(Date.parse('2026-01-15T12:00:00Z'), QUARTER_ZONE)).toBe(
      Date.parse('2026-01-14T18:15:00Z'),
    );
  });

  it.each([
    ['2026-03-08T18:00:00Z', 23],
    ['2026-11-01T18:00:00Z', 25],
  ])('finds the actual midnights on %s (%i hours)', (iso, hours) => {
    const at = Date.parse(iso);
    const first = dayStart(at, INTEGER_ZONE);
    const next = nextDayStart(at, INTEGER_ZONE);
    expect(next - first).toBe(hours * HOUR);
    expect(localDay(first - 1, INTEGER_ZONE)).not.toBe(localDay(first, INTEGER_ZONE));
    expect(localDay(next - 1, INTEGER_ZONE)).toBe(localDay(first, INTEGER_ZONE));
  });

  it('keeps ticks at fractional-zone midnights across DST', () => {
    const from = dayStart(Date.parse('2026-03-07T12:00:00Z'), FRACTIONAL_ZONE);
    const ticks = dayTicks(from, from + 4 * 24 * HOUR, (day) => day, FRACTIONAL_ZONE);
    expect(ticks[0]?.at).toBe(Date.parse('2026-03-07T03:30:00Z'));
    expect(ticks.map((tick) => tick.label)).toEqual([
      '2026-03-07',
      '2026-03-08',
      '2026-03-09',
      '2026-03-10',
      '2026-03-11',
    ]);
    expect(Number(ticks[2]?.at) - Number(ticks[1]?.at)).toBe(23 * HOUR);
  });
});
