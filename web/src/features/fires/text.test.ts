import { INTEGER_ZONE } from '../../test/configFixtures';
import { describe, expect, it } from 'vitest';
import { translate } from '../../i18n/translate';
import { FIRE_DETAIL, FIRE } from '../../test/fireFixtures';
import { compass, formatClock, formatPass, issueText, weatherAt, whereText } from './text';

const t = (key: Parameters<typeof translate>[1], params?: Parameters<typeof translate>[2]) =>
  translate('en', key, params);

describe('compass', () => {
  it('wraps any direction into the eight compass points', () => {
    expect([compass(0), compass(7.6), compass(8), compass(-1)]).toEqual([0, 0, 0, 7]);
  });
});

describe('whereText', () => {
  it('says how far the nearest place is and where the fire lies from it', () => {
    expect(whereText(t, 'en', FIRE.nearest_place)).toBe('12 km northwest');
  });
});

describe('times', () => {
  it('use the supplied place zone and include its Intl label', () => {
    expect(formatClock('en', '2026-10-28T18:38:00Z', INTEGER_ZONE)).toBe('12:38 GMT-6');
    expect(formatPass('en', '2026-10-28T18:38:00Z', INTEGER_ZONE)).toBe('28 Oct, 12:38 GMT-6');
  });
});

describe('weatherAt', () => {
  const own = FIRE_DETAIL.weather;
  if (!own) throw new Error('the fixture fire has weather');
  const detail = {
    ...FIRE_DETAIL,
    weather: { ...own, wind_speed_kmh: own.wind_speed_kmh.map((_, hour) => hour) },
  };

  it('takes the hour nearest to the pass', () => {
    expect(weatherAt(detail)?.speed).toBe(19);
  });

  it('takes the hour asked for', () => {
    expect(weatherAt(detail, '2026-10-28T05:00:00Z')?.speed).toBe(5);
  });

  it('has nothing for an hour the series does not reach', () => {
    expect(weatherAt(detail, '2026-11-05T05:00:00Z')).toBeNull();
  });

  it('has nothing for a fire without weather', () => {
    expect(weatherAt({ ...detail, weather: null })).toBeNull();
  });
});

const NO_ISSUE = {
  crew: null,
  mark: null,
  hours: null,
  speed_kmh: null,
  count: null,
  until_min: null,
  walk_min: null,
  distance_m: null,
  key: null,
  forced: null,
  hot_spot: null,
  crews: null,
  hot_spots: null,
} as const;

describe('issueText', () => {
  it('names the entry mark and the hours until the front arrives', () => {
    const text = issueText(t, { ...NO_ISSUE, level: 'block', kind: 'fc', mark: 2, hours: 1.5 }, 4);
    expect(text).toContain('2');
    expect(text).toContain('1.5');
  });

  it('has words for every kind of issue', () => {
    const kinds = [
      'in',
      'fc',
      'wind',
      'head',
      'nozone',
      'escfire',
      'stale',
      'outside',
      'nopath',
      'long',
      'share',
      'noland',
    ] as const;
    for (const kind of kinds) {
      expect(issueText(t, { ...NO_ISSUE, level: 'info', kind }, 0)).not.toBe('');
    }
  });
});
