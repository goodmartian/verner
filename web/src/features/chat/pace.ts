/** The slowest the text is let out, in characters a second, so that a trickle of tokens still reads as writing. */
export const MIN_SPEED = 40;
/** The backlog is let out in about this long: the more there is waiting, the faster. */
export const DRAIN_SECONDS = 0.4;
/** When the answer is over what is left is written in about this long, and never slower than this many characters a second. */
export const FINISH_SECONDS = 0.15;
export const FINISH_SPEED = 600;

/**
 * Where the text has got to after `dt` seconds: how many characters of `total` are out, as a fraction of one. The speed
 * follows the backlog, and at the end the rest comes fast.
 */
export function advance(shown: number, total: number, dt: number, finishing: boolean): number {
  const backlog = total - shown;
  if (backlog <= 0) return total;
  const speed = finishing
    ? Math.max(FINISH_SPEED, backlog / FINISH_SECONDS)
    : Math.max(MIN_SPEED, backlog / DRAIN_SECONDS);
  return Math.min(total, shown + speed * dt);
}

/** The first `count` characters of a text, whole code points. */
export function head(text: string, count: number): string {
  if (count >= text.length) return text;
  const high = text.charCodeAt(count - 1);
  return text.slice(0, high >= 0xd800 && high <= 0xdbff ? count + 1 : count);
}
