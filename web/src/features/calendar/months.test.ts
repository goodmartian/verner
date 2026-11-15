import { describe, expect, it } from 'vitest';
import { monthAt, monthIndex, monthsIn, sameRange, step, yearOf } from './months';

describe('months', () => {
  it('turns a month into a number and back', () => {
    expect(monthAt(monthIndex('2025-03'))).toBe('2025-03');
    expect(monthIndex('2025-01') - monthIndex('2024-12')).toBe(1);
    expect(yearOf('2024-12')).toBe(2024);
  });

  it('counts the months of a range', () => {
    expect(monthsIn({ from: '2025-01', to: '2025-12' })).toBe(12);
    expect(monthsIn({ from: '2025-03', to: '2025-03' })).toBe(1);
  });

  it('compares ranges', () => {
    expect(sameRange({ from: '2025-01', to: '2025-03' }, { from: '2025-01', to: '2025-03' })).toBe(
      true,
    );
    expect(sameRange({ from: '2025-01', to: '2025-03' }, { from: '2025-01', to: '2025-04' })).toBe(
      false,
    );
  });
});

describe('step', () => {
  const limits = { from: '2003-01', to: '2027-03' };

  it('moves a year to the year before and after', () => {
    const year = { from: '2024-01', to: '2024-12' };
    expect(step(year, -1, limits)).toEqual({ from: '2023-01', to: '2023-12' });
    expect(step(year, 1, limits)).toEqual({ from: '2025-01', to: '2025-12' });
  });

  it('cuts the last step short at the end of the data', () => {
    expect(step({ from: '2026-01', to: '2026-12' }, 1, limits)).toEqual({
      from: '2027-01',
      to: '2027-03',
    });
  });

  it('stops at either end', () => {
    expect(step({ from: '2027-01', to: '2027-03' }, 1, limits)).toBeNull();
    expect(step({ from: '2003-01', to: '2003-12' }, -1, limits)).toBeNull();
  });
});
