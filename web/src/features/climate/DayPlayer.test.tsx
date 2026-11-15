import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, useRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CALENDAR, monthOf } from '../../test/calendarFixtures';
import { MONTH_DAYS } from '../../test/climateFixtures';
import { apiError, json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { useBoard } from '../board/context';
import { CalTimeline } from '../calendar/CalTimeline';

const YEAR = {
  ...CALENDAR,
  series: [
    ...Array.from({ length: 12 }, (_, i) => monthOf(`2025-${String(i + 1).padStart(2, '0')}`)),
    monthOf('2027-01', {
      kind: 'forecast',
      count: null,
      forecast: { median: 5400, low: 2700, high: 10800, method: 'climatology', err_pct: 30 },
    }),
  ],
};

const routes = (days: boolean) => ({
  'POST /api/calendar': () => json(200, YEAR),
  'GET /api/calendar/days': () => (days ? json(200, MONTH_DAYS) : apiError(404, 'not_found')),
});

/** The month on the board, and the day when `day` is given; what the board then says is written out. */
function Harness({ day, big = true }: { day: string | null; big?: boolean }) {
  const board = useBoard();
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    board.setPick('2025-10');
    if (day) board.setDay(day);
  }, [board, day]);
  return (
    <>
      <CalTimeline onClose={vi.fn()} big={big} />
      <output>{board.day ?? 'month'}</output>
    </>
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the days of a month in the player of the calendar', () => {
  it('offers the days only when the month has days with fires', async () => {
    mockApi(routes(false));
    renderApp(<Harness day={null} />);
    await screen.findByRole('slider');
    expect(screen.queryByRole('button', { name: 'By day' })).not.toBeInTheDocument();
  });

  it('leaves the way into the days to the big map: the small one has no button for it', async () => {
    mockApi(routes(true));
    renderApp(<Harness day={null} big={false} />);
    await screen.findByRole('slider');
    expect(screen.queryByRole('button', { name: 'By day' })).not.toBeInTheDocument();
  });

  it('goes into the days from the months, to the first day with fires', async () => {
    mockApi(routes(true));
    renderApp(<Harness day={null} />);
    await userEvent.click(await screen.findByRole('button', { name: 'By day' }));
    expect(await screen.findByRole('status')).toHaveTextContent('2025-10-03');
    expect(screen.getByRole('slider').querySelector('.tl-handle b')).toHaveTextContent('3 Oct');
  });

  it('shows the days on one scale, a bar for each day with fires, the other days out of reach', async () => {
    mockApi(routes(true));
    const { container } = renderApp(<Harness day="2025-10-17" />);
    await screen.findByRole('button', { name: 'All days' });
    for (const label of ['1 Oct', '8', '15', '22', '29']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(container.querySelectorAll('.tl-bar')).toHaveLength(3);
    expect(container.querySelector('.tl-bar.on')).not.toBeNull();
    // the screen reader has the day; the eye has it in the days card until the player is used
    expect(screen.getByRole('slider')).toHaveAttribute(
      'aria-valuetext',
      '17 Oct, 300 detections · fires: 44',
    );
  });

  it('keeps the handle bare for a day picked on the board, and names it once the player is used', async () => {
    mockApi(routes(true));
    renderApp(<Harness day="2025-10-17" />);
    const slider = await screen.findByRole('slider');
    expect(slider.querySelector('.tl-handle')).not.toBeNull();
    expect(slider.querySelector('.tl-handle b')).toBeNull();
    slider.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(slider.querySelector('.tl-handle b')).toHaveTextContent('18 Oct');
  });

  it('names the day as soon as play is pressed', async () => {
    mockApi(routes(true));
    renderApp(<Harness day="2025-10-17" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Play days' }), {
      advanceTimers: (ms) => vi.advanceTimersByTime(ms),
    });
    expect(screen.getByRole('slider').querySelector('.tl-handle b')).toHaveTextContent('17 Oct');
  });

  it('picks another day with the arrows, and the whole month again on "All days"', async () => {
    mockApi(routes(true));
    renderApp(<Harness day="2025-10-17" />);
    const slider = await screen.findByRole('slider');
    slider.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('status')).toHaveTextContent('2025-10-18');
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('status')).toHaveTextContent('2025-10-18');
    await userEvent.keyboard('{ArrowLeft}{ArrowLeft}');
    expect(screen.getByRole('status')).toHaveTextContent('2025-10-03');
    await userEvent.click(screen.getByRole('button', { name: 'All days' }));
    expect(screen.getByRole('status')).toHaveTextContent('month');
    // the player is back to the months, with the way into the days
    expect(await screen.findByRole('button', { name: 'By day' })).toBeInTheDocument();
  });

  it('plays the days that had fires, one after another, and stops after the last', async () => {
    mockApi(routes(true));
    renderApp(<Harness day="2025-10-03" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Play days' }), {
      advanceTimers: (ms) => vi.advanceTimersByTime(ms),
    });
    act(() => {
      vi.advanceTimersByTime(700);
    });
    expect(screen.getByRole('status')).toHaveTextContent('2025-10-17');
    act(() => {
      vi.advanceTimersByTime(700);
    });
    expect(screen.getByRole('status')).toHaveTextContent('2025-10-18');
    act(() => {
      vi.advanceTimersByTime(1400);
    });
    expect(screen.getByRole('status')).toHaveTextContent('2025-10-18');
    expect(screen.getByRole('button', { name: 'Play days' })).toBeInTheDocument();
  });
});
