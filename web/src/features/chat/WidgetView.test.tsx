import { CONFIG_BBOX, INTEGER_ZONE } from '../../test/configFixtures';
import { COUNTRY_ID, REGION_ID, OTHER_COUNTRY_ID } from '../../test/configFixtures';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Widget } from '../../api/types';
import { CALENDAR, CHECK, MONTH, POLYGON, SUMMARY } from '../../test/calendarFixtures';
import { FIRE_DETAIL, FIRE_LIST, PLAN } from '../../test/fireFixtures';
import { renderApp } from '../../test/render';
import { WidgetActionsContext, type WidgetActions } from './actions';
import { ApiError } from '../../api/client';
import { WidgetView } from './WidgetView';

const show = (widget: Widget, actions: WidgetActions = noActions()) =>
  renderApp(
    <WidgetActionsContext value={actions}>
      <WidgetView widget={widget} />
    </WidgetActionsContext>,
  );

/** The hands the shell gives a button inside an answer, each one a spy. */
const noActions = () => ({
  openFire: vi.fn(),
  addMonth: vi.fn(),
  addFact: vi.fn(),
  showPeriod: vi.fn(),
  showArea: vi.fn(),
  hoverFire: vi.fn(),
  showShape: vi.fn(),
  showPlan: vi.fn(),
});

const FILE = {
  id: 'f1',
  name: 'verner_monthly.csv',
  mime: 'text/csv',
  size: 2048,
  rows: 12,
  kind: 'monthly',
} as const;

describe('WidgetView', () => {
  it('draws a file as one button that says what the file is and how much is in it, and saves it by a press', async () => {
    const downloadFile = vi.fn().mockResolvedValue(undefined);
    show({ type: 'file', data: FILE }, { ...noActions(), downloadFile });
    const card = screen.getByRole('button', { name: 'Download: Detections by month' });
    expect(card).toHaveAttribute('title', 'verner_monthly.csv');
    expect(card).toHaveTextContent('Detections by month');
    expect(card).toHaveTextContent('CSV · months: 12');
    // no word of the button, no size, no rows
    expect(card).not.toHaveTextContent(/Download|KB|rows/);
    await userEvent.click(card);
    expect(downloadFile).toHaveBeenCalledWith({ id: 'f1', name: 'verner_monthly.csv' });
  });
  it('tells each kind of file in words, with the count it holds', () => {
    const kinds = [
      ['days', 31, 'Detections by day', 'CSV · days: 31'],
      ['fires', 20, 'Active fires', 'CSV · fires: 20'],
      ['report', null, 'Report', 'Markdown'],
    ] as const;
    for (const [kind, rows, title, line] of kinds) {
      show({ type: 'file', data: { ...FILE, id: kind, kind, rows } });
      const card = screen.getByRole('button', { name: `Download: ${title}` });
      expect(card).toHaveTextContent(line);
    }
    // a kind the page does not know falls back to the name of the file, with no count
    show({ type: 'file', data: { ...FILE, id: 'x', name: 'odd.csv', kind: 'odd' as 'days' } });
    expect(screen.getByRole('button', { name: 'Download: odd.csv' })).toHaveTextContent(/csv/i);
  });
  it('keeps the card pressable after a failed save, and shows a file that has gone as quiet text, not a button', async () => {
    const downloadFile = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(500, 'oops', 'failed'))
      .mockRejectedValueOnce(new ApiError(404, 'not_found', 'gone'));
    show({ type: 'file', data: FILE }, { ...noActions(), downloadFile });
    const card = screen.getByRole('button', { name: 'Download: Detections by month' });
    await userEvent.click(card);
    expect(await screen.findByText('The download failed')).toBeInTheDocument();
    expect(card).toBeEnabled();
    await userEvent.click(card);
    expect(await screen.findByText('The file is no longer available')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(downloadFile).toHaveBeenCalledTimes(2);
  });
  it('shows the turning arc while a file is being saved, and a second press waits', async () => {
    let done: () => void = () => undefined;
    const downloadFile = vi.fn().mockReturnValue(new Promise<void>((resolve) => (done = resolve)));
    const { container } = show({ type: 'file', data: FILE }, { ...noActions(), downloadFile });
    const card = screen.getByRole('button', { name: 'Download: Detections by month' });
    await userEvent.click(card);
    expect(card).toBeDisabled();
    expect(container.querySelector('.spin')).not.toBeNull();
    done();
    await vi.waitFor(() => {
      expect(card).toBeEnabled();
    });
    expect(container.querySelector('.spin')).toBeNull();
  });
  it('draws several files as several cards and nothing for a kind it does not know', () => {
    const { container } = show({ type: 'file', data: FILE });
    show({ type: 'file', data: { ...FILE, id: 'f2', name: 'b.csv' } });
    expect(screen.getAllByRole('button', { name: 'Download: Detections by month' })).toHaveLength(2);
    const { container: empty } = show({ type: 'hologram', data: {} } as unknown as Widget);
    expect(empty).toBeEmptyDOMElement();
    expect(container).not.toBeEmptyDOMElement();
  });
  it('draws the calendar of a period the assistant asked for: the figures are of that period, not of the running month', async () => {
    const actions = noActions();
    const month = CALENDAR.series[0];
    if (!month) throw new Error('The fixture has no month');
    const year = Array.from({ length: 12 }, (_, index) => ({
      ...month,
      month: `2025-${String(index + 1).padStart(2, '0')}`,
      count: 100,
      median: 80,
    }));
    const yearly = [
      { year: 2023, count: 500, complete: true, gaps: false, converted: false },
      { year: 2024, count: 2000, complete: true, gaps: false, converted: false },
      { year: 2025, count: 1200, complete: true, gaps: false, converted: false },
      { year: 2026, count: 5000, complete: false, gaps: false, converted: false },
    ];
    show({ type: 'area_calendar', data: { ...CALENDAR, series: year, yearly } }, actions);
    // the year asked for, its count and the usual count of the same months, summed from what the service counted
    expect(screen.getByText('2025')).toBeInTheDocument();
    expect(screen.getByText('1,200').nextElementSibling).toHaveTextContent('Detections');
    expect(screen.getByText('960').nextElementSibling).toHaveTextContent(/^Usual$/);
    expect(screen.getByText('+25 %').nextElementSibling).toHaveTextContent('Against usual');
    // second among the years that are over: the running year is not one of them
    expect(screen.getByText('#2').nextElementSibling).toHaveTextContent('Among other years');
    // nothing of the running month
    expect(screen.queryByText(/October 2026/)).not.toBeInTheDocument();
    expect(screen.queryByText('+50 %')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Show in statistics' }));
    expect(actions.showPeriod).toHaveBeenCalledWith({ polygon: POLYGON }, '2025-01', '2025-12');
  });
  it('sets a whole year against the average year of the service, as the assistant says it in words', () => {
    const month = CALENDAR.series[0];
    if (!month) throw new Error('The fixture has no month');
    const year = Array.from({ length: 12 }, (_, index) => ({
      ...month,
      month: `2025-${String(index + 1).padStart(2, '0')}`,
      count: 100,
      median: 80,
    }));
    const yearly = [{ year: 2025, count: 1300, complete: true, gaps: false, converted: false }];
    const season = { average_year: 1000 } as NonNullable<typeof CALENDAR.season>;
    show({ type: 'area_calendar', data: { ...CALENDAR, series: year, yearly, season } });
    // the total of the year and the average year are the service's own; the sum of the months is not used
    expect(screen.getByText('1,300').nextElementSibling).toHaveTextContent('Detections');
    expect(screen.getByText('1,000').nextElementSibling).toHaveTextContent('A usual year');
    expect(screen.getByText('+30 %').nextElementSibling).toHaveTextContent('Against usual');
    // the answer holds this one year only: there is nothing to give it a place among
    expect(screen.queryByText('Among other years')).not.toBeInTheDocument();
  });
  it('draws the whole record as the running month against the same dates, and the years as bars', () => {
    const month = CALENDAR.series[0];
    if (!month) throw new Error('The fixture has no month');
    // 40 months from the first of the record, through the running one: more than a card shows as months
    const long = Array.from({ length: 40 }, (_, index) => ({
      ...month,
      month: `${String(2025 + Math.floor(index / 12))}-${String((index % 12) + 1).padStart(2, '0')}`,
    }));
    const yearly = [
      { year: 2025, count: 10, complete: true, gaps: false, converted: false },
      { year: 2026, count: 15, complete: false, gaps: false, converted: false },
    ];
    show({ type: 'area_calendar', data: { ...CALENDAR, series: long, yearly } });
    expect(screen.getByText('October 2026')).toBeInTheDocument();
    expect(screen.getByText(/through 29 October/)).toBeInTheDocument();
    expect(screen.getByText('Usual, same dates')).toBeInTheDocument();
    expect(screen.getByText('+50 %')).toBeInTheDocument();
    expect(screen.getByText('#1').nextElementSibling).toHaveTextContent('Among other years');
    expect(screen.getByText('By year')).toBeInTheDocument();
  });
  it('names a drawn area as one, in the language of the page', () => {
    show({
      type: 'area_calendar',
      data: { ...CALENDAR, area: { ...CALENDAR.area, id: null, name: 'Drawn area U1' } },
    });
    expect(screen.getByText('Drawn area')).toBeInTheDocument();
  });
  it('draws the region list with server type labels and opens a region', async () => {
    const actions = noActions();
    show(
      {
        type: 'region_list',
        data: {
          regions: [
            {
              id: REGION_ID,
              names: { en: 'North province' },
              kind: 'region',
              country_id: null,
              type: 'district',
              covered: false,
            },
          ],
          types: { district: { en: { one: 'district', other: 'districts' } } },
        },
      },
      actions,
    );
    await userEvent.click(screen.getByRole('button', { name: 'North province district' }));
    expect(actions.showArea).toHaveBeenCalledWith(REGION_ID);
  });
  it('draws one month with its number against the normal and the top provinces', () => {
    show({
      type: 'month_detail',
      data: {
        ...MONTH,
        month: '2025-03',
        kind: 'seen',
        value: 11465,
        normal: 9722,
        ratio: 1.18,
        rank: { place: 6, of: 23 },
        top_provinces: [
          {
            id: REGION_ID,
            names: { en: 'Corrientes', ru: 'Корриентес', es: 'Corrientes', fr: 'Corrientes' },
            value: 3314,
          },
        ],
      },
    });
    expect(screen.getByText('March 2025')).toBeInTheDocument();
    expect(screen.getByText('11,465')).toBeInTheDocument();
    expect(screen.getByText('+18 %')).toBeInTheDocument();
    expect(screen.getByText('5 of 23')).toBeInTheDocument();
  });

  it('moves the board to the same month of another year when its bar is pressed', async () => {
    const actions = noActions();
    show(
      {
        type: 'month_detail',
        data: {
          ...MONTH,
          month: '2025-03',
          kind: 'seen',
          value: 100,
          normal: 90,
          ratio: 1.1,
          rank: null,
          years: [
            { year: 2024, month: '2024-03', kind: 'seen', value: 80, low: null, high: null },
            { year: 2025, month: '2025-03', kind: 'seen', value: 100, low: null, high: null },
          ],
        },
      },
      actions,
    );
    // a month with no rank from the api shows no rank, not a dash
    expect(screen.queryByText('years had more')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '2024' }));
    expect(actions.showPeriod).toHaveBeenCalledWith(MONTH.area.id, '2024-03', '2024-03');
  });

  it('draws the weather of a month: the rain and the temperature against their normals, as the assistant has them', () => {
    const quantity = { unit: '', rank: 1, of_years: 2 };
    show({
      type: 'month_weather',
      data: {
        area: COUNTRY_ID,
        month: '2025-06',
        kind: 'observed',
        observed: {
          quantities: [
            {
              ...quantity,
              key: 'temperature_c',
              value: 17.4,
              normal: 16.15,
              anomaly: 1.25,
              anomaly_kind: 'difference',
              change_pct: null,
            },
            {
              ...quantity,
              key: 'rain_mm',
              value: 100,
              normal: 50,
              anomaly: 2,
              anomaly_kind: 'ratio',
              change_pct: 100,
            },
          ],
          normal_first_year: 1991,
          normal_last_year: 2020,
        },
        attribution: 'ERA5, Copernicus',
      },
    });
    expect(screen.getByText('Northland')).toBeInTheDocument();
    expect(screen.getByText('June 2025')).toBeInTheDocument();
    expect(screen.getByText('100 mm')).toBeInTheDocument();
    expect(screen.getByText('+100 %')).toBeInTheDocument();
    expect(screen.getByText('normal 50 mm')).toBeInTheDocument();
    // the temperature to the hundredth, as the service gives it and the text quotes it
    expect(screen.getByText('17.4 °C')).toBeInTheDocument();
    expect(screen.getByText('+1.25 °C')).toBeInTheDocument();
    expect(screen.getByText('normal 16.15 °C')).toBeInTheDocument();
    expect(screen.getByText('ERA5, Copernicus')).toBeInTheDocument();
  });

  it('draws a rain with too small a normal as a dash, and a drawn area by its word', () => {
    show({
      type: 'month_weather',
      data: {
        area: 'drawn',
        month: '2025-06',
        kind: 'observed',
        observed: {
          quantities: [
            {
              key: 'rain_mm',
              unit: 'mm',
              value: 1,
              normal: 3,
              anomaly: null,
              anomaly_kind: 'ratio',
              change_pct: null,
              rank: 1,
              of_years: 2,
            },
          ],
          normal_first_year: 1991,
          normal_last_year: 2020,
        },
        attribution: null,
      },
    });
    expect(screen.getByText('Drawn area')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  const WINDOW = {
    area: { id: COUNTRY_ID, name: 'Northland' },
    window: { start: '2025-07-01', end: '2025-07-31' },
    count: 120,
    median: 100,
    p10: 60,
    p90: 150,
    rank: 3,
    of: 14,
    ratio: 1.2,
    years: 13,
    partial: false,
    complete_through: null,
  };

  it('draws a date window against the same dates of the other years, and shows whole months on the board', async () => {
    const actions = noActions();
    show({ type: 'window_stats', data: WINDOW }, actions);
    expect(screen.getByText('Northland')).toBeInTheDocument();
    expect(screen.getByText('1 – 31 July 2025')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
    expect(screen.getByText('Usual, same dates')).toBeInTheDocument();
    expect(screen.getByText('+20 %')).toBeInTheDocument();
    expect(screen.getByText('#3 of 14')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Show in statistics' }));
    expect(actions.showPeriod).toHaveBeenCalledWith(COUNTRY_ID, '2025-07', '2025-07');
  });

  it('draws days inside a month without the button, a partial window with its last day, and nulls as dashes', () => {
    show({
      type: 'window_stats',
      data: {
        ...WINDOW,
        area: { id: null, name: 'Drawn area U1' },
        window: { start: '2025-07-10', end: '2025-07-20' },
        partial: true,
        complete_through: '2025-07-20',
        median: null,
        ratio: null,
        rank: null,
        of: null,
      },
    });
    expect(screen.getByText('Drawn area')).toBeInTheDocument();
    expect(screen.getByText('through 20 July')).toBeInTheDocument();
    expect(screen.getAllByText('—')).toHaveLength(3);
    expect(screen.queryByRole('button', { name: 'Show in statistics' })).not.toBeInTheDocument();
  });

  it('draws the month of a drawn area without a way to the board', () => {
    show({
      type: 'month_detail',
      data: {
        ...MONTH,
        area: { ...MONTH.area, id: 'drawn', kind: 'drawn' },
        month: '2025-03',
        kind: 'seen',
        value: 100,
        normal: 90,
        ratio: 1.1,
        years: [{ year: 2025, month: '2025-03', kind: 'seen', value: 100, low: null, high: null }],
      },
    });
    expect(screen.queryByRole('button', { name: 'Show in statistics' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '2025' })).toBeDisabled();
  });

  it('draws the blind check', () => {
    show({ type: 'forecast_check', data: CHECK });
    expect(screen.getByText('Check on 2023 to 2025')).toBeInTheDocument();
    expect(screen.getByText('Error per year')).toBeInTheDocument();
  });

  it('draws countries side by side', () => {
    show({
      type: 'countries',
      data: {
        first_year: 2003,
        last_year: 2025,
        source: 'MODIS',
        missing_years: [],
        cells_year: null,
        comparison: null,
        year_comparison: null,
        attribution: null,
        countries: [
          {
            id: OTHER_COUNTRY_ID,
            timezone: INTEGER_ZONE,
            covered: false,
            names: { en: 'Brazil', ru: 'Бразилия', es: 'Brasil', fr: 'Brésil' },
            area_km2: 8500000,
            average_per_year: 400000,
            density_per_1000_km2: 47.1,
            peak_month: 9,
            last_year_total: 232000,
            trend_ratio: 0.7,
            yearly: [],
            seasonal: [],
            years: [],
            bbox: null,
            geometry: null,
            cells: null,
          },
        ],
      },
    });
    expect(screen.getByText('Countries')).toBeInTheDocument();
    expect(screen.getByText('Brazil')).toBeInTheDocument();
    expect(screen.getByText('400,000')).toBeInTheDocument();
  });

  it('draws the stats of a drawn area, from the calendar or from the world grid', () => {
    const { unmount } = show({
      type: 'area_stats',
      data: {
        bbox: CONFIG_BBOX,
        timezone: INTEGER_ZONE,
        covered: true,
        source: 'calendar',
        cells: 12,
        summary: SUMMARY,
        world: null,
      },
    });
    expect(screen.getByText('−51 %')).toBeInTheDocument();
    unmount();
    show({
      type: 'area_stats',
      data: {
        bbox: CONFIG_BBOX,
        timezone: INTEGER_ZONE,
        covered: false,
        source: 'world',
        cells: 3,
        summary: null,
        world: {
          cells: 3,
          approximate: true,
          average_per_year: 5000,
          peak_month: 9,
          last_year_total: 4000,
          yearly: [],
        },
      },
    });
    expect(screen.getByText('Detections a year')).toBeInTheDocument();
    expect(screen.getByText('The area')).toBeInTheDocument();
  });

  it('lists fires, each a way to open it', async () => {
    const actions = noActions();
    show({ type: 'fire_list', data: FIRE_LIST }, actions);
    expect(screen.getByText('Villa General Savio')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Santo Tomé/ }));
    expect(actions.openFire).toHaveBeenCalledWith('20261028-1');
  });

  it('draws one fire with its numbers and a way to open it', async () => {
    const actions = noActions();
    show({ type: 'fire_detail', data: FIRE_DETAIL }, actions);
    expect(screen.getByText('≈ 252 ha')).toBeInTheDocument();
    expect(screen.getByText('652 MW')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Open the fire' }));
    expect(actions.openFire).toHaveBeenCalledWith('20261028-1');
  });

  it('draws a work plan as a small map and puts it on the map when asked', async () => {
    const actions = noActions();
    show({ type: 'work_plan', data: PLAN }, actions);
    expect(screen.getByRole('img', { name: 'Work plan' })).toBeInTheDocument();
    expect(screen.getByText('2 crews')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Show the plan on the map' }));
    expect(actions.showPlan).toHaveBeenCalledWith(PLAN);
  });

  it('draws the safety zones of a plan as hatched areas inside the box of the map', () => {
    const ring: [number, number][] = [
      [-56.2, -28.6],
      [-56.19, -28.6],
      [-56.19, -28.59],
      [-56.2, -28.6],
    ];
    const { container } = show({ type: 'work_plan', data: { ...PLAN, safe_zones: [ring] } });
    const zone = container.querySelector('polygon.mm-safe');
    expect(zone).not.toBeNull();
    expect(container.querySelector('pattern path.mm-hatch')).not.toBeNull();
    // the zone is filled with the pattern of its own map
    const pattern = container.querySelector('pattern')?.id ?? 'none';
    expect(zone?.getAttribute('style')).toContain(`#${pattern}`);
    // the zone is far from the crews: the map grows to hold it
    const [x = 0, y = 0] =
      (zone?.getAttribute('points') ?? '').split(' ')[0]?.split(',').map(Number) ?? [];
    expect(x).toBeGreaterThanOrEqual(0);
    expect(x).toBeLessThanOrEqual(320);
    expect(y).toBeGreaterThanOrEqual(0);
    expect(y).toBeLessThanOrEqual(180);
  });

  it('draws no safety zone when the plan has none', () => {
    const { container } = show({ type: 'work_plan', data: PLAN });
    expect(container.querySelector('polygon.mm-safe')).toBeNull();
  });

  it('opens a period in the calendar from its summary', async () => {
    const actions = noActions();
    show({ type: 'period_summary', data: SUMMARY }, actions);
    await userEvent.click(screen.getByRole('button', { name: 'Show in statistics' }));
    expect(actions.showPeriod).toHaveBeenCalled();
  });
});
