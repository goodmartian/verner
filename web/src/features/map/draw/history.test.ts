import { describe, expect, it } from 'vitest';
import { commit, redo, startHistory, undo } from './history';

describe('history', () => {
  it('goes back and forth through what was committed', () => {
    let h = startHistory('a');
    h = commit(commit(h, 'b'), 'c');
    expect(h.present).toBe('c');
    h = undo(h);
    expect(h.present).toBe('b');
    h = undo(h);
    expect(h.present).toBe('a');
    h = redo(h);
    expect(h.present).toBe('b');
  });

  it('stays put at either end', () => {
    const h = startHistory('a');
    expect(undo(h)).toBe(h);
    expect(redo(h)).toBe(h);
  });

  it('forgets what was undone when something new is committed', () => {
    let h = commit(startHistory('a'), 'b');
    h = commit(undo(h), 'c');
    expect(h.future).toEqual([]);
    expect(redo(h).present).toBe('c');
  });
});
