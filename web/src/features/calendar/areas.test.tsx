import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useEffect, useRef } from 'react';
import {
  makeConfig,
  OTHER_COUNTRY_ID,
  THIRD_COUNTRY_ID,
  CONFIG_BBOX,
  COUNTRY_ID,
  REGION_ID,
} from '../../test/configFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { useAreaFlags, useAreaName, useCountryItems } from './areas';
import { useBoard } from '../board/context';
import { CALENDAR } from '../../test/calendarFixtures';

function Catalog() {
  const countries = useCountryItems();
  return (
    <>
      {countries.map((country) => (
        <p key={country.id}>
          {country.id}:{country.provinces?.map((region) => region.id).join(',')}
        </p>
      ))}
    </>
  );
}

describe('country catalog', () => {
  it('does not treat an empty translation as a country alias', async () => {
    const config = makeConfig();
    const countries = config.countries.map((country) => ({
      ...country,
      names: { ...country.names, fr: '' },
    }));
    mockApi({
      'GET /api/regions': () =>
        json(200, {
          regions: [{ id: THIRD_COUNTRY_ID, kind: 'country', names: { en: 'Farland', fr: '' } }],
        }),
    });
    const view = renderApp(<Catalog />, { ...config, countries });
    await screen.findByText(`${THIRD_COUNTRY_ID}:`);
    // the world is the first line, over the countries, with no provinces of its own
    expect(view.container.querySelectorAll('p')).toHaveLength(3);
    expect(view.container.querySelector('p')).toHaveTextContent(/^WORLD:$/);
  });
  it('groups regions by data and deduplicates a country alias without a country-code rule', async () => {
    const config = makeConfig();
    const country = config.countries[0];
    if (!country) throw new Error('The fixture needs a country');
    const other = { ...country, id: OTHER_COUNTRY_ID, names: { en: 'Westland' } };
    const areas = [...config.areas, other];
    mockApi({
      'GET /api/regions': () =>
        json(200, {
          regions: [...areas, { ...country, id: THIRD_COUNTRY_ID }].map((area) => ({
            ...area,
            fires_now: 0,
          })),
        }),
    });
    const view = renderApp(<Catalog />, { ...config, countries: [country, other], areas });
    await screen.findByText(`${OTHER_COUNTRY_ID}:`);
    expect(view.container.querySelectorAll('p')).toHaveLength(3);
    expect(view.container.textContent).not.toContain(THIRD_COUNTRY_ID);
    expect(view.container.textContent).toContain(`${country.id}:${config.areas[1]?.id ?? ''}`);
  });
});

function PolygonMetadata() {
  const board = useBoard();
  const chosen = useRef(false);
  useEffect(() => {
    if (chosen.current) return;
    chosen.current = true;
    board.showDrawn([
      [0, 0],
      [2, 0],
      [2, 2],
      [0, 0],
    ]);
  }, [board]);
  const flags = useAreaFlags();
  return <p>{flags.bbox?.join(',')}</p>;
}

it('takes the frame the calendar returns for an independent polygon', async () => {
  const config = makeConfig();
  mockApi({
    'POST /api/calendar': () =>
      json(200, { ...CALENDAR, area: { ...CALENDAR.area, bbox: CONFIG_BBOX } }),
  });
  renderApp(<PolygonMetadata />, config);
  expect(await screen.findByText(CONFIG_BBOX.join(','))).toBeInTheDocument();
});

function SavedName({ id }: { id: string }) {
  const board = useBoard();
  const chosen = useRef(false);
  useEffect(() => {
    if (chosen.current) return;
    chosen.current = true;
    board.setArea(id);
  }, [board, id]);
  return <p>{useAreaName() ?? 'no name'}</p>;
}

it('names a saved province from the regions of its own country, not from the whole catalog', async () => {
  const calls = mockApi({
    'GET /api/regions': (request) => {
      const country = new URL(request.url).searchParams.get('country');
      return json(200, {
        regions: country
          ? [{ id: REGION_ID, kind: 'province', names: { en: 'Valley' }, fires_now: 0 }]
          : [],
        types: {},
        attribution: null,
      });
    },
  });
  renderApp(<SavedName id={REGION_ID} />, { ...makeConfig(), areas: [] });
  expect(await screen.findByText('Valley')).toBeInTheDocument();
  const asked = calls
    .filter((call) => call.path === '/api/regions')
    .map((call) => call.query.country);
  // the start asks for the countries; the province's country is asked for by itself
  expect(asked).toContain(COUNTRY_ID);
  expect(asked).toContain(undefined);
});
