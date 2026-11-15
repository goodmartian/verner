import { tailHours } from '../weather/time';
import { HOUR, dayStart, type Bar, type Step } from '../timeline/scale';

/** The hours of the growth forecast of a fire, after its last pass. */
export const FORECAST_HOURS = [1, 3, 6] as const;

/** Where the handle of the passes can stand. */
export type Moment =
  | { kind: 'pass'; index: number }
  | { kind: 'clock'; hour: string }
  | { kind: 'forecast'; hours: (typeof FORECAST_HOURS)[number] };

interface Pass {
  time: string;
}

/** The scale: from midnight of the first day of passes to the end of the weather forecast, or to now when there is none. */
export function passBounds(
  first: string | undefined,
  now: number,
  end: string | undefined,
  zone: string,
) {
  const from = dayStart(first ? Date.parse(first) : now - 3 * 24 * HOUR, zone);
  return { from, to: Math.max(end ? Date.parse(end) : now, now) };
}

/** A bar for each pass, as tall as the detections it had; with none it is a dot. */
export function passBars(passes: readonly Pass[], series: readonly number[]): Bar[] {
  const tallest = Math.max(1, ...series);
  return passes.map((pass, index) => ({
    at: Date.parse(pass.time),
    height: (series[index] ?? 0) / tallest,
  }));
}

/** The places for the handle: the passes, every hour from now on, and the marks of the forecast, which take the hours beside them. */
export function passSteps(
  passes: readonly Pass[],
  hours: readonly string[],
  now: string,
  marks: readonly { hours: (typeof FORECAST_HOURS)[number]; at: number }[],
): Step<Moment>[] {
  return [
    ...passes.map((pass, index) => ({
      at: Date.parse(pass.time),
      value: { kind: 'pass', index } as const,
    })),
    ...hours
      .filter(
        (hour) =>
          hour === now || marks.every((mark) => Math.abs(Date.parse(hour) - mark.at) >= HOUR),
      )
      .map((hour) => ({ at: Date.parse(hour), value: { kind: 'clock', hour } as const })),
    ...marks.map((mark) => ({
      at: mark.at,
      value: { kind: 'forecast', hours: mark.hours } as const,
    })),
  ];
}

/** What play goes through: every pass, then the hours of the forecast, three apart. */
export function passWalk(passes: readonly Pass[], now: string, end: string | undefined): Moment[] {
  return [
    ...passes.map((_, index): Moment => ({ kind: 'pass', index })),
    ...(end ? tailHours(now, end) : []).map((hour): Moment => ({ kind: 'clock', hour })),
  ];
}
