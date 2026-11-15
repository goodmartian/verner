import { screen } from '@testing-library/react';
import { useEffect, useRef } from 'react';
import { describe, expect, it } from 'vitest';
import { FIRE, FIRE_DETAIL, FIRE_LIST } from '../../test/fireFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { useFiresState } from './context';
import { FireStrip } from './FireStrip';

function Opened() {
  const state = useFiresState();
  // `select` is new at every change of the state: asking once is what keeps this from going round
  const asked = useRef(false);
  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    state.select(FIRE.id);
  }, [state]);
  return <FireStrip />;
}

describe('the strip of a fire', () => {
  it('is the name, the place and the cross, at every width: the numbers are in the tiles', async () => {
    mockApi({
      'GET /api/fires': () => json(200, FIRE_LIST),
      [`GET /api/fires/${FIRE.id}`]: () => json(200, FIRE_DETAIL),
    });
    renderApp(<Opened />);
    expect(await screen.findByText(FIRE_DETAIL.summary.nearest_place.name)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'All fires' })).toBeInTheDocument();
    expect(document.querySelectorAll('.fs-cells > span')).toHaveLength(1);
  });
});
