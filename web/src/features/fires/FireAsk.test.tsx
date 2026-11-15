import { ACCESS_ROUTE } from '../../test/fireFixtures';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { FIRE, FIRE_DETAIL, FIRE_LIST } from '../../test/fireFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { FIRE_WEATHER, WEATHER_LEGEND } from '../../test/weatherFixtures';
import { WidgetActionsContext, type WidgetActions } from '../chat/actions';
import { useFiresState } from './context';
import { FiresList, FireView } from './FiresSide';

const name = (text: string) => ({ en: text, ru: text, es: text, fr: text });
const LAND_COVER = {
  bbox: Array.from({ length: 4 }, (_, index) => index),
  width: 2,
  height: 1,
  data: '13',
  classes: [
    { id: 1, name: name('Forest'), color: '#2e7d32' },
    { id: 3, name: name('Grass'), color: '#a8c256' },
  ],
  shares: [
    { id: 1, share_pct: 61.5 },
    { id: 3, share_pct: 38.1 },
  ],
  attribution: 'Land cover: ESA WorldCover 2021.',
};

const routes = {
  'GET /api/fires': () => json(200, FIRE_LIST),
  [`GET /api/fires/${FIRE.id}`]: () => json(200, FIRE_DETAIL),
  [`GET /api/fires/${FIRE.id}/land-cover`]: () => json(200, LAND_COVER),
  [`GET /api/fires/${FIRE.id}/access-route`]: () => json(200, ACCESS_ROUTE),
  'GET /api/weather/legend': () => json(200, WEATHER_LEGEND),
  'GET /api/weather/fires': () => json(200, FIRE_WEATHER),
};

function Side() {
  const { fireId } = useFiresState();
  return fireId ? (
    <FireView onPlan={vi.fn()} />
  ) : (
    <FiresList onRegion={vi.fn()} onCalendar={vi.fn()} />
  );
}

function setup(ui: ReactNode = <Side />) {
  const addFact = vi.fn();
  mockApi(routes);
  renderApp(
    <WidgetActionsContext value={{ addFact } as unknown as WidgetActions}>
      {ui}
    </WidgetActionsContext>,
  );
  return addFact;
}

/** Presses a figure: the pill with «Ask SI» comes beside it, and a press on the pill asks. */
async function askAbout(figure: HTMLElement) {
  await userEvent.click(figure);
  await userEvent.click(await screen.findByRole('button', { name: 'Ask SI' }));
}

describe('the figures of a fire ask the assistant', () => {
  it('the area tile gives its number and the fire to the question', async () => {
    const addFact = setup();
    await userEvent.click(await screen.findByRole('button', { name: /Santo Tomé/ }));
    await askAbout(await screen.findByRole('button', { name: /Area, estimate/ }));
    expect(addFact).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'Area, estimate', value: '≈ 252 ha', area: 'Santo Tomé' }),
    );
  });

  it('the hotspots tile says how many', async () => {
    const addFact = setup();
    await userEvent.click(await screen.findByRole('button', { name: /Santo Tomé/ }));
    await askAbout(await screen.findByRole('button', { name: /Detections/ }));
    expect(addFact).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'Detections', value: '35' }),
    );
  });

  it('a bar of the growth gives the pass and its hotspots', async () => {
    const addFact = setup();
    await userEvent.click(await screen.findByRole('button', { name: /Santo Tomé/ }));
    await screen.findByRole('heading', { name: 'Growth by pass' });
    const bars = screen.getAllByRole('button', { name: /\d+ detections?$/ });
    await askAbout(bars.slice(-1)[0] ?? document.body);
    expect(addFact).toHaveBeenCalledWith(
      expect.objectContaining({ label: expect.stringContaining('Growth by pass') as string }),
    );
  });

  it('says what the fire burns on, and a press on the line asks about it', async () => {
    const addFact = setup();
    await userEvent.click(await screen.findByRole('button', { name: /Santo Tomé/ }));
    await askAbout(await screen.findByRole('button', { name: /Burns on/ }));
    expect(addFact).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'Burns on', value: 'Forest 62\u00a0%, grass 38\u00a0%' }),
    );
  });

  it('says the way in, from a place and not a station, and a press on the line asks about it', async () => {
    const addFact = setup();
    await userEvent.click(await screen.findByRole('button', { name: /Santo Tomé/ }));
    await askAbout(await screen.findByRole('button', { name: /Access/ }));
    expect(addFact).toHaveBeenCalledWith(
      expect.objectContaining({
        label: 'Access',
        value: '77 min by road, 31 km from Villa Ocampo, on foot 4.4 km',
      }),
    );
  });

  it('the line of the first detection gives its time', async () => {
    const addFact = setup();
    await userEvent.click(await screen.findByRole('button', { name: /Santo Tomé/ }));
    await askAbout(await screen.findByRole('button', { name: /First detected/ }));
    expect(addFact).toHaveBeenCalledWith(expect.objectContaining({ label: 'First detected' }));
  });

  it('the little chart of a row of the list gives the fire, without opening it', async () => {
    const addFact = setup();
    await screen.findByRole('button', { name: /Santo Tomé/ });
    await userEvent.click(document.querySelector<HTMLElement>('#fires .spark') ?? document.body);
    const pill = await screen.findByRole('button', { name: 'Ask SI' });
    expect(screen.queryByRole('heading', { name: 'Growth by pass' })).not.toBeInTheDocument();
    await userEvent.click(pill);
    expect(addFact).toHaveBeenCalledWith(expect.objectContaining({ label: 'Santo Tomé' }));
  });
});
