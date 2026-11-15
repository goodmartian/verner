import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CALENDAR, META, monthOf } from '../../test/calendarFixtures';
import { COUNTRY_ID, makeConfig } from '../../test/configFixtures';
import { apiError, json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { AreaCalendarBoard } from './AreaCalendarBoard';

const geometry = { ...CALENDAR.area, id: COUNTRY_ID };
const routes = {
  'POST /api/calendar': () => json(200, CALENDAR),
  'GET /api/meta': () => json(200, META),
  [`GET /api/regions/${COUNTRY_ID}/geometry`]: () => json(200, geometry),
};
function show(config = makeConfig()) {
  return renderApp(<AreaCalendarBoard slotRef={null} onRegion={vi.fn()} />, config);
}
async function chooseAction(name: string) {
  await userEvent.click(await screen.findByRole('button', { name }));
}
/** Catches the downloads the page starts: the address and the name of each, with no file read and nothing opened. */
function catchDownloads() {
  const saved: { href: string; name: string }[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    saved.push({ href: this.getAttribute('href') ?? '', name: this.download });
  });
  return saved;
}
const refuse = (status: number, code: string, wait?: number) => () =>
  new Response(JSON.stringify({ error: { code, message: code } }), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...(wait ? { 'Retry-After': String(wait) } : {}),
    },
  });
async function askEveryDetection() {
  await screen.findByRole('heading', { name: /January/ });
  await chooseAction('Download CSV');
  await userEvent.click(screen.getByRole('menuitem', { name: /^All detections/ }));
}

describe('area calendar UI', () => {
  // the spies and stubs of one test stay in it
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  it('gives the month as one verdict and four figures, each said once', async () => {
    mockApi(routes);
    const view = show();
    await screen.findByRole('heading', { name: 'January is below usual' });
    const tiles = view.container.querySelector<HTMLElement>('[class*="tiles"]');
    if (!tiles) throw new Error('Missing the figures of the month');
    const figures = within(tiles);
    expect(figures.getByText('Detections').nextElementSibling).toHaveTextContent('0');
    expect(figures.getByText('Usual').nextElementSibling).toHaveTextContent('10');
    expect(figures.getByText('Against usual').nextElementSibling).toHaveTextContent('−100 %');
    expect(figures.getByText('#2')).toBeInTheDocument();
    expect(figures.getByText('of 3 years')).toBeInTheDocument();
    expect(screen.queryByText('Current month vs median')).not.toBeInTheDocument();
    expect(screen.queryByText('More calendar details')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /February 2025: —$/ }));
    expect(screen.getByRole('heading', { name: 'February 2025' })).toBeInTheDocument();
    expect(figures.getAllByText('—')).toHaveLength(5);
    expect(figures.queryByText('0')).not.toBeInTheDocument();
  });
  const withJanuary = (over: Parameters<typeof monthOf>[1]) => ({
    ...CALENDAR,
    series: [monthOf('2025-01', over), ...CALENDAR.series.slice(1)],
  });
  it.each([
    [
      'the first place of all years is the highest, whatever the percent',
      { count: 500, median: 400, ratio: 1.18, rank: 1, of: 24 },
      'January: the highest of all years',
    ],
    [
      'the last place is the lowest',
      { count: 100, median: 400, ratio: 0.25, rank: 24, of: 24 },
      'January: the lowest of all years',
    ],
    [
      'under ten fires on both sides says there are few, and not a percent',
      { count: 2, median: 1, ratio: 2, rank: 1, of: 24 },
      'January: hardly any detections, 2 against a usual 1',
    ],
  ])('tells %s', async (_name, over, heading) => {
    mockApi({ ...routes, 'POST /api/calendar': () => json(200, withJanuary(over)) });
    const view = show();
    await screen.findByRole('heading', { name: heading });
    const tiles = view.container.querySelector<HTMLElement>('[class*="tiles"]');
    if (!tiles) throw new Error('Missing the figures of the month');
    // the tile of the comparison holds the difference when there are few fires, and a percent otherwise
    const few = heading.includes('hardly');
    expect(within(tiles).getByText('Against usual').nextElementSibling).toHaveTextContent(
      few ? '+1' : '%',
    );
    if (few) expect(tiles.textContent).not.toContain('%');
  });
  it('says there are no fires, as usual, and leaves the comparison and the place empty when both are nothing', async () => {
    mockApi({
      ...routes,
      'POST /api/calendar': () =>
        json(200, withJanuary({ count: 0, median: 0, ratio: null, rank: 1, of: 24 })),
    });
    const view = show();
    await screen.findByRole('heading', { name: 'January: no detections, as usual' });
    const tiles = view.container.querySelector<HTMLElement>('[class*="tiles"]');
    if (!tiles) throw new Error('Missing the figures of the month');
    const figures = within(tiles);
    expect(figures.getByText('Against usual').nextElementSibling).toHaveTextContent(/^—$/);
    expect(figures.getByText('Among other years').nextElementSibling).toHaveTextContent(/^—$/);
    expect(figures.queryByText('#1')).not.toBeInTheDocument();
    expect(figures.queryByText('of 24 years')).not.toBeInTheDocument();
  });
  it('keeps the years of a short period whole and reads a month outside the period from the record', async () => {
    const early = monthOf('2026-01', { count: 5, median: 4, ratio: 1.2, rank: 1, of: 3 });
    const picked = monthOf('2026-03', { count: 7, median: 4, ratio: 1.7, rank: 1, of: 3 });
    const record = {
      ...CALENDAR,
      series: [monthOf('2025-01', { count: 1, median: 4, ratio: 0.25 }), early, picked],
    };
    mockApi({
      ...routes,
      'POST /api/calendar': async (request) => {
        const body = (await request.json()) as { from?: string };
        return json(200, body.from ? { ...record, series: [picked] } : record);
      },
    });
    show();
    await userEvent.click(await screen.findByRole('button', { name: 'All years, 2025–2026' }));
    const month = () => within(screen.getByRole('dialog', { name: 'Period' })).getByText('Mar');
    await userEvent.click(month());
    await userEvent.click(month());
    // the period is one month (its label has no dash), and the grid stays the map of the whole record
    await waitFor(() => {
      expect(document.getElementById('pp-label')).not.toHaveTextContent('–');
    });
    const cell = await screen.findByRole('button', { name: /January 2026: 5/ });
    expect(cell).toBeEnabled();
    expect(await screen.findByRole('button', { name: /January 2025: 1/ })).toBeEnabled();
    // a month of the row outside the period is read from the record: the head follows it
    await userEvent.click(cell);
    await screen.findByRole('heading', { name: /January/ });
  });
  it('names the whole record in words, not by the years the picker can reach, and its forecast too', async () => {
    mockApi({
      ...routes,
      'POST /api/calendar': () =>
        json(200, {
          ...CALENDAR,
          presets: [
            { id: 'forecast', kind: 'forecast', first_month: '2026-11', last_month: '2027-04' },
          ],
        }),
    });
    show();
    // the archive reaches December 2026, the record ends in October: the record is what is on screen
    expect(await screen.findByRole('button', { name: 'All years, 2025–2026' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'All years, 2025–2026' }));
    expect(
      within(screen.getByRole('dialog', { name: 'Period' })).getByRole('button', {
        name: /^Forecast/,
      }),
    ).toBeInTheDocument();
  });
  it('leads a period it has no months for to the whole record or its last month', async () => {
    const calls = mockApi({
      ...routes,
      'POST /api/calendar': async (request) => {
        const body = (await request.json()) as { from?: string };
        return body.from === '2026-12'
          ? apiError(400, 'invalid_period')
          : json(200, body.from ? { ...CALENDAR, series: [CALENDAR.current_month] } : CALENDAR);
      },
    });
    show();
    await userEvent.click(await screen.findByRole('button', { name: 'All years, 2025–2026' }));
    // the grid opens on 2026, whose December the picker allows and the area has no forecast for
    const dialog = within(screen.getByRole('dialog', { name: 'Period' }));
    await userEvent.click(dialog.getByText('Dec'));
    await userEvent.click(dialog.getByText('Dec'));
    expect(await screen.findByText('There is no data for this period.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'October 2026' }));
    await screen.findByRole('heading', { name: /October/ });
    const asked = calls.filter((call) => call.path === '/api/calendar').at(-1);
    expect(asked?.body).toMatchObject({ from: '2026-10', to: '2026-10' });
  });
  it('waits with the places of the figures, not "no data", before there is an area to ask about', () => {
    mockApi(routes);
    const view = renderApp(<AreaCalendarBoard slotRef={null} onRegion={vi.fn()} />, null);
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true');
    // the skeleton is the first screen of the board: the calendar card has its grid of pale cells, hidden from readers
    const cells = view.container.querySelectorAll('[aria-hidden="true"] [class*="cell"]');
    expect(cells).toHaveLength(9 * 12);
    expect(view.container.querySelector('.cal-body')).toHaveAttribute('data-skeleton', 'true');
    expect(screen.queryByText('No data yet.')).not.toBeInTheDocument();
    expect(screen.queryByText('no data yet')).not.toBeInTheDocument();
  });
  it('keeps the board of the period before, dimmed, until the new period comes', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    mockApi({
      ...routes,
      'POST /api/calendar': async (request) => {
        const body = (await request.json()) as { from?: string };
        if (!body.from) return json(200, CALENDAR);
        await gate;
        return json(200, { ...CALENDAR, series: [CALENDAR.current_month] });
      },
    });
    const view = show();
    await screen.findByRole('heading', { name: 'January is below usual' });
    await userEvent.click(screen.getByRole('button', { name: 'All years, 2025–2026' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Period' }));
    await userEvent.click(dialog.getByText('Oct'));
    await userEvent.click(dialog.getByText('Oct'));
    const body = view.container.querySelector('.cal-body');
    await waitFor(() => {
      expect(body).toHaveAttribute('aria-busy', 'true');
    });
    // the figures before stay in their places: no skeleton in between
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'January is below usual' })).toBeInTheDocument();
    release();
    await waitFor(() => {
      expect(body).not.toHaveAttribute('aria-busy');
    });
    expect(
      screen.queryByRole('heading', { name: 'January is below usual' }),
    ).not.toBeInTheDocument();
  });
  it('leads an area of sea to the choice of another one', async () => {
    mockApi({ ...routes, 'POST /api/calendar': () => apiError(422, 'no_land') });
    const onRegion = vi.fn();
    renderApp(<AreaCalendarBoard slotRef={null} onRegion={onRegion} />);
    expect(await screen.findByText('This area has no land.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Change region' }));
    expect(onRegion).toHaveBeenCalledOnce();
  });
  it('leads an outline the service refuses to another area, not to asking again', async () => {
    mockApi({ ...routes, 'POST /api/calendar': () => apiError(400, 'invalid_area') });
    const onRegion = vi.fn();
    renderApp(<AreaCalendarBoard slotRef={null} onRegion={onRegion} />);
    expect(
      await screen.findByText('This area cannot be used: check its outline or coordinates.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Change region' }));
    expect(onRegion).toHaveBeenCalledOnce();
  });
  it('says so over the figures where nothing was ever seen, and offers another area', async () => {
    const quiet = {
      ...CALENDAR,
      series: CALENDAR.series.map((point) => ({
        ...point,
        count: point.count === null ? null : 0,
      })),
      current_month: { ...CALENDAR.current_month, count: 0 },
    };
    mockApi({ ...routes, 'POST /api/calendar': () => json(200, quiet) });
    show();
    expect(
      await screen.findByText('Satellites detected no burning here in the whole archive.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Change region' })).toBeInTheDocument();
  });
  it('says nothing of the kind where fires were seen', async () => {
    mockApi(routes);
    show();
    await screen.findByRole('heading', { name: 'January is below usual' });
    expect(
      screen.queryByText('Satellites detected no burning here in the whole archive.'),
    ).not.toBeInTheDocument();
  });
  it('says the server is down and asks again when the button is pressed', async () => {
    let calls = 0;
    mockApi({
      ...routes,
      'POST /api/calendar': () => {
        calls += 1;
        return calls === 1 ? apiError(503, 'unavailable') : json(200, CALENDAR);
      },
    });
    show();
    expect(await screen.findByRole('status')).toBeInTheDocument();
    await userEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    await screen.findByRole('heading', { name: 'January is below usual' });
    expect(calls).toBe(2);
  });
  it('reads a month still running against the same dates, with the whole month in small print', async () => {
    const running = monthOf('2026-11', {
      kind: 'running',
      count: 3963,
      median: 11528,
      ratio: 0.34,
      rank: 22,
      of: 24,
      partial: true,
      complete_through: '2026-11-11',
    });
    const to_date = {
      through: '2026-11-11',
      count: 3963,
      median: 4769,
      ratio: 0.83,
      rank: 13,
      of: 24,
    };
    mockApi({
      ...routes,
      'POST /api/calendar': () =>
        json(200, {
          ...CALENDAR,
          series: [running],
          normals: [{ month: 11, median: 11528, mean: 12000, p10: null, p90: null, years: 24 }],
          current_month: { ...running, to_date },
        }),
    });
    const view = show();
    await screen.findByRole('heading', { name: /November so far is near usual/ });
    const tiles = view.container.querySelector<HTMLElement>('[class*="tiles"]');
    if (!tiles) throw new Error('Missing the figures of the month');
    const figures = within(tiles);
    expect(figures.getByText('Usual, same dates').nextElementSibling).toHaveTextContent('4,769');
    expect(figures.getByText('Against usual').nextElementSibling).toHaveTextContent('−17 %');
    expect(figures.getByText('#13')).toBeInTheDocument();
    expect(figures.getByText('Usual for the whole month: 11,528')).toBeInTheDocument();
  });
  it('draws the calendar as rows of cells with the usual month on top and a total for the year', async () => {
    mockApi(routes);
    show();
    await screen.findByRole('heading', { name: 'January is below usual' });
    const grid = within(screen.getByRole('group', { name: 'Detections by year and month' }));
    expect(grid.getByText('Usual')).toBeInTheDocument();
    expect(grid.getByText('2025')).toBeInTheDocument();
    expect(grid.getByRole('button', { name: /January 2025: 0$/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    // one view of the grid: the count in the cell, the colour against the usual; no switch between them
    expect(screen.queryByRole('button', { name: 'Against usual' })).not.toBeInTheDocument();
  });
  it.each([
    ['heads the years before 2003 with a line', '2000-11', true],
    ['has no such line when the record starts in 2003', '2003-01', false],
  ])('%s', async (_, first, shown) => {
    mockApi({
      ...routes,
      'POST /api/calendar': () =>
        json(200, { ...CALENDAR, series: [monthOf(first, { count: 5 }), ...CALENDAR.series] }),
    });
    show();
    await screen.findByRole('heading', { name: 'January is below usual' });
    const grid = within(screen.getByRole('group', { name: 'Detections by year and month' }));
    expect(grid.getByText(first.slice(0, 4))).toBeInTheDocument();
    const line = grid.queryByText('Before 2003: morning satellite, not in the usual');
    if (shown) expect(line).toBeInTheDocument();
    else expect(line).not.toBeInTheDocument();
  });
  it('names the sections of the board in a bar that stays in view', async () => {
    mockApi(routes);
    show();
    const bar = await screen.findByRole('navigation', { name: 'Sections' });
    expect(
      within(bar)
        .getAllByRole('button')
        .map((button) => button.textContent),
    ).toEqual(['Overview', 'Calendar', 'Trend']);
    // one section is lit: which one depends on the scroll, which a test without layout does not have
    expect(bar.querySelectorAll('[aria-current="true"]')).toHaveLength(1);
    // the period of the board and its file stay in view with the sections: they are in the same sticky bar, once
    const sticky = bar.closest<HTMLElement>('[data-bar]');
    if (!sticky) throw new Error('The sections are not in the sticky bar');
    expect(within(sticky).getByRole('button', { name: 'Download CSV' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Download CSV' })).toHaveLength(1);
  });
  it('offers the periods of the months chart with five years chosen first', async () => {
    mockApi(routes);
    show();
    const group = await screen.findByRole('group', { name: 'Period of the chart' });
    const pressed = within(group)
      .getAllByRole('button')
      .map((button) => [button.textContent, button.getAttribute('aria-pressed')]);
    expect(pressed).toEqual([
      ['2y', 'false'],
      ['5y', 'true'],
      ['10y', 'false'],
      ['All', 'false'],
    ]);
  });
  it('remembers a folded card in one key for the board', async () => {
    mockApi(routes);
    show();
    const [fold] = await screen.findAllByRole('button', { name: 'Fold' });
    if (!fold) throw new Error('Missing the fold button');
    await userEvent.click(fold);
    expect(JSON.parse(localStorage.getItem('senda-cal-folds') ?? '{}')).toEqual({ trend: true });
    localStorage.removeItem('senda-cal-folds');
  });
  it('gives each card a hint instead of a long sentence', async () => {
    mockApi(routes);
    show();
    expect((await screen.findAllByRole('button', { name: 'What is this' })).length).toBeGreaterThan(
      0,
    );
  });
  it('shows an honest empty state on 503 without a fallback', async () => {
    const calls = mockApi({
      ...routes,
      'POST /api/calendar': () => apiError(503, 'grid_unavailable'),
    });
    show();
    await screen.findByText('The global grid is not available yet. No calendar data to show.');
    expect(screen.queryByRole('group', { name: 'Detections by month' })).not.toBeInTheDocument();
    expect(calls.some((call) => call.path.startsWith('/api/calendar/'))).toBe(false);
    expect(calls.filter((call) => call.path === '/api/calendar')).not.toHaveLength(0);
  });
  it('opens a menu of two files that says what each holds, the table of months first', async () => {
    mockApi(routes);
    show();
    await screen.findByRole('heading', { name: 'January is below usual' });
    const button = await screen.findByRole('button', { name: 'Download CSV' });
    expect(button).toHaveAttribute('aria-haspopup', 'menu');
    await userEvent.click(button);
    const items = within(screen.getByRole('menu', { name: 'Download CSV' })).getAllByRole(
      'menuitem',
    );
    expect(items.map((item) => item.textContent)).toEqual([
      'By monthThe calendar table for this period',
      'All detectionsEach satellite point with its correction. Large file.',
    ]);
    expect(items[0]).toHaveFocus();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('menu', { name: 'Download CSV' })).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });
  it('has the browser download every detection by the address of the ticket, without reading the file', async () => {
    const saved = catchDownloads();
    const calls = mockApi({
      ...routes,
      'POST /api/export/ticket': () =>
        json(200, { url: '/api/export/file/t1', rows: 3_100_000, name: 'verner_ar_all.csv' }),
    });
    show();
    await askEveryDetection();
    await waitFor(() => {
      expect(saved).toEqual([{ href: '/api/export/file/t1', name: 'verner_ar_all.csv' }]);
    });
    // the page asked only for the ticket: the file itself is the browser's to fetch
    expect(calls.map((call) => call.path).filter((path) => path.startsWith('/api/export'))).toEqual(
      ['/api/export/ticket'],
    );
    expect(screen.queryByRole('menu', { name: 'Download CSV' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download CSV' })).toHaveFocus();
  });
  it.each([
    [
      'a file too large',
      refuse(413, 'payload_too_large'),
      'Too many rows for one file. Choose a shorter period or a smaller area.',
    ],
    [
      'too many downloads, in minutes',
      refuse(429, 'export_quota', 240),
      'Too many downloads. Try again in 4 min.',
    ],
    [
      'the day spent',
      refuse(429, 'export_day_cap', 3600),
      'No more downloads today. The table by month is still available.',
    ],
    [
      'other downloads running',
      refuse(429, 'export_busy', 10),
      'Other downloads are running now. Try again in a minute.',
    ],
  ])('says %s under every detection, and keeps the menu open', async (_name, answer, text) => {
    const saved = catchDownloads();
    mockApi({ ...routes, 'POST /api/export/ticket': answer });
    show();
    await askEveryDetection();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(text);
    expect(alert.previousElementSibling).toHaveTextContent(/^All detections/);
    expect(screen.getByRole('menu', { name: 'Download CSV' })).toContainElement(alert);
    expect(saved).toEqual([]);
  });
  it('asks for one year when the whole world is too large', async () => {
    mockApi({
      ...routes,
      'GET /api/regions/WORLD/geometry': () => json(200, { ...geometry, id: 'WORLD' }),
      'POST /api/export/ticket': refuse(413, 'payload_too_large'),
    });
    show(makeConfig({ default_area: { id: 'WORLD' } }));
    await askEveryDetection();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The whole world can be downloaded for one year. Choose a year.',
    );
  });
  it('explains a 413 export in the menu, under its file, and keeps the menu open', async () => {
    mockApi({ ...routes, 'POST /api/export/ticket': () => apiError(413, 'payload_too_large') });
    show();
    await askEveryDetection();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      'Too many rows for one file. Choose a shorter period or a smaller area.',
    );
    const menu = screen.getByRole('menu', { name: 'Download CSV' });
    expect(menu).toContainElement(alert);
    expect(alert.previousElementSibling).toHaveTextContent(/^All detections/);
    await waitFor(() => {
      expect(screen.getByRole('menuitem', { name: /^All detections/ })).toHaveFocus();
    });
  });
  it('saves the table of months under the name the server gave it', async () => {
    const NativeURL = URL;
    const create = vi.fn(() => 'blob:export');
    vi.stubGlobal(
      'URL',
      class extends NativeURL {
        static override createObjectURL = create;
        static override revokeObjectURL = vi.fn();
      },
    );
    let saved = '';
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved = this.download;
    });
    const calls = mockApi({
      ...routes,
      'POST /api/export/months': () =>
        new Response('month,count\n2025-01,0\n', {
          headers: {
            'Content-Type': 'text/csv',
            'Content-Disposition': 'attachment; filename="verner_ar_2025-01_2025-02_months.csv"',
          },
        }),
    });
    show();
    await screen.findByRole('heading', { name: 'January is below usual' });
    await chooseAction('Download CSV');
    await userEvent.click(screen.getByRole('menuitem', { name: /^By month/ }));
    await waitFor(() => {
      expect(create).toHaveBeenCalledOnce();
    });
    expect(click).toHaveBeenCalledOnce();
    expect(saved).toBe('verner_ar_2025-01_2025-02_months.csv');
    expect(calls.some((call) => call.path === '/api/export')).toBe(false);
    expect(screen.queryByRole('menu', { name: 'Download CSV' })).not.toBeInTheDocument();
  });
});
