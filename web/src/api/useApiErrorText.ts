import { ApiError } from './client';
import { errorKey } from './errors';
import { useConfig } from '../config/context';
import { useI18n } from '../i18n/context';
import { localName } from '../i18n/lang';

export function useApiErrorText() {
  const config = useConfig();
  const { t, lang } = useI18n();
  return (error: unknown): string => {
    if (error instanceof ApiError && error.code === 'not_covered')
      return t('error.not_covered', {
        countries: (config?.countries ?? error.coveredCountries)
          .map((country) => localName(country.names, lang))
          .filter(Boolean)
          .join(', '),
      });
    // a refusal for a while says how long, in whole minutes
    if (
      error instanceof ApiError &&
      (error.code === 'chat_quota' || error.code === 'chat_banned' || error.code === 'export_quota')
    )
      return t(errorKey(error), { minutes: Math.max(1, Math.ceil((error.retryAfter ?? 60) / 60)) });
    return t(errorKey(error));
  };
}
