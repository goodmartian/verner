import type { ClimateMonth } from './types';
import type { I18n } from '../../i18n/context';
import { LOCALES, type Lang } from '../../i18n/lang';

const signed = (lang: Lang, n: number) =>
  new Intl.NumberFormat(LOCALES[lang], { signDisplay: 'exceptZero', maximumFractionDigits: 1 })
    .format(n)
    .replace('-', '−');

const percent = (lang: Lang, ratio: number) =>
  new Intl.NumberFormat(LOCALES[lang], { maximumFractionDigits: 0 }).format(ratio * 100);

/**
 * The weather of a month in one line: the temperature against the normal and the rain as a share of it.
 * Null when there is nothing to say: a month the server has no weather for is not a month that is loading.
 */
export function monthLine(
  t: I18n['t'],
  lang: Lang,
  month: ClimateMonth | null | undefined,
): string | null {
  if (month?.kind !== 'observed' || !month.observed) return null;
  const by = new Map(month.observed.quantities.map((item) => [item.key, item]));
  const parts: string[] = [];
  const temperature = by.get('temperature_c')?.anomaly;
  if (temperature !== null && temperature !== undefined) {
    parts.push(t('clim.temp', { n: signed(lang, temperature) }));
  }
  const rain = by.get('rain_mm');
  if (rain?.anomaly !== null && rain?.anomaly !== undefined && rain.anomaly_kind === 'ratio') {
    parts.push(t('clim.rain', { n: percent(lang, rain.anomaly) }));
  }
  return parts.length > 0 ? parts.join(', ') : null;
}
