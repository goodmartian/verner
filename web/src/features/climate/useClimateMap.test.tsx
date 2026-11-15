import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { CALENDAR } from '../../test/calendarFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { usePicked } from '../calendar/queries';
import { useClimateMap } from './useClimateMap';

const legend = (last: string) => ({
  available: true,
  first_month: '2003-01',
  last_month: last,
  month_layers: [],
  attribution: null,
});

/** What the menu of layers is given: whether the month has weather, and the way to the last one that has. */
function Probe() {
  const climate = useClimateMap(null, true);
  const month = usePicked();
  return (
    <>
      <output>{month}</output>
      {climate.empty ? <p>empty</p> : null}
      {climate.latest ? (
        <button type="button" onClick={climate.latest.run}>
          {climate.latest.label}
        </button>
      ) : null}
    </>
  );
}

describe('the weather of the months on the map', () => {
  it('leads a month past its last one back to that month', async () => {
    // the board stands on January 2025, the last month seen; the weather ends a month before
    mockApi({
      'POST /api/calendar': () => json(200, CALENDAR),
      'GET /api/climate/legend': () => json(200, legend('2024-12')),
    });
    renderApp(<Probe />);
    expect(await screen.findByText('empty')).toBeInTheDocument();
    await userEvent.click(await screen.findByRole('button', { name: 'December 2024' }));
    expect(await screen.findByRole('status')).toHaveTextContent('2024-12');
    expect(screen.queryByText('empty')).not.toBeInTheDocument();
  });

  it('offers nothing when the month on the board has its weather', async () => {
    mockApi({
      'POST /api/calendar': () => json(200, CALENDAR),
      'GET /api/climate/legend': () => json(200, legend('2026-12')),
    });
    renderApp(<Probe />);
    await screen.findByText('2025-01');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
