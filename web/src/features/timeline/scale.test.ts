import { INTEGER_ZONE } from '../../test/configFixtures';
import { describe, expect, it } from 'vitest';
import {
  DAY,
  HOUR,
  dayStart,
  dayTicks,
  fittingLabels,
  nearestStep,
  neighbour,
  tagShift,
  tagWidth,
  type Label,
  type Step,
} from './scale';

describe('the days there', () => {
  it('start at midnight in the explicit place zone', () => {
    expect(new Date(dayStart(Date.parse('2026-10-30T08:00:00Z'), INTEGER_ZONE)).toISOString()).toBe(
      '2026-10-30T06:00:00.000Z',
    );
    // Before local midnight it is still the previous day.
    expect(new Date(dayStart(Date.parse('2026-10-30T02:00:00Z'), INTEGER_ZONE)).toISOString()).toBe(
      '2026-10-29T06:00:00.000Z',
    );
  });

  it('are lines of the scale: one at its start and one at each midnight after', () => {
    const from = Date.parse('2026-10-28T06:00:00Z');
    const ticks = dayTicks(from, from + 3 * DAY + 5 * HOUR, (day) => day, INTEGER_ZONE);
    expect(ticks.map((tick) => tick.label)).toEqual([
      '2026-10-28',
      '2026-10-29',
      '2026-10-30',
      '2026-10-31',
    ]);
    expect(ticks[1]?.at).toBe(from + DAY);
  });

  it('give a day that has barely begun to the next one', () => {
    const from = Date.parse('2026-10-28T23:00:00Z');
    const ticks = dayTicks(from, from + 2 * DAY, (day) => day, INTEGER_ZONE);
    expect(ticks.map((tick) => tick.label)).toEqual(['2026-10-29', '2026-10-30']);
  });
});

const STEPS: Step<string>[] = [
  { at: 10, value: 'a' },
  { at: 20, value: 'b' },
  { at: 50, value: 'c' },
];

describe('the places of the handle', () => {
  it('take the nearest step to a moment, none when there are none', () => {
    expect(nearestStep(STEPS, 14)?.value).toBe('a');
    expect(nearestStep(STEPS, 36)?.value).toBe('c');
    expect(nearestStep(STEPS, 1000)?.value).toBe('c');
    expect(nearestStep([], 5)).toBeNull();
  });

  it('go on to the next and the one before, and stop at the ends', () => {
    expect(neighbour(STEPS, 20, 1)?.value).toBe('c');
    expect(neighbour(STEPS, 20, -1)?.value).toBe('a');
    expect(neighbour(STEPS, 50, 1)).toBeNull();
    expect(neighbour(STEPS, 10, -1)).toBeNull();
    expect(neighbour(STEPS, null, 1)?.value).toBe('a');
    expect(neighbour(STEPS, null, -1)?.value).toBe('c');
  });
});

const label = (key: string, at: number, text: string, rank: number, group?: string): Label => ({
  key,
  at,
  text,
  side: 'middle',
  rank,
  ...(group ? { group } : {}),
});

describe('the words under the scale', () => {
  it('all show while the width is not known', () => {
    const words = [label('a', 0, 'one', 0), label('b', 1, 'two', 0)];
    expect([...fittingLabels(words, 0, 100, 0)]).toEqual(['a', 'b']);
  });

  it('the one of the lower rank keeps its place when two touch', () => {
    // a rail of 100 px for 100 units: the words at 40 and 45 are in each other's way
    const words = [label('late', 45, 'later', 1), label('first', 40, 'first', 0)];
    expect([...fittingLabels(words, 0, 100, 100)]).toEqual(['first']);
  });

  it('a group stands whole or not at all', () => {
    const words = [
      label('x', 10, '+1', 0, 'marks'),
      label('y', 14, '+3', 0, 'marks'),
      label('z', 60, 'day', 1),
    ];
    // 4 px apart: the two do not fit side by side, so neither is shown; the word far from them is
    expect([...fittingLabels(words, 0, 100, 100)]).toEqual(['z']);
    expect([...fittingLabels(words, 0, 100, 1000)].sort()).toEqual(['x', 'y', 'z']);
  });
});

describe('the tag over the handle', () => {
  it('is as wide as its longer line needs', () => {
    expect(tagWidth('30 Oct, 03:00', undefined)).toBeLessThan(
      tagWidth('30 Oct, 03:00', 'outline forecast +3 h'),
    );
  });

  it('stays where it is while it is inside the scale', () => {
    expect(tagShift(300, 80, 600, 22)).toBe(0);
  });

  it('is pressed to the ends of the scale, to within the margin of its rail', () => {
    // the handle at the very start: half of an 80 px tag would stick out by 40, 22 are allowed
    expect(tagShift(0, 80, 600, 22)).toBe(18);
    expect(tagShift(600, 80, 600, 22)).toBe(-18);
  });
});
