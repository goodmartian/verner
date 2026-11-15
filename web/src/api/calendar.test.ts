import { describe, expect, it } from 'vitest';
import { CALENDAR, META, POLYGON } from '../test/calendarFixtures';
import { COUNTRY_ID } from '../test/configFixtures';
import { apiError, json, mockApi } from '../test/mockApi';
import { calendar, exportMonths, exportTicket, meta } from './calendar';

const area = { id: COUNTRY_ID };
const range = { from: '2025-01', to: '2025-02' };

describe('area calendar transport', () => {
  it('sends every selector intact, including multipolygons, and the period only when there is one', async () => {
    const calls = mockApi({ 'POST /api/calendar': () => json(200, CALENDAR) });
    const polygon = { polygon: POLYGON };
    for (const ref of [area, polygon]) {
      await calendar(ref, range);
      expect(calls.at(-1)?.body).toEqual({ area: ref, ...range });
    }
    // The fixture has a Polygon; preserve its coordinate nesting in a MultiPolygon.
    const multi = {
      polygon: {
        type: 'MultiPolygon' as const,
        coordinates: [POLYGON.coordinates],
      },
    };
    await calendar(multi, null);
    expect(calls.at(-1)?.body).toEqual({ area: multi });
  });
  it('keeps unavailable grids as errors', async () => {
    mockApi({ 'POST /api/calendar': () => apiError(503, 'grid_unavailable') });
    await expect(calendar(area, null)).rejects.toMatchObject({ code: 'grid_unavailable' });
  });
  it('reads the meta of the archive', async () => {
    mockApi({ 'GET /api/meta': () => json(200, META) });
    expect(await meta()).toEqual(META);
  });
});

describe('CSV export transport', () => {
  it('reads the table of months as CSV, not JSON, and names it when the server did not', async () => {
    const calls = mockApi({
      'POST /api/export/months': () =>
        new Response('month,count\n2025-01,3\n', { headers: { 'Content-Type': 'text/csv' } }),
    });
    const file = await exportMonths(area, range);
    expect(await file.blob.text()).toBe('month,count\n2025-01,3\n');
    expect(file.name).toBe('verner.csv');
    expect(calls[0]?.body).toEqual({ area, ...range });
  });
  it('asks the table of months from its own route and keeps the name the server gave', async () => {
    const calls = mockApi({
      'POST /api/export/months': () =>
        new Response('month,count\n2025-01,3\n', {
          headers: {
            'Content-Type': 'text/csv',
            'Content-Disposition': 'attachment; filename="verner_ar_2025-01_2025-02_months.csv"',
          },
        }),
    });
    const file = await exportMonths(area, range);
    expect(await file.blob.text()).toBe('month,count\n2025-01,3\n');
    expect(file.name).toBe('verner_ar_2025-01_2025-02_months.csv');
    expect(calls[0]?.path).toBe('/api/export/months');
    expect(calls[0]?.body).toEqual({ area, ...range });
  });
  it('asks a ticket for every detection and gives its address, name and rows', async () => {
    const ticket = { url: '/api/export/file/abc', rows: 3_100_000, name: 'verner_ar.csv' };
    const calls = mockApi({ 'POST /api/export/ticket': () => json(200, ticket) });
    expect(await exportTicket(area, range)).toEqual(ticket);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.body).toEqual({ area, ...range });
  });
  it('keeps a refusal of the ticket with its code and wait', async () => {
    mockApi({
      'POST /api/export/ticket': () =>
        new Response(JSON.stringify({ error: { code: 'export_quota', message: 'x' } }), {
          status: 429,
          headers: { 'Content-Type': 'application/json', 'Retry-After': '240' },
        }),
    });
    await expect(exportTicket(area, range)).rejects.toMatchObject({
      status: 429,
      code: 'export_quota',
      retryAfter: 240,
    });
  });
});
