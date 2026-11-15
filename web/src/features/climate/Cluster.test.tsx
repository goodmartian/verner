import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, useRef } from 'react';
import { describe, expect, it } from 'vitest';
import { DAY_FIRES } from '../../test/climateFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { useBoard } from '../board/context';
import { ClusterStrip } from './ClusterStrip';

/** The cluster of the day open on the board, with its strip. */
function Open() {
  const board = useBoard();
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    board.setPick('2025-10');
    board.setDay('2025-10-17');
    board.setCluster('20251017-1');
  }, [board]);
  return <ClusterStrip />;
}

describe('the card of a cluster of fires', () => {
  it('shows where it is and the first detection', async () => {
    mockApi({ 'GET /api/calendar/fires': () => json(200, DAY_FIRES) });
    renderApp(<Open />);
    expect(await screen.findByText('Santa Fe')).toBeInTheDocument();
    expect(screen.getByText('fires of 17 Oct')).toBeInTheDocument();
    // the satellite saw it at 04:10 UTC: 22:10 the previous day in the fixture place
    expect(screen.getByText('16 Oct, 22:10 GMT-6')).toBeInTheDocument();
  });

  it('closes on its cross', async () => {
    mockApi({ 'GET /api/calendar/fires': () => json(200, DAY_FIRES) });
    renderApp(<Open />);
    await screen.findByText('Santa Fe');
    await userEvent.click(screen.getByRole('button', { name: 'All fires' }));
    expect(screen.queryByText('Santa Fe')).not.toBeInTheDocument();
  });
});
