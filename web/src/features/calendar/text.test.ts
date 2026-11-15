import { describe, expect, it } from 'vitest';
import type { Summary } from '../../api/types';
import { translate } from '../../i18n/translate';
import type { Lang } from '../../i18n/lang';
import {
  formatChange,
  detectionsWord,
  formatCount,
  monthVerdict,
  niceNumber,
  periodTitle,
  verdictLines,
} from './text';

const summary = (
  verdict: Partial<Summary['verdict']>,
  rank: Summary['rank'] = { place: 21, of: 23 },
) =>
  ({
    verdict: { level: 'below', ratio: 0.4915, standing: null, forecast_range: null, ...verdict },
    rank,
  }) as Summary;

const lines = (lang: Lang, s: Summary) =>
  verdictLines((key, params) => translate(lang, key, params), lang, s, 2003);

describe('monthVerdict', () => {
  const at = (change: Partial<Parameters<typeof monthVerdict>[0]>) =>
    monthVerdict({ count: 500, median: 400, ratio: 1.18, rank: 10, of: 24, ...change });
  it('puts the first place of all years before the percent: +18 % at #1 is the highest, not the usual', () => {
    expect(at({ rank: 1 })).toBe('highest');
    expect(at({ rank: 24, ratio: 0.5 })).toBe('lowest');
  });
  it('tells by the percent when the place is in the middle', () => {
    expect(at({ ratio: 0.5 })).toBe('below');
    expect(at({})).toBe('near');
    expect(at({ ratio: 2 })).toBe('above');
    expect(at({ ratio: null, rank: null })).toBeNull();
  });
  it('says there are none when the month and the usual are both nothing, before a place or a percent', () => {
    expect(at({ count: 0, median: 0, ratio: null, rank: 1, of: 24 })).toBe('none');
    expect(at({ count: 0, median: 3, ratio: 0, rank: 24 })).toBe('few');
  });
  it('says there are few when both the month and the usual are under ten, whatever the percent or the place', () => {
    expect(at({ count: 2, median: 1, ratio: 2, rank: 1 })).toBe('few');
    expect(at({ count: 2, median: 40, ratio: 0.05, rank: 24 })).toBe('lowest');
  });
});

describe('niceNumber', () => {
  it.each([
    [40303.9, 40300],
    [12707.6, 12700],
    [4918.1, 4900],
    [947, 950],
    [42.4, 42],
  ])('%f is shown as %f', (n, shown) => {
    expect(niceNumber(n)).toBe(shown);
  });
});

describe('formatCount', () => {
  it('groups digits as the language does and marks an estimate', () => {
    expect(formatCount('en', 40303.9, true)).toBe('≈ 40,300');
    expect(formatCount('en', 1400)).toBe('1,400');
    expect(formatCount('ru', 1400)).toMatch(/^1\s400$/);
  });
});

describe('detectionsWord', () => {
  const word = (n: number) =>
    detectionsWord((key, params) => translate('ru', key, params), 'ru', n);
  it('declines the Russian word by the last digits of the count', () => {
    expect(word(82541)).toBe('детекция');
    expect(word(82542)).toBe('детекции');
    expect(word(3963)).toBe('детекции');
    expect(word(5009)).toBe('детекций');
    expect(word(11)).toBe('детекций');
    expect(word(0)).toBe('детекций');
  });
  it('keeps one and many in English', () => {
    const en = (n: number) =>
      detectionsWord((key, params) => translate('en', key, params), 'en', n);
    expect(en(1)).toBe('detection');
    expect(en(5009)).toBe('detections');
  });
});

describe('formatChange', () => {
  it('writes a signed percent with a real minus', () => {
    expect(formatChange('en', 0.4915)).toBe('−51 %');
    expect(formatChange('en', 1.18)).toBe('+18 %');
    expect(formatChange('en', 1)).toBe('0 %');
  });
});

describe('verdictLines', () => {
  it('says how far below the normal and where the period stands among the years', () => {
    expect(lines('en', summary({ standing: 'bottom', forecast_range: 'below_normal' }))).toEqual([
      '51 % below the normal',
      'Number 3 for quiet since 2003',
      'Even the top of the forecast range is below the normal',
    ]);
  });

  it('says how far above, and when it is many times the normal', () => {
    expect(lines('en', summary({ level: 'above', ratio: 1.4 }))[0]).toBe('40 % above the normal');
    expect(lines('en', summary({ level: 'far_above', ratio: 2.54 }))[0]).toBe(
      '2.5 times the normal',
    );
    expect(lines('ru', summary({ level: 'far_above', ratio: 2.54 }))[0]).toBe(
      'В 2,5 раза сильнее нормы',
    );
  });

  it('has words for no normal and for near the normal', () => {
    expect(lines('en', summary({ level: 'none', ratio: null }))).toEqual([
      'No normal for this period',
    ]);
    expect(lines('en', summary({ level: 'near', ratio: 1.03 }))).toEqual(['Near the normal']);
  });

  it('names the record, the top, the quietest', () => {
    expect(lines('en', summary({ level: 'above', ratio: 3, standing: 'record' }))[1]).toBe(
      'The most since 2003',
    );
    expect(lines('en', summary({ standing: 'top' }, { place: 2, of: 23 }))[1]).toBe(
      'Number 2 since 2003',
    );
    expect(lines('en', summary({ standing: 'quietest' }))[1]).toBe('The quietest since 2003');
  });

  it('says that the whole range is above the normal', () => {
    expect(
      lines('en', summary({ level: 'above', ratio: 2, forecast_range: 'above_normal' })).at(-1),
    ).toBe('Even the bottom of the forecast range is above the normal');
  });
});

describe('periodTitle', () => {
  const context = {
    forecast: { from: '2026-10', to: '2027-03' },
    record: { from: '2003-01', to: '2025-12' },
  };
  const title = (lang: Lang, from: string, to: string) =>
    periodTitle((key, params) => translate(lang, key, params), lang, { from, to }, context);

  it('names a year, a quarter and a month', () => {
    expect(title('en', '2025-01', '2025-12')).toBe('2025');
    expect(title('en', '2025-04', '2025-06')).toBe('Q2 2025');
    expect(title('en', '2025-03', '2025-03')).toBe('March 2025');
    expect(title('ru', '2025-04', '2025-06')).toBe('2 кв. 2025');
  });

  it('names the forecast and the whole record', () => {
    expect(title('en', '2026-10', '2027-03')).toBe('Forecast, Oct 2026 – Mar 2027');
    expect(title('en', '2003-01', '2025-12')).toBe('All years, 2003–2025');
  });

  it('writes any other span out', () => {
    expect(title('en', '2024-10', '2025-03')).toBe('Oct 2024 – Mar 2025');
  });
});
