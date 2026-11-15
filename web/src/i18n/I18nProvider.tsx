import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { writeStored } from '../lib/storage';
import { I18nContext, type I18n } from './context';
import type { MessageKey } from './en';
import { LANG_STORAGE_KEY, readLangPref, resolveLang, type LangPref } from './lang';
import { translate } from './translate';
import { useConfig } from '../config/context';

export function I18nProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<LangPref>(readLangPref);
  const config = useConfig();
  const lang = resolveLang(pref, navigator.languages, config?.languages ?? []);
  const locale = config?.languages.find((item) => item.code === lang)?.locale ?? lang;

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const value = useMemo<I18n>(
    () => ({
      lang,
      locale,
      pref,
      setPref: (next) => {
        writeStored(LANG_STORAGE_KEY, next);
        setPrefState(next);
      },
      t: (key: MessageKey, params?: Record<string, string | number>) =>
        translate(lang, key, params),
    }),
    [lang, locale, pref],
  );

  return <I18nContext value={value}>{children}</I18nContext>;
}
