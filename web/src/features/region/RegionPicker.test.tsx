import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CALENDAR } from '../../test/calendarFixtures';
import { COUNTRY_ID, REGION_ID } from '../../test/configFixtures';
import { apiError, json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { RegionPicker } from './RegionPicker';

const region = {
  ...CALENDAR.area,
  id: REGION_ID,
  kind: 'region',
  country_id: COUNTRY_ID,
  names: { en: 'Valley', ru: 'Долина' },
  type: 'district',
  fires_now: 0,
};
const types = {
  district: { en: { one: 'district', other: 'districts' }, ru: { one: 'район', other: 'районы' } },
};
describe('region search integration', () => {
  it('searches on the server in the UI language and loads geometry before picking', async () => {
    localStorage.setItem('senda-lang', 'ru');
    const pick = vi.fn();
    const close = vi.fn();
    const calls = mockApi({
      'GET /api/regions': (request) =>
        json(200, {
          regions: new URL(request.url).searchParams.get('q') ? [region] : [],
          types,
          attribution: null,
        }),
      [`GET /api/regions/${REGION_ID}/geometry`]: () => json(200, region),
    });
    const land = { id: COUNTRY_ID, kind: 'country', names: { en: 'Land', ru: 'Земля' } };
    renderApp(<RegionPicker open onClose={close} countries={[land]} value={null} onPick={pick} />);
    // the dialog is a separate chunk: it appears once it has loaded
    await userEvent.type(await screen.findByRole('searchbox', {}, { timeout: 5000 }), 'дол');
    const option = await screen.findByRole('option', { name: /Долина/ });
    // the country is named under the region: same-named regions of two countries differ
    expect(option).toHaveTextContent('район · Земля');
    expect(
      calls.some(
        (call) =>
          call.path === '/api/regions' && call.query.q === 'дол' && call.query.lang === 'ru',
      ),
    ).toBe(true);
    await userEvent.click(option);
    await waitFor(() => {
      expect(pick).toHaveBeenCalledWith(REGION_ID);
    });
    expect(calls.some((call) => call.path === `/api/regions/${REGION_ID}/geometry`)).toBe(true);
    expect(close).toHaveBeenCalled();
  });
  it('has the whole world as the first line on both tabs', async () => {
    mockApi({
      'GET /api/regions': () => json(200, { regions: [region], types, attribution: null }),
    });
    for (const showFires of [false, true]) {
      const pick = vi.fn();
      const land = { id: COUNTRY_ID, kind: 'country', names: { en: 'Land' } };
      const view = renderApp(
        <RegionPicker
          open
          onClose={vi.fn()}
          countries={[land]}
          value={null}
          onPick={pick}
          showFires={showFires}
        />,
      );
      const world = await screen.findByRole('option', { name: /World/ }, { timeout: 5000 });
      expect(screen.getAllByRole('option')[0]).toBe(world);
      await userEvent.click(world);
      await waitFor(() => {
        expect(pick).toHaveBeenCalledWith('WORLD');
      });
      view.unmount();
    }
  });
  it('keeps the dialog open when geometry cannot be loaded', async () => {
    const pick = vi.fn();
    const close = vi.fn();
    mockApi({
      'GET /api/regions': () => json(200, { regions: [region], types, attribution: null }),
      [`GET /api/regions/${REGION_ID}/geometry`]: () => apiError(404, 'not_found'),
    });
    renderApp(<RegionPicker open onClose={close} countries={[]} value={null} onPick={pick} />);
    await userEvent.click(await screen.findByRole('option', { name: /Valley/ }));
    expect(await screen.findByRole('status')).toHaveTextContent('Not found');
    expect(pick).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
  });
});
