import { describe, expect, it } from 'vitest';
import { cellText, scaleOf } from './cells';

describe('figures of the grid', () => {
  it('picks the unit by the biggest figure', () => {
    expect(scaleOf(900)).toBe('plain');
    expect(scaleOf(9_999)).toBe('plain');
    expect(scaleOf(10_000)).toBe('thousand');
    expect(scaleOf(999_999)).toBe('thousand');
    expect(scaleOf(1_200_000)).toBe('million');
  });
  it('shows a short number without a word in every language', () => {
    expect(cellText('en', 19_541, 'thousand')).toBe('20');
    expect(cellText('en', 6_600, 'thousand')).toBe('6.6');
    expect(cellText('en', 800, 'thousand')).toBe('0.8');
    expect(cellText('ru', 6_600, 'thousand')).toBe('6,6');
    expect(cellText('fr', 6_600, 'thousand')).toBe('6,6');
    expect(cellText('es', 6_600, 'thousand')).toBe('6,6');
    expect(cellText('en', 1_100_000, 'million')).toBe('1.1');
    expect(cellText('en', 842, 'plain')).toBe('842');
  });
  it('keeps every figure under four characters in a unit', () => {
    for (const value of [0, 49, 999, 9_950, 10_000, 99_999, 999_499]) {
      expect(cellText('en', value, 'thousand').length).toBeLessThanOrEqual(4);
    }
  });
});
