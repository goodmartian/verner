import { LOCALES, type Lang } from '../i18n/lang';
import { formatLocalTime } from './time';

/** A calendar day (`YYYY-MM-DD`) in the language's way of writing a date, whatever the time zone. */
export function formatDay(lang: Lang, day: string): string {
  return new Intl.DateTimeFormat(LOCALES[lang], {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(new Date(`${day}T00:00:00Z`));
}

/** A moment as a short date and time in the language: "30 Oct, 14:05". */
export function formatWhen(lang: Lang, iso: string, zone: string | null): string {
  return formatLocalTime(LOCALES[lang], iso, zone, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}
