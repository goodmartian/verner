import { COUNTRY_ID, REGION_ID, OTHER_COUNTRY_ID } from '../../test/configFixtures';
import { describe, expect, it } from 'vitest';
import { keepTarget, parseTarget } from './links';

describe('parseTarget', () => {
  it('knows a fire by its id', () => {
    expect(parseTarget('fire:20261030-1')).toEqual({ kind: 'fire', id: '20261030-1' });
    expect(parseTarget('fire:f12')).toEqual({ kind: 'fire', id: 'f12' });
  });

  it('knows a month and a run of months', () => {
    expect(parseTarget('period:2025-10')).toEqual({
      kind: 'period',
      from: '2025-10',
      to: '2025-10',
    });
    expect(parseTarget('period:2025-10..2026-03')).toEqual({
      kind: 'period',
      from: '2025-10',
      to: '2026-03',
    });
  });

  it('refuses a period that runs backwards, or has a month that is not one', () => {
    expect(parseTarget('period:2026-03..2025-10')).toBeNull();
    expect(parseTarget('period:2025-13')).toBeNull();
    expect(parseTarget('period:2025-00')).toBeNull();
    expect(parseTarget('period:2025-10..')).toBeNull();
    expect(parseTarget('period:25-10')).toBeNull();
  });

  it('knows an area by its code or the name of a drawn one', () => {
    expect(parseTarget(`area:${COUNTRY_ID}`)).toEqual({ kind: 'area', id: COUNTRY_ID });
    expect(parseTarget(`area:${REGION_ID}`)).toEqual({ kind: 'area', id: REGION_ID });
    expect(parseTarget(`area:${OTHER_COUNTRY_ID}`)).toEqual({ kind: 'area', id: OTHER_COUNTRY_ID });
    expect(parseTarget('area:U1')).toEqual({ kind: 'area', id: 'U1' });
  });

  it('knows a drawing of the assistant by its name, and no other', () => {
    expect(parseTarget('shape:A3')).toEqual({ kind: 'shape', id: 'A3' });
    expect(parseTarget('shape:U1')).toBeNull();
    expect(parseTarget('shape:')).toBeNull();
  });

  it('knows web addresses, http and https only', () => {
    expect(parseTarget('https://example.com/a?b=1')).toEqual({
      kind: 'web',
      url: 'https://example.com/a?b=1',
    });
    expect(parseTarget('http://example.com')).toEqual({ kind: 'web', url: 'http://example.com' });
  });

  it.each([
    'javascript:alert(1)',
    'data:text/html,<b>x</b>',
    'mailto:a@b.c',
    'tel:+5491100000000',
    'file:///etc/passwd',
    'vbscript:x',
    'FIRE:123',
    'fire:',
    'fire:a b',
    'fire:<script>',
    'area:',
    'area:AR/../x',
    'ftp://example.com',
    '/relative/path',
    '#anchor',
    '',
  ])('refuses %s', (url) => {
    expect(parseTarget(url)).toBeNull();
    expect(keepTarget(url)).toBe('');
  });
});

describe('keepTarget', () => {
  it('keeps what it knows as it is', () => {
    expect(keepTarget('fire:20261030-1')).toBe('fire:20261030-1');
    expect(keepTarget('https://example.com')).toBe('https://example.com');
  });
});
