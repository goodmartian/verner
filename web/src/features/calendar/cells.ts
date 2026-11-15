import { LOCALES, type Lang } from '../../i18n/lang';
import { numberFormat } from '../../lib/numberFormat';

/** The unit the figures of the grid are shown in, said once in the caption so the cells carry only digits. */
export type Scale = 'plain' | 'thousand' | 'million';

const DIVISOR: Record<Scale, number> = { plain: 1, thousand: 1_000, million: 1_000_000 };

/** The unit for a grid whose biggest figure is `max`: a short number of at most three digits fits a cell. */
export function scaleOf(max: number): Scale {
  if (max >= 1_000_000) return 'million';
  if (max >= 10_000) return 'thousand';
  return 'plain';
}

/** A figure of the grid in its unit: one decimal under ten, whole above, whole as they are when there is no unit. */
export function cellText(lang: Lang, value: number, scale: Scale): string {
  const scaled = value / DIVISOR[scale];
  const digits = scale !== 'plain' && scaled < 10 ? 1 : 0;
  return numberFormat(LOCALES[lang], {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(scaled);
}
