/** Every displayed instant uses a supplied place zone. Unknown zones have no guessed clock. */
export function formatLocalTime(
  locale: string,
  iso: string | number,
  zone: string | null,
  options: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' },
): string {
  if (!zone) return '';
  return new Intl.DateTimeFormat(locale, {
    ...options,
    timeZone: zone,
    timeZoneName: 'shortOffset',
  }).format(new Date(iso));
}

/** A date key in the place zone, independent of the browser's zone and language. */
export function localDay(ms: number, zone: string): string {
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(ms);
  const get = (kind: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === kind)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

/** The area's current UTC offset, including daylight saving and fractional hours. */
export function utcOffsetLabel(zone: string, at: number = Date.now()): string {
  const offset =
    new Intl.DateTimeFormat('en', {
      timeZone: zone,
      timeZoneName: 'shortOffset',
    })
      .formatToParts(at)
      .find((part) => part.type === 'timeZoneName')?.value ?? '';
  return offset.replace(/^GMT/, 'UTC').replace('-', '−');
}
