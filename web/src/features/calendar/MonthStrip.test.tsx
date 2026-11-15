import { act, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { useBoard } from '../board/context';
import { MonthStrip } from './MonthStrip';

/** Picks a month and a day of it, as a press on the calendar does. */
function PickDay() {
  const { setPick, setDay } = useBoard();
  useEffect(() => {
    setPick('2025-01');
    setDay('2025-01-05');
  }, [setPick, setDay]);
  return <MonthStrip />;
}

describe('the strip of the month', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('says nothing of a day whose figures are still on the way', async () => {
    // no answer ever comes
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => undefined)),
    );
    renderApp(<PickDay />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText(/5 Jan/)).toBeInTheDocument();
    expect(screen.queryByText(/no data/i)).not.toBeInTheDocument();
  });

  it('labels a day the server has nothing for like the other figures of the strip', async () => {
    // every answer is "not found": the day has no figures
    mockApi({});
    renderApp(<PickDay />);
    expect(await screen.findByText('no data')).toBeInTheDocument();
  });
});
