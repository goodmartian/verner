import { describe, expect, it } from 'vitest';
import { fitPadding } from './framing';

const PADDING = { top: 72, right: 24, bottom: 72, left: 24 };

describe('fitPadding', () => {
  it('keeps the padding when the window is big enough', () => {
    expect(fitPadding(PADDING, 600, 500)).toEqual(PADDING);
  });

  it('leaves the region at least 40 % of the height when the window is short', () => {
    const fitted = fitPadding(PADDING, 600, 200);
    expect(fitted.top + fitted.bottom).toBeLessThanOrEqual(120);
    expect(fitted.top).toBe(fitted.bottom);
    expect(fitted.left).toBe(24);
  });

  it('does the same for the width, on its own', () => {
    const fitted = fitPadding(PADDING, 60, 500);
    expect(fitted.left + fitted.right).toBeLessThanOrEqual(36);
    expect(fitted.top).toBe(72);
  });

  it('never goes below nothing', () => {
    const fitted = fitPadding(PADDING, 0, 0);
    expect(Object.values(fitted).every((value) => value >= 0)).toBe(true);
  });
});
