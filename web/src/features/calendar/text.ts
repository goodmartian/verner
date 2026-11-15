import type { Summary } from '../../api/types';
import type { I18n } from '../../i18n/context';
import { LOCALES, type Lang } from '../../i18n/lang';
import { numberFormat } from '../../lib/numberFormat';
import { monthIndex, monthsIn, sameRange, yearOf, type Month, type MonthRange } from './months';

/** Big numbers are shown to the hundred, mid ones to the ten: the satellites are not that exact. */
export function niceNumber(n: number): number {
  if (n >= 1000) return Math.round(n / 100) * 100;
  if (n >= 100) return Math.round(n / 10) * 10;
  return Math.round(n);
}

/** A count of detections as it was seen; `≈` and a round number when it is a forecast or a sum with one. */
export function formatCount(lang: Lang, n: number, approximate = false): string {
  const text = numberFormat(LOCALES[lang]).format(approximate ? niceNumber(n) : Math.round(n));
  return approximate ? `≈ ${text}` : text;
}

/** A normal or a total of another period: rounded to the hundred, as the satellites are not that exact. */
export function formatNice(lang: Lang, n: number): string {
  return numberFormat(LOCALES[lang]).format(niceNumber(n));
}

/** A share as a signed percent: `−51 %`, `+18 %`. */
export function formatChange(lang: Lang, ratio: number): string {
  return numberFormat(LOCALES[lang], {
    style: 'percent',
    signDisplay: 'exceptZero',
    maximumFractionDigits: 0,
  })
    .format(ratio - 1)
    .replace('-', '−')
    .replace(/\s?%/, ' %');
}

/** Under this many detections a month and its usual one are too few to be told apart by a percent. */
export const FEW = 10;

export type MonthVerdict = 'none' | 'few' | 'highest' | 'lowest' | 'below' | 'above' | 'near';

/**
 * How a month stands, in the order of what is true of it: too few detections to compare, the highest or the lowest
 * of all the years, and then how it stands against the usual one.
 */
export function monthVerdict(point: {
  count: number | null;
  median: number | null;
  ratio: number | null;
  rank: number | null;
  of: number | null;
}): MonthVerdict | null {
  const { count, median, ratio, rank, of } = point;
  // nothing and nothing usual: there is nothing to compare, and no place among the years
  if (count === 0 && median === 0) return 'none';
  if (count !== null && median !== null && count < FEW && median < FEW) return 'few';
  if (rank !== null && of !== null && of >= 3) {
    if (rank === 1) return 'highest';
    if (rank === of) return 'lowest';
  }
  if (ratio === null) return null;
  return ratio < 0.8 ? 'below' : ratio >= 1.25 ? 'above' : 'near';
}

/** The period in a sentence or two, from the verdict's codes. */
export function verdictLines(
  t: I18n['t'],
  lang: Lang,
  summary: Summary,
  firstYear: number,
): string[] {
  const { verdict, rank } = summary;
  const lines: string[] = [];
  const ratio = verdict.ratio;
  if (verdict.level === 'none' || ratio === null) lines.push(t('verdict.none'));
  else if (verdict.level === 'near') lines.push(t('verdict.near'));
  else if (verdict.level === 'far_above') {
    lines.push(
      t('verdict.times', {
        x: new Intl.NumberFormat(LOCALES[lang]).format(Math.round(ratio * 10) / 10),
      }),
    );
  } else if (verdict.level === 'above') {
    lines.push(t('verdict.above', { p: Math.round((ratio - 1) * 100) }));
  } else {
    lines.push(t('verdict.below', { p: Math.round((1 - ratio) * 100) }));
  }
  if (rank) {
    if (verdict.standing === 'record') lines.push(t('verdict.record', { year: firstYear }));
    else if (verdict.standing === 'top') {
      lines.push(t('verdict.top', { n: rank.place, year: firstYear }));
    } else if (verdict.standing === 'quietest') {
      lines.push(t('verdict.quietest', { year: firstYear }));
    } else if (verdict.standing === 'bottom') {
      lines.push(t('verdict.bottom', { n: rank.of - rank.place + 1, year: firstYear }));
    }
  }
  if (verdict.forecast_range === 'below_normal') lines.push(t('verdict.rangeBelow'));
  else if (verdict.forecast_range === 'above_normal') lines.push(t('verdict.rangeAbove'));
  return lines;
}

// the short names of the months, the same in every browser
const SHORT: Record<Lang, readonly string[]> = {
  fr: [
    'janv.',
    'févr.',
    'mars',
    'avr.',
    'mai',
    'juin',
    'juill.',
    'août',
    'sept.',
    'oct.',
    'nov.',
    'déc.',
  ],
  en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
  es: ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'],
  ru: ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'],
};
const LONG: Record<Lang, readonly string[]> = {
  fr: [
    'janvier',
    'février',
    'mars',
    'avril',
    'mai',
    'juin',
    'juillet',
    'août',
    'septembre',
    'octobre',
    'novembre',
    'décembre',
  ],
  en: [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
  ],
  es: [
    'Enero',
    'Febrero',
    'Marzo',
    'Abril',
    'Mayo',
    'Junio',
    'Julio',
    'Agosto',
    'Septiembre',
    'Octubre',
    'Noviembre',
    'Diciembre',
  ],
  ru: [
    'Январь',
    'Февраль',
    'Март',
    'Апрель',
    'Май',
    'Июнь',
    'Июль',
    'Август',
    'Сентябрь',
    'Октябрь',
    'Ноябрь',
    'Декабрь',
  ],
};
const monthOf = (month: Month) => Number(month.slice(5, 7)) - 1;

/** `Oct 2026` */
const shortMonthYear = (lang: Lang, month: Month) =>
  `${SHORT[lang][monthOf(month)] ?? ''} ${month.slice(0, 4)}`;

/** `October 2026` */
export const longMonthYear = (lang: Lang, month: Month) =>
  `${LONG[lang][monthOf(month)] ?? ''} ${month.slice(0, 4)}`;

/** `13 November`, from a date `YYYY-MM-DD`. */
export const dateText = (lang: Lang, iso: string) =>
  new Intl.DateTimeFormat(LOCALES[lang], { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(
    new Date(`${iso}T12:00:00Z`),
  );

/** `1 – 31 July 2025`, or one date when the span is one day; from dates `YYYY-MM-DD`. */
export const dateSpanText = (lang: Lang, start: string, end: string) =>
  new Intl.DateTimeFormat(LOCALES[lang], {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).formatRange(new Date(`${start}T12:00:00Z`), new Date(`${end}T12:00:00Z`));

/** `October` */
export const longMonth =(lang: Lang, month: Month) => LONG[lang][monthOf(month)] ?? '';

/** `Oct` */
export const shortMonth = (lang: Lang, month: Month) => SHORT[lang][monthOf(month)] ?? '';

/** The twelve short names, January first. */
export const shortMonths = (lang: Lang): readonly string[] => SHORT[lang];

interface PeriodContext {
  /** The first month of the forecast, when the area has one. */
  forecast: MonthRange | null;
  /** The whole record, first to last month seen. */
  record: MonthRange;
}

/** The period in words: "2025", "Q1 2025", "March 2025", "Forecast, Oct 2026 – Mar 2027". */
export function periodTitle(
  t: I18n['t'],
  lang: Lang,
  range: MonthRange,
  context: PeriodContext,
): string {
  const from = monthIndex(range.from);
  const length = monthsIn(range);
  if (context.forecast && sameRange(range, context.forecast)) {
    return t('period.titleForecast', {
      a: shortMonthYear(lang, range.from),
      b: shortMonthYear(lang, range.to),
    });
  }
  if (sameRange(range, context.record)) {
    return t('period.titleWhole', { a: yearOf(range.from), b: yearOf(range.to) });
  }
  if (length === 1) return longMonthYear(lang, range.from);
  if (length === 12 && from % 12 === 0) return String(yearOf(range.from));
  if (length === 3 && from % 3 === 0) {
    return t('period.titleQuarter', { q: (from % 12) / 3 + 1, y: yearOf(range.from) });
  }
  return t('period.titleRange', {
    a: shortMonthYear(lang, range.from),
    b: shortMonthYear(lang, range.to),
  });
}

/** The words of a preset of the period menu. */
export function presetLabel(
  t: I18n['t'],
  lang: Lang,
  preset: { id: string; kind: string; first_month: Month; last_month: Month },
): string {
  const range = { from: preset.first_month, to: preset.last_month };
  if (preset.kind === 'forecast') return t('preset.forecast', { n: monthsIn(range) });
  if (preset.kind === 'season') {
    return t('preset.season', {
      a: shortMonth(lang, preset.first_month),
      b: shortMonth(lang, preset.last_month),
    });
  }
  return preset.id;
}

/** `detection`, `detections`: the word for a count of them in the language. */
export const detectionsWord = (t: I18n['t'], lang: Lang, n: number): string =>
  t(`detections.${new Intl.PluralRules(LOCALES[lang]).select(n)}` as 'detections.other');

/** What a day had: `1 324 detections`, and `fires: 296` when the fires of the day are known. */
export function dayFigures(
  t: I18n['t'],
  lang: Lang,
  detections: number,
  fires?: number | null,
): string[] {
  return [
    `${formatCount(lang, detections)} ${detectionsWord(t, lang, Math.round(detections))}`,
    ...(fires == null ? [] : [t('fires.count', { n: fires })]),
  ];
}
