import { en, type MessageKey, type Messages } from './en';
import { es } from './es';
import { fr } from './fr';
import type { Lang } from './lang';
import { ru } from './ru';

export const MESSAGES: Record<Lang, Messages> = { en, fr, es, ru };

/** A message in a language; `{name}` in it is replaced by the value given under `name`. */
export function translate(
  lang: Lang,
  key: MessageKey,
  params?: Record<string, string | number>,
): string {
  return MESSAGES[lang][key].replace(/\{(\w+)\}/g, (whole, name: string) =>
    String(params?.[name] ?? whole),
  );
}
