import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CALENDAR } from '../../test/calendarFixtures';
import { COUNTRY_ID } from '../../test/configFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { MAP_BUSY_AFTER_MS, useCalendarMapBusy } from './useCalendarMap';

const CELLS = { type: 'FeatureCollection', kind: 'cells', features: [] };
const pause = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

/** Writes down every state of the sign, so a blink is caught too. */
const seen: boolean[] = [];
function Busy() {
  const busy = useCalendarMapBusy(true);
  seen.push(busy);
  return <p>{busy ? 'busy' : 'idle'}</p>;
}

function serve(cellsAfterMs: number) {
  const calls = mockApi({
    'POST /api/calendar': () => json(200, CALENDAR),
    [`GET /api/regions/${COUNTRY_ID}/geometry`]: () =>
      json(200, { ...CALENDAR.area, id: COUNTRY_ID }),
    'GET /api/calendar/map': async () => {
      await pause(cellsAfterMs);
      return json(200, CELLS);
    },
  });
  return calls;
}

describe('the sign that the map is still loading', () => {
  afterEach(() => {
    seen.length = 0;
    vi.unstubAllGlobals();
  });

  it('shows while the points of the month take longer than a blink, and goes when they come', async () => {
    const calls = serve(MAP_BUSY_AFTER_MS + 400);
    renderApp(<Busy />);
    expect(await screen.findByText('busy', {}, { timeout: 2000 })).toBeInTheDocument();
    await waitFor(
      () => {
        expect(screen.getByText('idle')).toBeInTheDocument();
      },
      { timeout: 2000 },
    );
    expect(calls.some((call) => call.path === '/api/calendar/map')).toBe(true);
  });

  it('never shows for a quick answer', async () => {
    const calls = serve(0);
    renderApp(<Busy />);
    await waitFor(() => {
      expect(calls.some((call) => call.path === '/api/calendar/map')).toBe(true);
    });
    await pause(MAP_BUSY_AFTER_MS + 200);
    expect(seen.includes(true)).toBe(false);
  });
});
