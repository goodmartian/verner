import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CALENDAR, META, monthOf } from '../../test/calendarFixtures';
import { COUNTRY_ID } from '../../test/configFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { AreaCalendarBoard } from './AreaCalendarBoard';

const zero = (month: string) =>
  monthOf(month, { count: 0, median: 0, mean: 0, ratio: null, level: null, rank: null, of: null });

describe('an area with no fires at all', () => {
  it('shows dashes and no NaN', async () => {
    const now = zero('2026-11');
    mockApi({
      'POST /api/calendar': () =>
        json(200, {
          ...CALENDAR,
          series: [
            // as the service sends it: nothing against a usual of nothing is the ratio 1, the step «near usual»
            { ...zero('2026-08'), ratio: 1, level: 1 },
            zero('2026-09'),
            zero('2026-10'),
            { ...now, partial: true, complete_through: '2026-11-11' },
          ],
          normals: CALENDAR.normals.map((n) => ({ ...n, median: 0, mean: 0 })),
          yearly: CALENDAR.yearly.map((y) => ({ ...y, count: 0 })),
          current_month: {
            ...now,
            partial: true,
            to_date: {
              through: '2026-11-11',
              count: 0,
              median: 0,
              ratio: null,
              rank: null,
              of: null,
            },
          },
        }),
      'GET /api/meta': () => json(200, META),
      [`GET /api/regions/${COUNTRY_ID}/geometry`]: () => json(200, CALENDAR.area),
    });
    const view = renderApp(<AreaCalendarBoard slotRef={null} onRegion={vi.fn()} />);
    await screen.findByRole('navigation', { name: 'Sections' });
    expect(view.container.textContent).not.toMatch(/NaN|Infinity|undefined/);
    // nothing seen is the palest step, not «near usual», with the ratio 1 of the service or without a ratio
    for (const name of [/August 2026: 0$/, /September 2026: 0$/])
      expect(await screen.findByRole('button', { name })).toHaveAttribute('data-level', '0');
  });
});
