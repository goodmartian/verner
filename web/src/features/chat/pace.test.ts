import { describe, expect, it } from 'vitest';
import { advance, DRAIN_SECONDS, FINISH_SPEED, head, MIN_SPEED } from './pace';

const FRAME = 1 / 60;

describe('advance', () => {
  it('lets a trickle out at the slowest pace, not faster', () => {
    // a few characters waiting: the pace is the floor, MIN_SPEED a second
    const after = advance(0, 5, 1, false);
    expect(after).toBe(5);
    const step = advance(100, 105, FRAME, false) - 100;
    expect(step).toBeCloseTo(MIN_SPEED * FRAME, 5);
  });

  it('goes faster the more is waiting, so that the backlog is out in about DRAIN_SECONDS', () => {
    const small = advance(0, 60, FRAME, false);
    const large = advance(0, 6000, FRAME, false);
    expect(large).toBeGreaterThan(small * 10);
    expect(large).toBeCloseTo((6000 / DRAIN_SECONDS) * FRAME, 3);
  });

  it('drains a backlog to the end in a bounded time, with no tail of slow characters', () => {
    let at = 0;
    let seconds = 0;
    while (at < 2000 && seconds < 10) {
      at = advance(at, 2000, FRAME, false);
      seconds += FRAME;
    }
    expect(at).toBe(2000);
    expect(seconds).toBeLessThan(3);
  });

  it('writes the rest fast once the answer is over', () => {
    const slow = advance(0, 300, FRAME, false);
    const fast = advance(0, 300, FRAME, true);
    expect(fast).toBeGreaterThan(slow);
    expect(advance(0, 20, FRAME, true)).toBeCloseTo(FINISH_SPEED * FRAME, 5);
    let at = 0;
    let frames = 0;
    while (at < 1500) {
      at = advance(at, 1500, FRAME, true);
      frames += 1;
    }
    expect(frames * FRAME).toBeLessThan(0.8);
  });

  it('never goes past the end or back, and stays at the end', () => {
    expect(advance(10, 12, 5, false)).toBe(12);
    expect(advance(12, 12, FRAME, false)).toBe(12);
    // the text became shorter than where it had got to
    expect(advance(30, 12, FRAME, false)).toBe(12);
    expect(advance(3, 100, 0, false)).toBe(3);
  });
});

describe('head', () => {
  it('cuts a text to a count of characters', () => {
    expect(head('abcdef', 3)).toBe('abc');
    expect(head('abc', 9)).toBe('abc');
  });

  it('does not cut a character made of two units in half', () => {
    expect(head('a🔥b', 2)).toBe('a🔥');
  });
});
