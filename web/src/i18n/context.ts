import { createContext, useContext } from 'react';
import type { MessageKey } from './en';
import type { Lang, LangPref } from './lang';

export interface I18n {
  lang: Lang;
  locale: string;
  pref: LangPref;
  setPref: (pref: LangPref) => void;
  /** A message; `{name}` in it is replaced by the value given under `name`. */
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}

export const I18nContext = createContext<I18n | null>(null);

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (!value) throw new Error('useI18n needs an I18nProvider above it');
  return value;
}
