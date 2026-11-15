import { COUNTRY_ID, makeConfig } from '../../test/configFixtures';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EMPTY_FIRE_LIST, FIRE, FIRE_DETAIL, FIRE_LIST, OTHER_FIRE } from '../../test/fireFixtures';
import { REGIONS } from '../../test/calendarFixtures';
import { apiError, json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { FIRE_WEATHER, WEATHER_LEGEND } from '../../test/weatherFixtures';
import { useFiresState } from './context';
import { FiresList, FireView } from './FiresSide';

afterEach(() => {
  vi.unstubAllGlobals();
});

const visitor = {
  'GET /api/fires': () => json(200, FIRE_LIST),
  [`GET /api/fires/${FIRE.id}`]: () => json(200, FIRE_DETAIL),
};

/** The side column as the shell draws it: the list, or the open fire. */
function Side() {
  const { fireId } = useFiresState();
  return fireId ? (
    <FireView onPlan={vi.fn()} />
  ) : (
    <FiresList onRegion={vi.fn()} onCalendar={vi.fn()} />
  );
}

describe('the list of fires', () => {
  it('lists the fires of the last days with the period and when the data came', async () => {
    mockApi(visitor);
    renderApp(<Side />);
    expect(await screen.findByRole('button', { name: /Santo Tomé/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Villa General Savio/ })).toBeInTheDocument();
    expect(screen.getByText(/27 to 29 October 2026/)).toBeInTheDocument();
    expect(screen.getByText(/Updated 08:57 GMT-6/)).toBeInTheDocument();
  });

  it('counts the rows of the list, the fires without hotspots at the pass too', async () => {
    const quiet = {
      ...OTHER_FIRE,
      id: 'quiet-1',
      growth: FIRE.growth.map((point) => ({ ...point, detections: 0 })),
    };
    mockApi({
      'GET /api/fires': () => json(200, { ...FIRE_LIST, fires: [FIRE, OTHER_FIRE, quiet] }),
    });
    renderApp(<Side />);
    await screen.findByRole('button', { name: /Santo Tomé/ });
    expect(document.querySelectorAll('#fires > li')).toHaveLength(3);
    expect(document.querySelector('#count')).toHaveTextContent('3');
  });

  it('asks for the fires of the region on the board', async () => {
    const calls = mockApi({ ...visitor, 'GET /api/regions': () => json(200, REGIONS) });
    renderApp(<Side />);
    await screen.findByRole('button', { name: /Santo Tomé/ });
    expect(calls.find((call) => call.path === '/api/fires')?.query.region).toBe(COUNTRY_ID);
    expect(await screen.findByRole('button', { name: /Northland/ })).toBeInTheDocument();
  });

  it('keeps a bar in the place of the region until its name has come, never the code', async () => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    mockApi({
      ...visitor,
      'GET /api/regions': async () => {
        await held;
        return json(200, REGIONS);
      },
    });
    const config = makeConfig();
    renderApp(<Side />, { ...config, areas: config.areas.map((area) => ({ ...area, names: {} })) });
    await screen.findByRole('button', { name: /Santo Tomé/ });
    expect(screen.queryByText(COUNTRY_ID)).not.toBeInTheDocument();
    expect(document.querySelector('#region-name .skel')).not.toBeNull();
    release();
    expect(await screen.findByRole('button', { name: /Argentina/ })).toBeInTheDocument();
    expect(document.querySelector('.skel')).toBeNull();
  });

  it('is honest when there are none, and offers the example', async () => {
    const calls = mockApi({
      ...visitor,
      'GET /api/fires': (request) =>
        json(
          200,
          new URL(request.url).searchParams.get('demo') === 'true' ? FIRE_LIST : EMPTY_FIRE_LIST,
        ),
    });
    renderApp(<Side />);
    expect(await screen.findByText('No fires in the last 3 days.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Show an example' }));
    expect(await screen.findByRole('button', { name: /Santo Tomé/ })).toBeInTheDocument();
    expect(calls.some((call) => call.query.demo === 'true')).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: 'Back to live fires' }));
    expect(await screen.findByText('No fires in the last 3 days.')).toBeInTheDocument();
  });

  it('leads a quiet region to the one burning most now, and to its own statistics', async () => {
    // the province of the fixture: one fire now, and not the area on the board
    const province = REGIONS.regions.find((item) => item.kind === 'province')?.id;
    const calls = mockApi({
      ...visitor,
      'GET /api/regions': () => json(200, REGIONS),
      'GET /api/fires': (request) =>
        json(
          200,
          new URL(request.url).searchParams.get('region') === province
            ? FIRE_LIST
            : EMPTY_FIRE_LIST,
        ),
    });
    const onCalendar = vi.fn();
    renderApp(<FiresList onRegion={vi.fn()} onCalendar={onCalendar} />);
    expect(await screen.findByText('No fires in the last 3 days.')).toBeInTheDocument();
    // the region on the board is left out: the other one has a fire now
    const burning = await screen.findByRole('button', { name: 'Corrientes, fires: 1' });
    expect(screen.queryByRole('button', { name: 'Show an example' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Open statistics' }));
    expect(onCalendar).toHaveBeenCalledOnce();
    await userEvent.click(burning);
    expect(await screen.findByRole('button', { name: /Santo Tomé/ })).toBeInTheDocument();
    expect(
      calls.some((call) => call.path === '/api/fires' && call.query.region === province),
    ).toBe(true);
  });

  it('says the service is down when the list is not available', async () => {
    mockApi({
      ...visitor,
      'GET /api/fires': () => json(200, { ...EMPTY_FIRE_LIST, available: false }),
    });
    renderApp(<Side />);
    expect(await screen.findByText('Live fires are not loaded yet.')).toBeInTheDocument();
    // nothing live to lead to: the example and the statistics
    expect(screen.getByRole('button', { name: 'Show an example' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open statistics' })).toBeInTheDocument();
  });

  it('shows the error when the list cannot be loaded', async () => {
    mockApi({ ...visitor, 'GET /api/fires': () => apiError(500, 'boom') });
    renderApp(<Side />);
    expect(await screen.findByText('Something went wrong.')).toBeInTheDocument();
  });
});

describe('a fire', () => {
  // the card shows the hour of now: the fixture's weather is of those days
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-10-28T12:30:00Z') });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const open = async () => {
    await userEvent.click(await screen.findByRole('button', { name: /Santo Tomé/ }));
    await screen.findByRole('heading', { name: 'Santo Tomé' });
  };
  const weatherApi = {
    ...visitor,
    'GET /api/weather/legend': () => json(200, WEATHER_LEGEND),
    'GET /api/weather/fires': () => json(200, FIRE_WEATHER),
  };

  it('opens with its numbers and the weather, and goes back', async () => {
    mockApi(visitor);
    renderApp(<Side />);
    await open();
    expect(screen.getByText('≈ 252 ha')).toBeInTheDocument();
    expect(screen.getByText('652 MW')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Conditions' })).toBeInTheDocument();
    // the wind is a whole number on one line, the side it blows from is the caption
    expect(screen.getByText('10 km/h')).toBeInTheDocument();
    expect(screen.getByText('from the south')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'All fires' }));
    expect(await screen.findByRole('button', { name: /Villa General Savio/ })).toBeInTheDocument();
  });

  it('adds the gusts, the rain and the dryness of the weather layers', async () => {
    mockApi(weatherApi);
    renderApp(<Side />);
    await open();
    expect(await screen.findByText('22 km/h')).toBeInTheDocument();
    expect(screen.getByText('Gusts')).toBeInTheDocument();
    expect(screen.getByText('0 mm/h')).toBeInTheDocument();
    // the class of the dryness by its name, the hot-dry-windy number as the caption
    expect(screen.getByText('Dry')).toBeInTheDocument();
    expect(screen.getByText('Dryness, HDW 31')).toBeInTheDocument();
    expect(screen.getByText('24 °C, 41%')).toBeInTheDocument();
  });

  it('says there is no data for what the example does not have', async () => {
    mockApi({
      ...weatherApi,
      // the weather of the layers is of the live fires only
      'GET /api/weather/fires': () => json(200, { ...FIRE_WEATHER, fires: [] }),
      [`GET /api/fires/${FIRE.id}`]: () => json(200, { ...FIRE_DETAIL, source: 'demo' }),
    });
    renderApp(<Side />);
    await open();
    expect(await screen.findAllByText('No data')).toHaveLength(3);
    expect(screen.getByText('10 km/h')).toBeInTheDocument();
  });

  it('says where the weather comes from when it is the grid', async () => {
    mockApi({
      ...visitor,
      [`GET /api/fires/${FIRE.id}`]: () =>
        json(200, {
          ...FIRE_DETAIL,
          weather: FIRE_DETAIL.weather && { ...FIRE_DETAIL.weather, source: 'grid' },
        }),
    });
    renderApp(<Side />);
    await open();
    expect(await screen.findByText('from the GFS grid')).toBeInTheDocument();
  });
});
