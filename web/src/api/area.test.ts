import { afterEach, describe, expect, it, vi } from 'vitest';
import { json, mockApi } from '../test/mockApi';
import { areaRequests, supportsArea } from './area';
import type { AreaRef } from '../config/types';
import { COUNTRY_ID } from '../test/configFixtures';

const POLYGON = {
  type: 'Polygon' as const,
  coordinates: [
    [
      [-65, -25],
      [-60, -25],
      [-60, -22],
      [-65, -22],
      [-65, -25],
    ],
  ],
};
const DRAWN: AreaRef = { polygon: POLYGON };
const COUNTRY: AreaRef = { id: COUNTRY_ID };

describe('the requests of an area', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each(['map', 'days', 'month'] as const)(
    'asks %s of a drawn area by POST with its outline, of a catalog area by GET',
    async (name) => {
      const path = `/api/calendar/${name}`;
      const calls = mockApi({ [`POST ${path}`]: () => json(200, {}), [`GET ${path}`]: () => json(200, {}) });
      await areaRequests[name](DRAWN, '2024-09');
      await areaRequests[name](COUNTRY, '2024-09');
      expect(calls).toEqual([
        { method: 'POST', path, query: {}, body: { area: { polygon: POLYGON }, month: '2024-09' } },
        { method: 'GET', path, query: { area: COUNTRY_ID, month: '2024-09' }, body: undefined },
      ]);
    },
  );

  it('lets a drawn area ask only what the server answers for it', () => {
    for (const name of ['map', 'days', 'month'] as const) expect(supportsArea(DRAWN, name)).toBe(true);
    for (const name of ['fires', 'firesOfDay'] as const) expect(supportsArea(DRAWN, name)).toBe(false);
    expect(supportsArea(COUNTRY, 'fires')).toBe(true);
    expect(supportsArea(null, 'map')).toBe(false);
  });
});
