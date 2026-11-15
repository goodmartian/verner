const cache = new Map<string, Intl.NumberFormat>();

/** A number formatter that is built once per language and options: building one costs far more than using it, and a grid asks for hundreds. */
export function numberFormat(
  locale: string | undefined,
  options: Intl.NumberFormatOptions = {},
): Intl.NumberFormat {
  const key = `${locale ?? ''}|${JSON.stringify(options)}`;
  let format = cache.get(key);
  if (!format) {
    format = new Intl.NumberFormat(locale, options);
    cache.set(key, format);
  }
  return format;
}
