import { INTEGER_ZONE } from '../../test/configFixtures';
import { describe, expect, it } from 'vitest';
import { DAY, HOUR } from '../timeline/scale';
import { passBars, passBounds, passSteps, passWalk } from './passScale';

const PASSES = [
  { time: '2026-10-28T04:34:00Z' },
  { time: '2026-10-28T18:38:00Z' },
  { time: '2026-10-30T02:16:00Z' },
];
const NOW = '2026-10-30T11:00:00Z';
const END = '2026-10-31T11:00:00Z';

describe('the scale of the passes', () => {
  it('runs from midnight of the first day to the end of the forecast', () => {
    const { from, to } = passBounds(PASSES[0]?.time, Date.parse(NOW), END, INTEGER_ZONE);
    expect(new Date(from).toISOString()).toBe('2026-10-27T06:00:00.000Z');
    expect(to).toBe(Date.parse(END));
  });

  it('is three days back from now and ends at now when there are no passes and no forecast', () => {
    const now = Date.parse(NOW);
    const { from, to } = passBounds(undefined, now, undefined, INTEGER_ZONE);
    expect(to).toBe(now);
    expect(now - from).toBeGreaterThanOrEqual(3 * DAY);
    expect(now - from).toBeLessThan(4 * DAY);
  });
});

describe('the bars of the passes', () => {
  it('are as tall as the detections, the tallest whole, none a dot', () => {
    const bars = passBars(PASSES, [50, 0, 100]);
    expect(bars.map((bar) => bar.height)).toEqual([0.5, 0, 1]);
    expect(bars[0]?.at).toBe(Date.parse(PASSES[0]?.time ?? ''));
  });
});

const HOURS = ['2026-10-30T11:00:00Z', '2026-10-30T12:00:00Z', '2026-10-30T13:00:00Z'];

describe('the places of the handle on the passes', () => {
  it('are the passes, the hours from now, and the marks of the forecast', () => {
    const steps = passSteps(PASSES, HOURS, NOW, []);
    expect(steps.map((step) => step.value.kind)).toEqual([
      'pass',
      'pass',
      'pass',
      'clock',
      'clock',
      'clock',
    ]);
  });

  it('give the hours beside a mark to it, and keep now', () => {
    const marks = [{ hours: 1 as const, at: Date.parse('2026-10-30T12:20:00Z') }];
    const steps = passSteps(PASSES, HOURS, NOW, marks);
    const hours = steps.flatMap((step) => (step.value.kind === 'clock' ? [step.value.hour] : []));
    // 12:00 and 13:00 are within the hour of the mark, 11:00 is now
    expect(hours).toEqual(['2026-10-30T11:00:00Z']);
    expect(steps.at(-1)?.value).toEqual({ kind: 'forecast', hours: 1 });
    expect(marks[0]?.at).toBeGreaterThan(Date.parse(NOW) + HOUR);
  });
});

describe('what play walks', () => {
  it('is every pass, then the hours of the forecast three apart', () => {
    const walk = passWalk(PASSES, NOW, END);
    expect(walk.slice(0, 3).map((step) => step.kind)).toEqual(['pass', 'pass', 'pass']);
    const hours = walk.flatMap((step) => (step.kind === 'clock' ? [step.hour] : []));
    expect(hours[0]).toBe(NOW);
    expect(hours[1]).toBe('2026-10-30T14:00:00Z');
    expect(hours.at(-1)).toBe(END);
  });

  it('is the passes alone when there is no forecast', () => {
    expect(passWalk(PASSES, NOW, undefined)).toHaveLength(3);
  });
});
