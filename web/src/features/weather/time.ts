const HOUR = 3_600_000;

/** The hour nearest to a moment, as the server writes it: `2026-10-30T14:00:00Z`. */
export function nearestHour(ms: number): string {
  return new Date(Math.round(ms / HOUR) * HOUR).toISOString().replace('.000Z', 'Z');
}

/** The hour a moment is in. */
export function thisHour(ms: number): string {
  return new Date(Math.floor(ms / HOUR) * HOUR).toISOString().replace('.000Z', 'Z');
}

/** Whether the hour is one the data has; there is no guessing beyond its ends. */
export function inSpan(span: { start: string; end: string } | null | undefined, hour: string) {
  if (!span) return false;
  const at = Date.parse(hour);
  return at >= Date.parse(span.start) && at <= Date.parse(span.end);
}

/** Where an hour stands in a series that starts at `start`, an hour apart; null when the series does not reach it. */
export function seriesIndex(start: string | null, length: number, hour: string): number | null {
  if (!start) return null;
  const index = Math.round((Date.parse(hour) - Date.parse(start)) / HOUR);
  return index >= 0 && index < length ? index : null;
}

/** The hours of the forecast tail of the player: from now to the end of the data, every `step` hours, the end last. */
export function tailHours(now: string, end: string, step = 3): string[] {
  const hours: string[] = [];
  const last = Date.parse(end);
  for (let at = Date.parse(now); at < last; at += step * HOUR) {
    hours.push(new Date(at).toISOString().replace('.000Z', 'Z'));
  }
  if (last >= Date.parse(now)) hours.push(new Date(last).toISOString().replace('.000Z', 'Z'));
  return hours;
}

interface MomentInput {
  /** The row of passes is open. */
  player: boolean;
  /** An hour of the forecast tail picked in it. */
  clock: string | null;
  /** The time of the pass on screen, and the hours of the front forecast added to it. */
  pass: string | null;
  forecast: number;
  now: string;
}

/** The hour the weather is shown for: the one of the player when it is open, else the present hour. */
export function weatherMoment({ player, clock, pass, forecast, now }: MomentInput): string {
  if (!player) return now;
  if (clock) return clock;
  return pass ? nearestHour(Date.parse(pass) + forecast * HOUR) : now;
}
