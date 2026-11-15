import { screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CALENDAR, META } from '../../test/calendarFixtures';
import { COUNTRY_ID, REGION_ID, makeConfig } from '../../test/configFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { WidgetActionsContext, type WidgetActions } from '../chat/actions';
import { AreaCalendarBoard } from './AreaCalendarBoard';

const geometry = { ...CALENDAR.area, id: COUNTRY_ID };
const row = (id: string, name: string, total: number, ratio: number | null) => ({
  id,
  names: { en: name },
  total,
  normal: 329,
  ratio,
  share: 0.1,
  year_normal: 1000,
});

function show(area: string, whole = false) {
  const calls = mockApi({
    'POST /api/calendar': () => json(200, { ...CALENDAR, season: null }),
    'GET /api/meta': () => json(200, META),
    'GET /api/regions': () =>
      json(200, { regions: [{ id: COUNTRY_ID, kind: 'country', names: { en: 'Northland' } }] }),
    [`GET /api/regions/${COUNTRY_ID}/geometry`]: () => json(200, geometry),
    'GET /api/calendar/provinces': () =>
      json(200, {
        first_month: '2026-11',
        last_month: '2026-11',
        approximate: false,
        whole,
        sort: 'total',
        total: 1900,
        rows: [
          row(`${COUNTRY_ID}-A`, 'Formosa', 1576, 4.79),
          row(`${COUNTRY_ID}-B`, 'Salta', 324, null),
        ],
        attribution: null,
      }),
  });
  renderApp(
    <WidgetActionsContext
      value={{ addFact: vi.fn(), addMonth: vi.fn() } as unknown as WidgetActions}
    >
      <AreaCalendarBoard slotRef={null} onRegion={vi.fn()} />
    </WidgetActionsContext>,
    makeConfig({ default_area: { id: area } }),
  );
  return calls;
}

describe('the provinces of a country', () => {
  it('asks for the chosen country and its period, and draws the rows with a dash for no norm', async () => {
    const calls = show(COUNTRY_ID);
    expect(await screen.findByText('Formosa')).toBeInTheDocument();
    expect(screen.getByText('Salta')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Against the normal' })).toBeInTheDocument();
    expect(
      within(screen.getByText('Salta').closest('tr') as HTMLElement).getByText('—'),
    ).toBeInTheDocument();
    const asked = calls.find((call) => call.path === '/api/calendar/provinces');
    expect(asked?.query.area).toBe(COUNTRY_ID);
    expect(asked?.query.from).toBeTruthy();
  });
  it('shows the share of the country when the period is the whole archive', async () => {
    show(COUNTRY_ID, true);
    await screen.findByText('Formosa');
    expect(screen.getByRole('button', { name: 'Share' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Against the normal' })).not.toBeInTheDocument();
    expect(
      within(screen.getByText('Formosa').closest('tr') as HTMLElement).getByText('10 %'),
    ).toBeInTheDocument();
  });
  it('is not asked for a region of the country', async () => {
    const calls = show(REGION_ID);
    await screen.findAllByText(/Burning calendar|calendar/i);
    expect(calls.some((call) => call.path === '/api/calendar/provinces')).toBe(false);
    expect(screen.queryByText('Formosa')).not.toBeInTheDocument();
  });
});
