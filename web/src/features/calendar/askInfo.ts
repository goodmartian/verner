import type { Calendar } from '../../api/calendar';
import { useI18n, type I18n } from '../../i18n/context';
import { LOCALES, type Lang } from '../../i18n/lang';
import type { AskInfo } from '../../ui/AskPop';
import { useWidgetActions } from '../chat/actions';
import { useAreaName } from './areas';
import { detectionsWord, formatCount, longMonthYear, monthVerdict } from './text';

type Point = Calendar['series'][number];

/**
 * What a month says about itself: its number (a forecast is marked as one), then how it stands against the usual one.
 * Null for a month with neither a count nor a forecast.
 */
export function monthFacts(
  t: I18n['t'],
  lang: Lang,
  point: Point,
): { value: string; note?: string } | null {
  const ahead = point.count === null ? point.forecast : null;
  if (point.count === null && !ahead) return null;
  const times = (x: number) =>
    new Intl.NumberFormat(LOCALES[lang], { maximumFractionDigits: 1 }).format(x);
  const n = point.median === null ? null : formatCount(lang, point.median);
  const ratio = point.ratio;
  const kind = monthVerdict(point);
  const note = ahead
    ? n === null
      ? undefined
      : t('pop.forecast', {
          lo: formatCount(lang, ahead.low),
          hi: formatCount(lang, ahead.high),
          n,
        })
    : n === null
      ? undefined
      : kind !== 'few' && ratio !== null && ratio >= 1.25
        ? t('pop.normHi', { n, x: times(ratio) })
        : kind !== 'few' && ratio !== null && ratio > 0 && ratio <= 0.8
          ? t('pop.normLo', { n, x: times(1 / ratio) })
          : t('pop.norm', { n });
  const count = point.count;
  return {
    value:
      count === null
        ? formatCount(lang, ahead?.median ?? 0, true)
        : `${formatCount(lang, count)} ${detectionsWord(t, lang, count)}`,
    note,
  };
}

/**
 * The cards of the board's figures: what each says and what its button does. Null where there is no chat to take the figure
 * (a board shown by itself), and the figures are then plain.
 */
export function useAskers() {
  const { t, lang } = useI18n();
  const actions = useWidgetActions();
  const area = useAreaName();
  if (!actions) return null;
  return {
    /** A figure of a card (a year, a row, a tile, a day): it goes into the question as a line of context. */
    fact: (
      label: string,
      value: string,
      period: string,
      options: { note?: string; area?: string; show?: AskInfo['show'] } = {},
    ): AskInfo => {
      const where = options.area ?? area ?? '';
      return {
        title: where ? `${label}, ${where}` : label,
        value,
        note: options.note,
        show: options.show,
        ask: () => {
          actions.addFact({ label, value, area: where, period });
        },
      };
    },
    /** A month of the series: its number against the usual one; the month itself goes into the question. */
    month: (point: Point): AskInfo | null => {
      const facts = monthFacts(t, lang, point);
      if (!facts) return null;
      return {
        title: area
          ? `${longMonthYear(lang, point.month)}, ${area}`
          : longMonthYear(lang, point.month),
        ...facts,
        ask: () => {
          actions.addMonth(point.month);
        },
      };
    },
  };
}
