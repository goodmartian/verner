import type { Lang } from './lang';

/** Runtime extension until the API's generated types include type_label. */
export function regionLabel(
  value: unknown,
  lang: Lang,
  form: 'one' | 'other',
  fallback: string,
): string {
  if (!value || typeof value !== 'object' || !('type_label' in value)) return fallback;
  const labels: unknown = value.type_label;
  if (!labels || typeof labels !== 'object' || !(lang in labels)) return fallback;
  const label: unknown = labels[lang as keyof typeof labels];
  if (!label || typeof label !== 'object' || !(form in label)) return fallback;
  const text: unknown = label[form as keyof typeof label];
  return typeof text === 'string' && text ? text : fallback;
}
