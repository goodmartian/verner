import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CALENDAR, META, monthOf } from '../../test/calendarFixtures';
import { COUNTRY_ID } from '../../test/configFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { WidgetActionsContext, type WidgetActions } from '../chat/actions';
import { AreaCalendarBoard } from './AreaCalendarBoard';

const geometry = { ...CALENDAR.area, id: COUNTRY_ID };
const MONTHS = ['2026-12', '2027-01', '2027-02', '2027-03', '2027-04', '2027-05'];
/** Six months ahead, the first `model` of them from the model, the error 12.3 % on the first. */
const ahead = (model: number) =>
  MONTHS.map((month, index) =>
    monthOf(month, {
      kind: 'forecast',
      count: null,
      median: 100,
      ratio: null,
      forecast: {
        median: 100,
        low: 50,
        high: 200,
        method: index < model ? 'model' : 'climatology',
        err_pct: index < model ? 12.3 : 40,
      },
    }),
  );

function show(model: number, seam: unknown = null) {
  const base = { ...CALENDAR, season: null };
  mockApi({
    'POST /api/calendar': () =>
      json(200, {
        ...base,
        series: [...CALENDAR.series, ...ahead(model)],
        quality: { ...CALENDAR.quality, seam },
        forecast: {
          first_month: MONTHS[0],
          last_month: MONTHS[5],
          accuracy: null,
          model_horizons: model,
          model_months: model,
          trained_at: null,
          trained_through: null,
          basis: model > 0 ? 'model' : 'climatology',
        },
      }),
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

const SEAM = {
  name: 'World',
  kind: 'world',
  seam: '2012-02',
  gap_pct: 1.81,
  threshold_pct: 3.46,
  as_is_jump: 6.2,
  status: 'pass',
};

describe('the method of the forecast and the join of the sensors', () => {
  it('tells the model alone when it gave all six months, with the error of the month', async () => {
    show(6);
    expect(await screen.findByText('Model')).toBeInTheDocument();
    expect(screen.getByText('±12%')).toBeInTheDocument();
    expect(screen.queryByText('Forecast error for a year')).not.toBeInTheDocument();
  });
  it('tells the model first and the median after it', async () => {
    show(4);
    expect(await screen.findByText('Model 4 mo., then median')).toBeInTheDocument();
    expect(screen.getByText('±12%')).toBeInTheDocument();
  });
  it('tells the median alone and keeps the error of the year, without the error of the month', async () => {
    show(0);
    expect(await screen.findByText('Median of past years')).toBeInTheDocument();
    expect(screen.queryByText('Month error on the check')).not.toBeInTheDocument();
  });
  it('shows the join that passed with a signed gap, and tells the gap and the threshold in words under the rows', async () => {
    show(0, SEAM);
    expect(await screen.findByText('Sensor join 2012')).toBeInTheDocument();
    expect(screen.getByText('passed, +1.8 %')).toBeInTheDocument();
    expect(
      screen.getByText(/differs from MODIS alone by \+1\.8 %; .* up to 3\.5 %\.$/),
    ).toBeInTheDocument();
  });
  it('leaves the join out of the words when there is not enough data for it', async () => {
    show(0, { ...SEAM, gap_pct: null, status: 'insufficient' });
    expect(await screen.findByText(/brought to the VIIRS scale/)).not.toHaveTextContent(/MODIS alone/);
  });
  it('says not passed for a failed join', async () => {
    show(0, { ...SEAM, gap_pct: -4.07, threshold_pct: 2.58, status: 'fail' });
    expect(await screen.findByText('not passed, −4.1 %')).toBeInTheDocument();
  });
  it('says there is not enough data, and has no row without a join check', async () => {
    show(0, { ...SEAM, gap_pct: null, status: 'insufficient' });
    expect(await screen.findByText('not enough data')).toBeInTheDocument();
  });
  it('has no row without a join check', async () => {
    show(0);
    await screen.findByText('Median of past years');
    expect(screen.queryByText(/Sensor join/)).not.toBeInTheDocument();
  });
});
