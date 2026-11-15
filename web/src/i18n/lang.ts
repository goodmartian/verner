import { readStored } from '../lib/storage';

/** Translation capabilities; enabled languages come from config. */
const CATALOG = {
  en: { name: 'English', locale: 'en-GB' },
  fr: { name: 'Français', locale: 'fr-CA' },
  es: { name: 'Español', locale: 'es' },
  ru: { name: 'Русский', locale: 'ru' },
} as const;
export type Lang = keyof typeof CATALOG;
export type LangPref = Lang | 'auto';

export const language = (code: Lang) => CATALOG[code];
export const LOCALES = Object.fromEntries(
  Object.entries(CATALOG).map(([code, value]) => [code, value.locale]),
) as Record<Lang, string>;

export const LANG_STORAGE_KEY = 'senda-lang';

export const isLang = (value: unknown): value is Lang =>
  typeof value === 'string' && Object.hasOwn(CATALOG, value);

export function readLangPref(): LangPref {
  const stored = readStored(LANG_STORAGE_KEY);
  return isLang(stored) ? stored : 'auto';
}

export function resolveLang(
  pref: LangPref,
  systemLanguages: readonly string[],
  available: readonly { code: Lang; locale: string }[],
): Lang {
  if (pref !== 'auto' && available.some((item) => item.code === pref)) return pref;
  for (const tag of systemLanguages) {
    const code =
      available.find((item) => item.locale.toLowerCase() === tag.toLowerCase())?.code ??
      available.find((item) => item.code === tag.split('-')[0]?.toLowerCase())?.code;
    if (code) return code;
  }
  return available[0]?.code ?? 'en';
}

export const localName = (names: Partial<Record<Lang, string>>, lang: Lang): string =>
  [names[lang], names.en, ...Object.values(names)].find(
    (name) => name !== undefined && name.trim() !== '',
  ) ?? '';
