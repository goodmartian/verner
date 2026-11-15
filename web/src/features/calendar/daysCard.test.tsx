import { fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, useRef } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CALENDAR, monthOf } from '../../test/calendarFixtures';
import { MONTH_DAYS } from '../../test/climateFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { useBoard } from '../board/context';
import { WidgetActionsContext, type WidgetActions } from '../chat/actions';
import { DaysCard } from './CalCards';

afterEach(() => {
  vi.unstubAllGlobals();
});

// October 2025 counted 430: the sum of its days, so the bars are the days as they came
const OCTOBER = { ...CALENDAR, series: [monthOf('2025-10', { count: 430 })] };

/** The card on the month of the fixture's days. */
function Harness() {
  const board = useBoard();
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    board.setPick('2025-10');
  }, [board]);
  return <DaysCard onPick={() => undefined} />;
}

function show() {
  mockApi({
    'POST /api/calendar': () => json(200, OCTOBER),
    'GET /api/calendar/days': () => json(200, MONTH_DAYS),
  });
  renderApp(
    <WidgetActionsContext
      value={{ addFact: vi.fn(), addMonth: vi.fn() } as unknown as WidgetActions}
    >
      <Harness />
    </WidgetActionsContext>,
  );
}

describe('the days of the month', () => {
  it('names the day under the pointer with the figures its bar is drawn from', async () => {
    show();
    const bar = await screen.findByRole('button', { name: '17 October: 300' });
    fireEvent.pointerEnter(bar, { pointerType: 'mouse' });
    const tip = await screen.findByRole('status');
    expect(tip).toHaveTextContent('17 October');
    expect(tip).toHaveTextContent('300 detections');
    expect(tip).toHaveTextContent('fires: 44');
    fireEvent.pointerLeave(bar);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('opens no card for a touch', async () => {
    show();
    const bar = await screen.findByRole('button', { name: '17 October: 300' });
    fireEvent.pointerEnter(bar, { pointerType: 'touch' });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('writes the pressed day under the bars, closes the card, and keeps the pill', async () => {
    show();
    const bar = await screen.findByRole('button', { name: '18 October: 90' });
    fireEvent.pointerEnter(bar, { pointerType: 'mouse' });
    await userEvent.click(bar);
    expect(bar).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByText('18 October: 90 detections · fires: 12')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask SI' })).toBeInTheDocument();
  });
});
