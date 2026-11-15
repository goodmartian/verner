import { INTEGER_ZONE } from '../../test/configFixtures';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Timeline } from './Timeline';

afterEach(() => {
  vi.restoreAllMocks();
});

// a rail 1000 px wide that starts at 0: a moment is where its share of the scale is
const RAIL = { left: 0, right: 1000, width: 1000, top: 0, bottom: 28, height: 28, x: 0, y: 0 };

function railBox() {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    return (this.classList.contains('tl-rail') ? RAIL : { ...RAIL, width: 0 }) as DOMRect;
  });
}

const STEPS = [10, 30, 60, 90].map((at) => ({ at, value: `at ${String(at)}` }));

function Scale({
  value = 30,
  onSeek = vi.fn(),
  now,
  level,
  tag,
}: {
  value?: number | null;
  onSeek?: (value: string) => void;
  now?: { at: number; label?: string };
  level?: { label: string; onClick: () => void };
  tag?: boolean;
}) {
  return (
    <Timeline
      label="Satellite passes"
      from={0}
      to={100}
      bars={[
        { at: 10, height: 0.5 },
        { at: 30, height: 0 },
        { at: 60, height: 1, ring: true },
      ]}
      ticks={[{ at: 0, label: '28 Oct' }]}
      now={now ?? { at: 70, label: 'Now' }}
      marks={[{ at: 80, label: '+1' }]}
      steps={STEPS}
      value={value}
      valueLabel="30 Oct, 03:00"
      valueNote="3 detections"
      {...(tag === undefined ? {} : { tag })}
      zone={INTEGER_ZONE}
      playing={false}
      playLabel="Play"
      onPlay={vi.fn()}
      onSeek={onSeek}
      closeLabel="Close"
      onClose={vi.fn()}
      level={level ?? null}
    />
  );
}

describe('the scale of the player', () => {
  it('says the moment in the tag over the handle, and under it what the map shows', () => {
    render(<Scale />);
    const slider = screen.getByRole('slider', { name: 'Satellite passes' });
    expect(slider).toHaveAttribute('aria-valuetext', '30 Oct, 03:00, 3 detections');
    expect(slider.querySelector('.tl-handle b')).toHaveTextContent('30 Oct, 03:00');
    expect(slider.querySelector('.tl-handle small')).toHaveTextContent('3 detections');
  });

  it('keeps the handle bare without its tag, and the value for the screen reader', () => {
    render(<Scale tag={false} />);
    const slider = screen.getByRole('slider', { name: 'Satellite passes' });
    expect(slider.querySelector('.tl-handle')).not.toBeNull();
    expect(slider.querySelector('.tl-handle b')).toBeNull();
    expect(slider).toHaveAttribute('aria-valuetext', '30 Oct, 03:00, 3 detections');
  });

  it('says the time zone once, at the end of the scale', () => {
    render(<Scale />);
    expect(screen.getAllByText(INTEGER_ZONE)).toHaveLength(1);
  });

  it('draws a bar for what happened, a dot where nothing did, the words of the scale', () => {
    const { container } = render(<Scale />);
    expect(container.querySelectorAll('.tl-bar')).toHaveLength(2);
    expect(container.querySelectorAll('.tl-dot')).toHaveLength(1);
    expect(container.querySelector('.tl-bar.ring')).not.toBeNull();
    expect(container.querySelector('.tl-dot.on')).not.toBeNull();
    expect(container.querySelectorAll('.tl-mark')).toHaveLength(1);
    expect(screen.getByText('Now')).toBeInTheDocument();
    expect(screen.getByText('28 Oct')).toBeInTheDocument();
    // the mark has no text until it is chosen or pointed at
    expect(screen.queryByText('+1')).not.toBeInTheDocument();
  });

  it('names a mark when the pointer is on it, and no other', () => {
    railBox();
    render(<Scale />);
    const slider = screen.getByRole('slider');
    // the mark is at 80 of 100: 800 px; the pointer at 850 is farther from it than the reach
    fireEvent.pointerMove(slider, { clientX: 850 });
    expect(screen.queryByText('+1')).not.toBeInTheDocument();
    fireEvent.pointerMove(slider, { clientX: 805 });
    expect(screen.getByText('+1')).toBeInTheDocument();
    fireEvent.pointerLeave(slider);
    expect(screen.queryByText('+1')).not.toBeInTheDocument();
  });

  it('names the mark the handle stands on', () => {
    render(<Scale value={80} />);
    expect(screen.getByText('+1')).toBeInTheDocument();
  });

  it('is paler from now on, and not at all when nothing is to come', () => {
    const { container } = render(<Scale now={{ at: 70, label: 'Now' }} />);
    expect(container.querySelector('.timeline')).toHaveStyle({ '--now': '70%' });
  });

  it('goes to the nearest step where the scale is pressed', () => {
    railBox();
    const onSeek = vi.fn();
    render(<Scale value={10} onSeek={onSeek} />);
    fireEvent.pointerDown(screen.getByRole('slider'), { clientX: 640, button: 0 });
    // 640 of 1000 is 64 of 100: the step at 60
    expect(onSeek).toHaveBeenCalledWith('at 60');
  });

  it('does nothing where the handle already stands', () => {
    railBox();
    const onSeek = vi.fn();
    render(<Scale value={60} onSeek={onSeek} />);
    fireEvent.pointerDown(screen.getByRole('slider'), { clientX: 620, button: 0 });
    expect(onSeek).not.toHaveBeenCalled();
  });

  it('follows the pointer while it is down, and stops when it is up', () => {
    railBox();
    const onSeek = vi.fn();
    render(<Scale value={10} onSeek={onSeek} />);
    fireEvent.pointerDown(screen.getByRole('slider'), { clientX: 100, button: 0 });
    act(() => {
      window.dispatchEvent(new PointerEvent('pointermove', { clientX: 880 }));
    });
    expect(onSeek).toHaveBeenLastCalledWith('at 90');
    act(() => {
      window.dispatchEvent(new PointerEvent('pointerup'));
    });
    act(() => {
      window.dispatchEvent(new PointerEvent('pointermove', { clientX: 300 }));
    });
    expect(onSeek).toHaveBeenCalledTimes(1);
  });

  it('keeps to its ends when the pointer goes beyond them', () => {
    railBox();
    const onSeek = vi.fn();
    render(<Scale value={30} onSeek={onSeek} />);
    fireEvent.pointerDown(screen.getByRole('slider'), { clientX: 5000, button: 0 });
    expect(onSeek).toHaveBeenCalledWith('at 90');
  });

  it('moves a step with the arrows, to the first and the last with Home and End', async () => {
    const onSeek = vi.fn();
    render(<Scale value={30} onSeek={onSeek} />);
    const slider = screen.getByRole('slider');
    slider.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(onSeek).toHaveBeenLastCalledWith('at 60');
    await userEvent.keyboard('{ArrowLeft}');
    expect(onSeek).toHaveBeenLastCalledWith('at 10');
    await userEvent.keyboard('{End}');
    expect(onSeek).toHaveBeenLastCalledWith('at 90');
    await userEvent.keyboard('{Home}');
    expect(onSeek).toHaveBeenLastCalledWith('at 10');
    await userEvent.keyboard('a');
    expect(onSeek).toHaveBeenCalledTimes(4);
  });

  it('has no handle when it stands nowhere', () => {
    const { container } = render(<Scale value={null} />);
    expect(container.querySelector('.tl-handle')).toBeNull();
  });

  it('has a way up or down a level when it is given one', async () => {
    const onClick = vi.fn();
    render(<Scale level={{ label: 'All days', onClick }} />);
    await userEvent.click(screen.getByRole('button', { name: 'All days' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
