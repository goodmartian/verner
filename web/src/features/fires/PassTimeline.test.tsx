import { act, fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, useRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FIRE, FIRE_DETAIL, FIRE_LIST } from '../../test/fireFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { WEATHER_LEGEND } from '../../test/weatherFixtures';
import { useFiresState } from './context';
import { PassTimeline } from './PassTimeline';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-10-30T06:30:00Z') });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const routes = {
  'GET /api/fires': () => json(200, FIRE_LIST),
  'GET /api/weather/legend': () => json(200, WEATHER_LEGEND),
  [`GET /api/fires/${FIRE.id}`]: () => json(200, FIRE_DETAIL),
};

/** The player, with the fire open when `fire` is on. */
function Player({ fire = false }: { fire?: boolean }) {
  const state = useFiresState();
  const asked = useRef(false);
  useEffect(() => {
    if (asked.current || !fire) return;
    asked.current = true;
    state.select(FIRE.id);
  }, [state, fire]);
  return (
    <>
      <PassTimeline />
      <output>{[state.pass, state.clock, state.forecast].join('|')}</output>
    </>
  );
}

async function scale() {
  const slider = await screen.findByRole('slider', { name: 'Satellite passes' });
  // the passes have come when the caption says what the pass had
  await screen.findByText(/detections/);
  slider.focus();
  return slider;
}

describe('the player of the passes', () => {
  it('stands on the last pass, with the time of it over the handle and what it saw under the date', async () => {
    mockApi(routes);
    renderApp(<Player />);
    const slider = await scale();
    // 18:38 UTC is 12:38 in the fixture place zone
    expect(slider.querySelector('.tl-handle b')).toHaveTextContent('28 Oct, 12:38 GMT-6');
    expect(screen.getByText('Now')).toBeInTheDocument();
  });

  it('goes back to the first pass with the left arrow', async () => {
    mockApi(routes);
    renderApp(<Player />);
    await scale();
    await userEvent.keyboard('{ArrowLeft}');
    expect(screen.getByText('34 detections')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('0||0');
  });

  it('goes on from the last pass to now and then hour by hour into the forecast', async () => {
    mockApi(routes);
    renderApp(<Player />);
    await scale();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByText('weather now')).toBeInTheDocument();
    expect(screen.getByText(/30 Oct, 00:00 GMT-6/)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('|2026-10-30T06:00:00Z|0');
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByText('weather forecast')).toBeInTheDocument();
    expect(screen.getByText(/30 Oct, 01:00 GMT-6/)).toBeInTheDocument();
    await userEvent.keyboard('{ArrowLeft}{ArrowLeft}');
    expect(screen.getByText('128 detections')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('1||0');
  });

  it('ends at the last pass when the server has no weather', async () => {
    mockApi({
      ...routes,
      'GET /api/weather/legend': () =>
        json(200, { ...WEATHER_LEGEND, available: false, grid: null, layers: [] }),
    });
    renderApp(<Player />);
    await scale();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByText('128 detections')).toBeInTheDocument();
  });

  it('has no marks of the forecast of the growth until a fire is open', async () => {
    mockApi(routes);
    const { container } = renderApp(<Player />);
    await scale();
    expect(container.querySelectorAll('.tl-mark')).toHaveLength(0);
  });

  it('puts the three marks of the forecast of the growth after the last pass, and the handle goes to them', async () => {
    mockApi(routes);
    const { container } = renderApp(<Player fire />);
    await scale();
    await vi.waitFor(() => {
      expect(container.querySelectorAll('.tl-mark')).toHaveLength(3);
    });
    // the marks are dots until one is chosen
    expect(screen.queryByText('+1 h')).not.toBeInTheDocument();
    // the first of them is the next place after the last pass
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByText('outline forecast +1 h')).toBeInTheDocument();
    expect(screen.getByText('+1 h')).toBeInTheDocument();
    expect(screen.queryByText('+3 h')).not.toBeInTheDocument();
    // 18:38 and an hour on, in the place zone
    expect(screen.getByText(/28 Oct, 13:38 GMT-6/)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('1||1');
    expect(container.querySelector('.tl-mark.on')).not.toBeNull();
    // another place takes the forecast away
    await userEvent.keyboard('{ArrowLeft}');
    expect(screen.getByRole('status')).toHaveTextContent('1||0');
  });

  it('plays on from the last pass into the hours of the forecast, and says so on its button', async () => {
    vi.useFakeTimers({
      toFake: ['Date', 'setInterval', 'clearInterval'],
      now: new Date('2026-10-30T06:30:00Z'),
    });
    mockApi(routes);
    renderApp(<Player />);
    await scale();
    fireEvent.click(screen.getByRole('button', { name: 'Play passes' }));
    act(() => {
      vi.advanceTimersByTime(800);
    });
    expect(screen.getByRole('status')).toHaveTextContent('|2026-10-30T06:00:00Z|0');
    act(() => {
      vi.advanceTimersByTime(800);
    });
    // the forecast is walked three hours at a step
    expect(screen.getByRole('status')).toHaveTextContent('|2026-10-30T09:00:00Z|0');
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    act(() => {
      vi.advanceTimersByTime(2400);
    });
    expect(screen.getByRole('status')).toHaveTextContent('|2026-10-30T09:00:00Z|0');
  });
});
