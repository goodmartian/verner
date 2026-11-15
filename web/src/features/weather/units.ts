import type { I18n } from '../../i18n/context';

const KEYS = { 'km/h': 'unit.kmh', 'mm/h': 'unit.mmh', kPa: 'unit.kpa' } as const;

/** The unit of a layer as the server names it, written in the language of the screen; a unit it does not know stays as it came. */
export function unitText(t: I18n['t'], unit: string): string {
  const key = (KEYS as Record<string, (typeof KEYS)[keyof typeof KEYS]>)[unit];
  return key ? t(key) : unit;
}
