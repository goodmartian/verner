import { localDay } from '../../lib/time';
export const HOUR = 3_600_000;
export const DAY = 24 * HOUR;

/** The day a moment falls on there, `YYYY-MM-DD`. */
export const dayKey = localDay;

/** The midnight that starts the day a moment falls on there. */
export function dayStart(ms: number, zone: string): number {
  const day = dayKey(ms, zone);
  let lo = ms - 36 * HOUR;
  let hi = ms;
  while (hi - lo > 1) {
    const mid = Math.floor((lo + hi) / 2);
    if (dayKey(mid, zone) < day) lo = mid;
    else hi = mid;
  }
  return hi;
}

export const nextDayStart = (ms: number, zone: string): number =>
  dayStart(dayStart(ms, zone) + 36 * HOUR, zone);

/** A bar of the scale: at `at`, `span` wide when it stands for a stretch of time, `height` the share of the tallest; none at all is a dot. */
export interface Bar {
  at: number;
  span?: number;
  height: number;
  color?: string;
  /** Drawn pale, for what is only forecast. */
  pale?: boolean;
  /** Rain fell in it: a blue dot under the bar. */
  rain?: boolean;
  /** Ringed: where it all began. */
  ring?: boolean;
  /** A few characters under the bar. */
  label?: string;
}

/** A thin line of the scale with a few words under it. */
export interface Tick {
  at: number;
  label: string;
}

/** A place the handle can stand on, and what standing on it means. */
export interface Step<T> {
  at: number;
  value: T;
}

/** The step closest to a moment. */
export function nearestStep<T>(steps: readonly Step<T>[], at: number): Step<T> | null {
  let best: Step<T> | null = null;
  for (const step of steps) {
    if (best === null || Math.abs(step.at - at) < Math.abs(best.at - at)) best = step;
  }
  return best;
}

/** The step after (1) or before (-1) a moment; null at the ends. */
export function neighbour<T>(
  steps: readonly Step<T>[],
  at: number | null,
  direction: 1 | -1,
): Step<T> | null {
  const sorted = [...steps].sort((a, b) => a.at - b.at);
  if (at === null) return (direction === 1 ? sorted[0] : sorted.at(-1)) ?? null;
  const ahead = direction === 1 ? sorted.filter((s) => s.at > at) : sorted.filter((s) => s.at < at);
  return (direction === 1 ? ahead[0] : ahead.at(-1)) ?? null;
}

/** A word that wants a place under the scale; the lower the rank the likelier it keeps it. */
export interface Label {
  key: string;
  at: number;
  text: string;
  /** `start`: the text begins at the line; `middle`: the line is in the middle of it; `end`: the text ends at it. */
  side: 'start' | 'middle' | 'end';
  rank: number;
  /** Its width in px when the text is not all there is to it. */
  width?: number;
  /** The labels of one group stand together or not at all. */
  group?: string;
}

const CHAR = 6;
const GAP = 2;

const boxOf = (label: Label, x: number): [number, number] => {
  const width = label.width ?? label.text.length * CHAR;
  if (label.side === 'end') return [x - width, x];
  return label.side === 'middle' ? [x - width / 2, x + width / 2] : [x + 3, x + 3 + width];
};

/** Which of the labels fit under a rail `width` px wide without touching: those of the lowest rank first, a group whole or not at all. */
export function fittingLabels(
  labels: readonly Label[],
  from: number,
  to: number,
  width: number,
): Set<string> {
  // not measured yet: show them all rather than none
  if (width <= 0) return new Set(labels.map((label) => label.key));
  const kept: [number, number][] = [];
  const shown = new Set<string>();
  const units = new Map<string, Label[]>();
  [...labels]
    .sort((a, b) => a.rank - b.rank)
    .forEach((label) => {
      const unit = units.get(label.group ?? label.key);
      if (unit) unit.push(label);
      else units.set(label.group ?? label.key, [label]);
    });
  for (const unit of units.values()) {
    const boxes = unit.map((label) => boxOf(label, ((label.at - from) / (to - from)) * width));
    const clear = boxes.every(([a, b], index) =>
      [...kept, ...boxes.slice(0, index)].every(([c, d]) => b + GAP <= c || d + GAP <= a),
    );
    if (clear) {
      kept.push(...boxes);
      unit.forEach((label) => shown.add(label.key));
    }
  }
  return shown;
}

/** The days of a stretch as lines of the scale: one at its start, and one at each midnight after. */
export function dayTicks(
  from: number,
  to: number,
  label: (day: string) => string,
  zone: string,
): Tick[] {
  const ticks: Tick[] = [];
  const first = dayStart(from, zone);
  const next = nextDayStart(from, zone);
  // a day that has barely begun gives its label to the next one
  const room = from === first || next - from >= 12 * HOUR;
  for (let at = room ? from : next; at < to; at = nextDayStart(at, zone)) {
    ticks.push({ at, label: label(dayKey(at, zone)) });
  }
  return ticks;
}

/** The width in px of the tag over the handle: its time and, under it in smaller type, what the map shows. */
export const tagWidth = (time: string, note: string | undefined): number =>
  Math.max(time.length * 6.6, (note?.length ?? 0) * 5.8) + 14;

/**
 * How far to move the tag over the handle, px, so that it stays within the scale (and the `margin` around the rail):
 * the handle at `x` of a rail `width` wide, the tag `tag` wide, centred on it before.
 */
export function tagShift(x: number, tag: number, width: number, margin: number): number {
  const left = x - tag / 2;
  return Math.min(Math.max(left, -margin), width + margin - tag) - left;
}
