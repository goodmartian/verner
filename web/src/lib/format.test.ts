import { describe, expect, it } from 'vitest';
import { formatDay } from './format';

describe('formatDay', () => {
  it('writes a day the way each language does', () => {
    expect(formatDay('en', '2026-10-30')).toBe('30 Oct');
    expect(formatDay('es', '2026-10-30')).toContain('30');
    expect(formatDay('ru', '2026-10-30')).toBe('30 окт.');
  });

  it('does not move the day with the time zone', () => {
    expect(formatDay('en', '2026-01-01')).toBe('1 Jan');
  });
});
