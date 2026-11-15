import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CALENDAR, META, monthOf } from '../../test/calendarFixtures';
import { COUNTRY_ID, OTHER_COUNTRY_ID } from '../../test/configFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { WidgetActionsContext, type WidgetActions } from '../chat/actions';
import { AreaCalendarBoard } from './AreaCalendarBoard';

const geometry = { ...CALENDAR.area, id: COUNTRY_ID };
const ahead = monthOf('2025-03', {
  kind: 'forecast',
  count: null,
  median: 7000,
  ratio: null,
  forecast: { median: 7400, low: 4100, high: 17000, method: 'climatology', err_pct: 30 },
});
const calendar = {
  ...CALENDAR,
  series: [...CALENDAR.series, ahead],
  season: null,
};
const routes = (over: Record<string, unknown> = {}) => ({
  'POST /api/calendar': () => json(200, { ...calendar, ...over }),
  'GET /api/meta': () =>
    json(200, {
      ...META,
      examples: [
        {
          id: 'x',
          region_id: OTHER_COUNTRY_ID,
          names: { en: 'Portugal' },
          month: '2003-08',
          era: 'a',
          count: 11691,
          median: null,
          ratio: null,
          rank: null,
          of: null,
          found: true,
          source_url: null,
        },
      ],
    }),
  [`GET /api/regions/${COUNTRY_ID}/geometry`]: () => json(200, geometry),
});

function show() {
  const actions = { addFact: vi.fn(), addMonth: vi.fn() } as unknown as WidgetActions &
    Record<'addFact' | 'addMonth', ReturnType<typeof vi.fn>>;
  renderApp(
    <WidgetActionsContext value={actions}>
      <AreaCalendarBoard slotRef={null} onRegion={vi.fn()} />
    </WidgetActionsContext>,
  );
  return actions;
}
// the head of the month has its own «Ask SI»; the pill is the one that describes a figure
const pills = () =>
  screen
    .queryAllByRole('button', { name: 'Ask SI' })
    .filter((button) => button.hasAttribute('aria-describedby'));
const pill = () =>
  waitFor(() => {
    const [first] = pills();
    if (!first) throw new Error('No pill');
    return first;
  });
const noPill = () => {
  expect(pills()).toHaveLength(0);
};
const ask = async () => {
  await userEvent.click(await pill());
};

describe('the «Ask SI» pill of a pressed figure', () => {
  it('stays away on hover, shows on a press and puts the month in the question', async () => {
    mockApi(routes());
    const actions = show();
    const cell = await screen.findByRole('button', { name: /January 2025: 0$/ });
    // no system tip, no card on a rest of the pointer
    expect(cell).not.toHaveAttribute('title');
    await userEvent.hover(cell);
    await new Promise((resolve) => setTimeout(resolve, 400));
    noPill();
    await userEvent.click(cell);
    // the press still picks the month
    expect(cell).toHaveAttribute('aria-pressed', 'true');
    expect(await pill()).toHaveAccessibleDescription(/January 2025.*Normal 10/);
    await ask();
    expect(actions.addMonth).toHaveBeenCalledWith('2025-01');
    noPill();
  });

  it('names a month of the grid under the pointer, and says a month ahead is a forecast', async () => {
    mockApi(routes());
    show();
    const seen = await screen.findByRole('button', { name: /January 2025: 0$/ });
    await userEvent.hover(seen);
    expect(await screen.findByRole('status')).toHaveTextContent(/January 2025.*Normal 10/);
    const coming = screen.getByRole('button', { name: /March 2025: Forecast ≈ 7,400$/ });
    await userEvent.hover(coming);
    const card = screen.getByRole('status');
    expect(card).toHaveTextContent('March 2025');
    expect(card).toHaveTextContent('Outlook ≈ 7,400');
    expect(card).toHaveTextContent('from 4,100 to 17,000');
    expect(card).toHaveTextContent('Normal 7,000');
    // the colour scale has no caption beside it: its name shows under the pointer
    await userEvent.unhover(coming);
    const scale = screen.getByRole('group', { name: 'Weather key' });
    await userEvent.hover(scale);
    expect(screen.getByRole('status')).toHaveTextContent(/Against usual, %.*Cell colour/);
    await userEvent.unhover(scale);
    await userEvent.hover(coming);
    // a press puts the pill there instead
    await userEvent.click(coming);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    await userEvent.unhover(coming);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('goes by Escape or a press elsewhere', async () => {
    mockApi(routes());
    show();
    const cell = await screen.findByRole('button', { name: /January 2025: 0$/ });
    await userEvent.click(cell);
    await pill();
    await userEvent.keyboard('{Escape}');
    noPill();
    await userEvent.click(cell);
    await pill();
    await userEvent.click(document.body);
    noPill();
  });

  it('opens from the keyboard and takes the focus onto the pill', async () => {
    mockApi(routes());
    show();
    const cell = await screen.findByRole('button', { name: /January 2025: 0$/ });
    cell.focus();
    await userEvent.keyboard('{Enter}');
    expect(await pill()).toHaveFocus();
    await userEvent.keyboard('{Escape}');
    expect(cell).toHaveFocus();
  });

  it.each([['a tile of the month', 'Usual', 'Usual']])(
    'puts %s in the question as a fact',
    async (_name, tile, label) => {
      mockApi(routes());
      const actions = show();
      await screen.findByRole('heading', { name: 'January is below usual' });
      await userEvent.click(screen.getByRole('button', { name: new RegExp(`^${tile}`) }));
      await ask();
      expect(actions.addFact).toHaveBeenCalledWith(expect.objectContaining({ label }));
    },
  );

  it('puts the count tile in the question as the month', async () => {
    mockApi(routes());
    const actions = show();
    await screen.findByRole('heading', { name: 'January is below usual' });
    await userEvent.click(screen.getByRole('button', { name: /^Detections/ }));
    await ask();
    expect(actions.addMonth).toHaveBeenCalledWith('2025-01');
  });

  it.each([
    ['Detections', 'Trend', 'Trend'],
    // the area has no season card: the usual figure is told by the calendar
    ['Usual', 'Calendar', 'Calendar'],
    ['Against usual', 'Calendar', 'Calendar'],
    // the years are a card of the trend: the bar lights the trend
    ['Among other years', 'By year', 'Trend'],
  ])('leads the tile %s to its card, %s', async (tile, segment, lit) => {
    mockApi(routes());
    show();
    await screen.findByRole('heading', { name: 'January is below usual' });
    await userEvent.click(screen.getByRole('button', { name: new RegExp(`^${tile}`) }));
    const group = (await pill()).closest<HTMLElement>('[role="group"]');
    if (!group) throw new Error('No pill');
    await userEvent.click(within(group).getByRole('button', { name: segment }));
    noPill();
    const bar = screen.getByRole('navigation', { name: 'Sections' });
    expect(bar.querySelector('[aria-current="true"]')).toHaveTextContent(lit);
  });

  it('leads the usual tile to the season card where the area has one', async () => {
    mockApi(
      routes({
        season: {
          season_months: [8],
          season_share: 0.5,
          record_year: { year: 2025, count: 0 },
          quiet_year: { year: 2025, count: 0 },
          peak_month: { month: 8, median: 507 },
          quiet_month: { month: 12, median: 6 },
          average_year: 3168,
          ytd: null,
          unusual_months: { count: 0, last: null },
          season_strength: 84.5,
        },
      }),
    );
    show();
    await screen.findByRole('heading', { name: 'January is below usual' });
    await userEvent.click(screen.getByRole('button', { name: /^Usual/ }));
    const group = (await pill()).closest<HTMLElement>('[role="group"]');
    if (!group) throw new Error('No pill');
    expect(within(group).getByRole('button', { name: 'Season' })).toBeInTheDocument();
  });

  it('opens over a bar of the years', async () => {
    mockApi(routes());
    const actions = show();
    await userEvent.click(await screen.findByRole('button', { name: '2025: 0' }));
    await ask();
    expect(actions.addFact).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'By year', value: '0', period: '2025' }),
    );
  });

  it('opens over a row of a card', async () => {
    mockApi(routes());
    const actions = show();
    const value = await screen.findByRole('button', { name: /^±25/ });
    await userEvent.click(value);
    await ask();
    expect(actions.addFact).toHaveBeenCalledWith(
      expect.objectContaining({ value: expect.stringMatching(/^±25/) as string }),
    );
  });

  it('opens over a season of the known ones, without the area of the board in the line', async () => {
    mockApi(routes());
    const actions = show();
    // a press only opens the card: the board does not move until «Show on the board»
    await userEvent.click(await screen.findByRole('button', { name: /Portugal/ }));
    expect(await pill()).toHaveAccessibleDescription(/Portugal, August 2003/);
    expect(screen.getByRole('button', { name: 'Show on the board' })).toBeVisible();
    await ask();
    expect(actions.addFact).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'Portugal, August 2003', value: '11,691', area: '' }),
    );
  });

  it('opens over a month ahead of the forecast', async () => {
    mockApi(routes());
    const actions = show();
    const bar = await screen.findByRole('button', { name: /March 2025: ≈/ });
    await userEvent.click(bar);
    expect(await pill()).toHaveAccessibleDescription(/forecast, 4,100 to 17,000/);
    await ask();
    expect(actions.addMonth).toHaveBeenCalledWith('2025-03');
  });

  it('keeps no little plus on the board', async () => {
    mockApi(routes());
    show();
    await screen.findByRole('button', { name: '2025: 0' });
    expect(screen.queryByRole('button', { name: /^Add to the question/ })).not.toBeInTheDocument();
  });

  it('leaves the figures plain where there is no chat to take them', async () => {
    mockApi(routes());
    renderApp(<AreaCalendarBoard slotRef={null} onRegion={vi.fn()} />);
    const cell = await screen.findByRole('button', { name: /January 2025: 0$/ });
    await userEvent.click(cell);
    noPill();
    expect(cell).toHaveAttribute('aria-pressed', 'true');
  });
});
