import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { apiError, json, mockApi } from '../test/mockApi';
import {
  makeConfig,
  configResponse,
  COUNTRY_ID,
  INTEGER_ZONE,
  FRACTIONAL_ZONE,
  REGION_ID,
} from '../test/configFixtures';
import { ConfigProvider } from './ConfigProvider';
import { areaFlags, useConfig } from './context';
import { decodeConfig, loadConfig, mergeRegions } from './load';
import { BoardProvider } from '../features/board/BoardProvider';
import { I18nProvider } from '../i18n/I18nProvider';
import { AreaName } from '../features/calendar/AreaName';
import { placeZone } from './usePlaceZone';
import { monthAttachment } from '../api/area';

describe('config', () => {
  it('merges API regions without requiring them to be repeated in config', () => {
    const config = makeConfig();
    const merged = mergeRegions({ ...config, areas: config.countries }, config.areas);
    expect(areaFlags(merged, { id: REGION_ID })).toMatchObject({
      covered: true,
      timezone: FRACTIONAL_ZONE,
    });
    expect(merged.areas).toHaveLength(config.areas.length);
  });
  it('reads /api/config and preserves all supplied coverage, years and locales', async () => {
    const config = makeConfig();
    const calls = mockApi({ 'GET /api/config': () => json(200, configResponse(config)) });
    const result = await loadConfig();
    expect(result).toMatchObject({
      default_area: config.default_area,
      languages: config.languages,
      archive_years: config.archive_years,
    });
    expect(result.countries[0]?.bbox).toEqual(config.countries[0]?.bbox);
    expect(calls.map((call) => call.path)).toEqual(['/api/config']);
    expect(areaFlags(mergeRegions(result, config.areas), { id: REGION_ID }).timezone).toBe(
      FRACTIONAL_ZONE,
    );
  });

  it('has no config when /api/config fails', async () => {
    const calls = mockApi({
      'GET /api/config': () => apiError(404, 'not_found'),
    });
    await expect(loadConfig()).rejects.toMatchObject({ status: 404 });
    expect(calls.map((call) => call.path)).toEqual(['/api/config']);
  });

  it('does not invent absent timezone, default area, languages or archive years', async () => {
    mockApi({});
    await expect(loadConfig()).rejects.toMatchObject({ status: 404 });
    expect(areaFlags(null, null)).toEqual({
      covered: null,
      bbox: null,
      timezone: null,
    });
    const decoded = decodeConfig({
      ...configResponse(),
      covered_countries: [{ id: COUNTRY_ID, names: {}, bbox: [], timezone: 'invalid' }],
    });
    expect(decoded.countries[0]).toMatchObject({ bbox: null, timezone: null });
  });

  it('takes the fire zone before the area zone', () => {
    expect(placeZone({ timezone: FRACTIONAL_ZONE }, INTEGER_ZONE)).toBe(FRACTIONAL_ZONE);
    expect(placeZone({ summary: { timezone: FRACTIONAL_ZONE } }, INTEGER_ZONE)).toBe(
      FRACTIONAL_ZONE,
    );
    expect(placeZone({}, INTEGER_ZONE)).toBe(INTEGER_ZONE);
    expect(placeZone({}, null)).toBeNull();
  });

  it('shows a skeleton while no default place is known', async () => {
    // the config has not answered yet: no error, a pale bar where the name will stand
    const calls = mockApi({ 'GET /api/config': () => new Promise<never>(() => undefined) });
    function Probe() {
      const config = useConfig();
      return (
        <>
          <AreaName />
          <span>{config ? 'loaded' : 'no config'}</span>
        </>
      );
    }
    const view = render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ConfigProvider>
          <I18nProvider>
            <BoardProvider>
              <Probe />
            </BoardProvider>
          </I18nProvider>
        </ConfigProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => {
      expect(calls.some((call) => call.path === '/api/config')).toBe(true);
    });
    expect(screen.getByText('no config')).toBeInTheDocument();
    expect(view.container.querySelector('.skel')).not.toBeNull();
  });

  it('says the server does not answer when the config cannot be had, and asks again', async () => {
    const calls = mockApi({});
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ConfigProvider>
          <span>app</span>
        </ConfigProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('No answer from the server');
    expect(screen.queryByText('app')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => {
      expect(calls.filter((call) => call.path === '/api/config').length).toBeGreaterThan(1);
    });
  });

  it('refuses a polygon where a catalog area is needed', () => {
    const ref = {
      polygon: {
        type: 'Polygon' as const,
        coordinates: [
          [
            [0, 0],
            [2, 0],
            [2, 2],
            [0, 0],
          ],
        ],
      },
    };
    expect(() =>
      monthAttachment({ kind: 'month', month: '2024-01', area: ref, label: '' }),
    ).toThrow('catalog area');
  });
});
