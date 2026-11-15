import { describe, expect, it } from 'vitest';
import { contrast, legibleOn, MAP_GROUND } from './contrast';

describe('contrast', () => {
  it('is 21 for black on white and 1 for a colour on itself', () => {
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 0);
    expect(contrast('#8fd0ef', '#8fd0ef')).toBeCloseTo(1, 5);
  });
});

describe('legibleOn', () => {
  it('leaves a colour that already stands out', () => {
    expect(legibleOn('#b8222d')).toBe('#b8222d');
    expect(legibleOn('#e8743b', MAP_GROUND, 2)).toBe('#e8743b');
  });

  it('takes the pale blues of the calm bands toward the ink until they reach three to one', () => {
    for (const pale of ['#d9f0fb', '#8fd0ef', '#4aa6dd', '#f2c14e']) {
      const color = legibleOn(pale);
      expect(contrast(color, MAP_GROUND)).toBeGreaterThanOrEqual(3);
      expect(color).not.toBe(pale);
    }
  });

  it('keeps the hue: a darkened blue is still bluer than it is red', () => {
    const [red = 0, , blue = 0] = [1, 3, 5].map((at) =>
      Number.parseInt(legibleOn('#8fd0ef').slice(at, at + 2), 16),
    );
    expect(blue).toBeGreaterThan(red);
  });
});
