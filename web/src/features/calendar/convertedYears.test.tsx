import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CALENDAR, META, monthOf } from '../../test/calendarFixtures';
import { COUNTRY_ID } from '../../test/configFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { WidgetActionsContext, type WidgetActions } from '../chat/actions';
import { AreaCalendarBoard } from './AreaCalendarBoard';

const geometry = { ...CALENDAR.area, id: COUNTRY_ID };

function show(over: Record<string, unknown> = {}) {
  mockApi({
    'POST /api/calendar': () => json(200, { ...CALENDAR, season: null, ...over }),
    'GET /api/meta': () => json(200, META),
    [`GET /api/regions/${COUNTRY_ID}/geometry`]: () => json(200, geometry),
  });
  renderApp(
    <WidgetActionsContext
      value={{ addFact: vi.fn(), addMonth: vi.fn() } as unknown as WidgetActions}
    >
      <AreaCalendarBoard slotRef={null} onRegion={vi.fn()} />
    </WidgetActionsContext>,
  );
}

const year = (n: number, converted: boolean) => ({
  year: n,
  count: 100 * (n - 2000),
  complete: true,
  gaps: false,
  converted,
});

describe('the trend of the years and the years brought from MODIS', () => {
  it('says the trend beside the title of the years, and nothing when there is none', async () => {
    show();
    expect(await screen.findByText('10 years: −1 % a year')).toBeInTheDocument();
  });
  it('has no trend caption without a trend', async () => {
    show({ trend: null });
    await screen.findByRole('heading', { name: 'By year' });
    expect(screen.queryByText(/a year$/)).not.toBeInTheDocument();
  });
  it('colours the bars of converted years and names the colour under the chart', async () => {
    show({
      yearly: [year(2009, true), year(2010, true), year(2011, true), year(2012, false)],
    });
    expect(await screen.findByText('Converted from MODIS')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '2010: 1,000' })).toHaveAttribute(
      'data-converted',
      'on',
    );
    expect(screen.getByRole('button', { name: '2012: 1,200' })).not.toHaveAttribute(
      'data-converted',
    );
  });
  it('draws nothing for years without conversion', async () => {
    show({ yearly: [year(2012, false), year(2013, false)] });
    await screen.findByRole('heading', { name: 'By year' });
    expect(screen.queryByText('Converted from MODIS')).not.toBeInTheDocument();
  });
  it('puts the entry in the legend of the line when a converted month is in the window', async () => {
    const converted = monthOf('2026-09', { count: 5, median: 4, ratio: 1.2 });
    show({
      series: [...CALENDAR.series, { ...converted, converted: true }],
    });
    expect(await screen.findByText('Converted from MODIS')).toBeInTheDocument();
  });
  it('names the year and its count on hover, and says where a converted year comes from', async () => {
    show({ yearly: [year(2009, true), year(2012, false)] });
    await userEvent.hover(await screen.findByRole('button', { name: '2009: 900' }));
    const card = await screen.findByRole('status');
    expect(card).toHaveTextContent('2009');
    expect(card).toHaveTextContent('900');
    expect(card).toHaveTextContent('Converted from MODIS');
    // the question to the assistant waits for a press
    // (the head of the month has its own button; the pill is the one that describes a figure)
    expect(
      screen
        .queryAllByRole('button', { name: 'Ask SI' })
        .filter((button) => button.hasAttribute('aria-describedby')),
    ).toHaveLength(0);
    await userEvent.unhover(screen.getByRole('button', { name: '2009: 900' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
  it('says through which day a year that is not over is counted', async () => {
    show({ yearly: [{ ...year(2026, false), complete: false }] });
    await userEvent.hover(await screen.findByRole('button', { name: '2026: 2,600' }));
    expect(await screen.findByRole('status')).toHaveTextContent(/Through/);
  });
});
