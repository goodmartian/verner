import { describe, expect, it } from 'vitest';
import { FOLD_AT, OPEN_AT, folded } from './foldOnScroll';

describe('folded', () => {
  it('stays open at the top and folds once the board leaves it', () => {
    expect(folded(false, 0)).toBe(false);
    expect(folded(false, FOLD_AT)).toBe(false);
    expect(folded(false, FOLD_AT + 1)).toBe(true);
  });

  it('stays folded between the two edges, so a small scroll back does not flicker', () => {
    expect(folded(true, FOLD_AT)).toBe(true);
    expect(folded(true, OPEN_AT + 1)).toBe(true);
    expect(folded(false, OPEN_AT + 1)).toBe(false);
  });

  it('opens back at the very top', () => {
    expect(folded(true, OPEN_AT)).toBe(false);
    expect(folded(true, 0)).toBe(false);
  });
});
