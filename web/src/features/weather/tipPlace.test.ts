import { describe, expect, it } from 'vitest';
import { placeTip } from './tipPlace';

const SIZE = { width: 200, height: 50 };
const AREA = { width: 1000, height: 600 };
// a strip along the top of the map, 60 px tall
const STRIP = { left: 0, top: 0, right: 1000, bottom: 60 };

describe('the place of the card of the pointer', () => {
  it('is below and right of the pointer when there is room', () => {
    expect(placeTip({ x: 300, y: 300 }, SIZE, AREA, [])).toEqual({
      left: 314,
      top: 314,
      flipX: false,
      flipY: false,
    });
  });

  it('turns to the left of the pointer at the right edge, and stays off the pointer itself', () => {
    const place = placeTip({ x: 980, y: 590 }, SIZE, AREA, []);
    expect(place.flipX).toBe(true);
    // it hangs from a corner at the left of the pointer, inside the map
    expect(place.left).toBeLessThan(980);
    expect(place.top).toBeLessThanOrEqual(AREA.height - 8);
  });

  it('gives way to what stands over the map: under the pointer is a strip, so it goes beside', () => {
    // the pointer is just under the strip at the top; the card would be right under it, clear of it
    const clear = placeTip({ x: 300, y: 70 }, SIZE, AREA, [STRIP]);
    expect(clear.top).toBeGreaterThanOrEqual(60);
    // a player over the lower right: the card turns up and away from it
    const player = { left: 500, top: 520, right: 1000, bottom: 600 };
    const place = placeTip({ x: 700, y: 480 }, SIZE, AREA, [player]);
    expect(place.flipY).toBe(true);
    expect(place.top).toBeLessThanOrEqual(480);
  });

  it('takes the first place inside the map when every place is blocked', () => {
    const all = { left: 0, top: 0, right: 1000, bottom: 600 };
    expect(placeTip({ x: 300, y: 300 }, SIZE, AREA, [all]).flipX).toBe(false);
  });
});
