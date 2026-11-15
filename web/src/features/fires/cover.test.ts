import { describe, expect, it } from 'vitest';
import { coverKey, coverSummary } from './cover';

const names = (name: string) => ({ en: name, ru: name, es: name, fr: name });

describe('coverKey', () => {
  it('lists the classes the grid really has, the widest first, and never the unpainted one', () => {
    // 100 cells: 60 grass (3), 39 forest (1), 1 water (8), no cell of class 0
    const data = '3'.repeat(60) + '1'.repeat(39) + '8';
    const key = coverKey({
      width: 10,
      height: 10,
      data,
      classes: [
        { id: 0, name: names('No data'), color: '#000000' },
        { id: 1, name: names('Forest'), color: '#2e7d32' },
        { id: 3, name: names('Grass'), color: '#a8c256' },
        { id: 8, name: names('Water'), color: '#3b82c4' },
      ],
    });
    expect(key.map((item) => item.id)).toEqual([3, 1]);
  });
});

describe('coverSummary', () => {
  const classes = [
    { id: 1, name: names('Forest'), color: '#2e7d32' },
    { id: 2, name: names('Scrub'), color: '#b5a642' },
    { id: 3, name: names('Grass'), color: '#a8c256' },
    { id: 4, name: names('Fields'), color: '#e8d27a' },
  ];
  const say = (shares: { id: number; share_pct: number }[]) =>
    coverSummary({ classes, shares }, (n) => n.en, 'en');

  it('writes the main classes with their shares, the first with a capital', () => {
    expect(
      say([
        { id: 1, share_pct: 61.5 },
        { id: 3, share_pct: 38.1 },
      ]),
    ).toBe('Forest 62\u00a0%, grass 38\u00a0%');
  });

  it('keeps three at most and leaves out what is under one percent', () => {
    expect(
      say([
        { id: 1, share_pct: 50 },
        { id: 2, share_pct: 25 },
        { id: 3, share_pct: 24 },
        { id: 4, share_pct: 1 },
      ]),
    ).toBe('Forest 50\u00a0%, scrub 25\u00a0%, grass 24\u00a0%');
    expect(
      say([
        { id: 1, share_pct: 99.6 },
        { id: 2, share_pct: 0.4 },
      ]),
    ).toBe('Forest 100\u00a0%');
  });

  it('says nothing when the outline has no data', () => {
    expect(say([])).toBe('');
  });
});
