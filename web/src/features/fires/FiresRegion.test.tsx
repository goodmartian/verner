import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { REGION_ID } from '../../test/configFixtures';
import { EMPTY_FIRE_LIST, FIRE, FIRE_DETAIL, FIRE_LIST } from '../../test/fireFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { useBoard } from '../board/context';
import { useFiresState } from './context';
import { FiresList } from './FiresSide';

function Probe() {
  const { setArea } = useBoard();
  const { fireId, select, setPlayer, player } = useFiresState();
  return (
    <>
      <output aria-label="fire">{fireId ?? 'none'}</output>
      <output aria-label="player">{String(player)}</output>
      <button
        type="button"
        onClick={() => {
          select(FIRE.id);
          setPlayer(true);
        }}
      >
        open
      </button>
      <button
        type="button"
        onClick={() => {
          setArea(REGION_ID);
        }}
      >
        region
      </button>
      <FiresList onRegion={vi.fn()} onCalendar={vi.fn()} />
    </>
  );
}

describe('another region', () => {
  it('lets go of the open fire and the player of the old one', async () => {
    mockApi({
      'GET /api/fires': () => json(200, FIRE_LIST),
      [`GET /api/fires/${FIRE.id}`]: () => json(200, FIRE_DETAIL),
    });
    renderApp(<Probe />);
    await userEvent.click(screen.getByRole('button', { name: 'open' }));
    expect(screen.getByLabelText('fire')).toHaveTextContent(FIRE.id);
    await userEvent.click(screen.getByRole('button', { name: 'region' }));
    expect(screen.getByLabelText('fire')).toHaveTextContent('none');
    expect(screen.getByLabelText('player')).toHaveTextContent('false');
  });

  it('says there are no fires when the list of a region is empty, not waiting for ever', async () => {
    mockApi({ 'GET /api/fires': () => json(200, EMPTY_FIRE_LIST) });
    renderApp(<Probe />);
    await userEvent.click(screen.getByRole('button', { name: 'region' }));
    expect(await screen.findByText('No active fires in this region.')).toBeInTheDocument();
    expect(document.querySelector('.skel')).toBeNull();
  });
});
