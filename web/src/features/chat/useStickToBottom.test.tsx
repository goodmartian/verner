import { act, fireEvent, render, screen } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { isNearBottom, NEAR, useStickToBottom } from './useStickToBottom';

function Thread({ resetKey = 0 }: { resetKey?: number }) {
  const key = resetKey;
  const box = useRef<HTMLDivElement>(null);
  const { atBottom, toBottom } = useStickToBottom(box, key);
  return (
    <>
      <div ref={box} data-testid="box" />
      <output>{String(atBottom)}</output>
      <button type="button" onClick={toBottom}>
        down
      </button>
    </>
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame'] });
});
afterEach(() => {
  vi.useRealTimers();
});

/** A box that has no layout in jsdom gets the sizes of a thread of 1000 high in a window of 400. */
function sized() {
  const box = screen.getByTestId('box');
  Object.defineProperty(box, 'scrollHeight', { value: 1000, configurable: true });
  Object.defineProperty(box, 'clientHeight', { value: 400, configurable: true });
  return box;
}

const grow = async (box: HTMLElement) => {
  await act(async () => {
    box.append(document.createElement('p'));
    await Promise.resolve();
    vi.advanceTimersByTime(50);
  });
};

describe('isNearBottom', () => {
  it('counts the bottom as within the margin', () => {
    expect(isNearBottom({ scrollHeight: 1000, clientHeight: 400, scrollTop: 600 })).toBe(true);
    expect(isNearBottom({ scrollHeight: 1000, clientHeight: 400, scrollTop: 600 - NEAR })).toBe(
      true,
    );
    expect(isNearBottom({ scrollHeight: 1000, clientHeight: 400, scrollTop: 600 - NEAR - 1 })).toBe(
      false,
    );
  });
});

describe('useStickToBottom', () => {
  it('goes to the bottom when the key changes, even from above', () => {
    const { rerender } = render(<Thread resetKey={1} />);
    const box = sized();
    box.scrollTop = 100;
    fireEvent.scroll(box);
    rerender(<Thread resetKey={2} />);
    expect(box.scrollTop).toBe(1000);
  });

  it('follows the growth of the thread while the person is at the bottom', async () => {
    render(<Thread />);
    const box = sized();
    await grow(box);
    expect(box.scrollTop).toBe(1000);
  });

  it('lets go when the person scrolls up, and shows the way down', async () => {
    render(<Thread />);
    const box = sized();
    box.scrollTop = 100;
    fireEvent.scroll(box);
    expect(screen.getByRole('status')).toHaveTextContent('false');
    await grow(box);
    expect(box.scrollTop).toBe(100);
  });

  it('goes down on the way down and stays with the thread from then on', async () => {
    render(<Thread />);
    const box = sized();
    box.scrollTop = 100;
    fireEvent.scroll(box);
    fireEvent.click(screen.getByRole('button', { name: 'down' }));
    expect(box.scrollTop).toBe(1000);
    expect(screen.getByRole('status')).toHaveTextContent('true');
    box.scrollTop = 1000;
    await grow(box);
    expect(box.scrollTop).toBe(1000);
  });

  it('follows when the person scrolled back near the bottom', async () => {
    render(<Thread />);
    const box = sized();
    box.scrollTop = 100;
    fireEvent.scroll(box);
    box.scrollTop = 600 - NEAR / 2;
    fireEvent.scroll(box);
    expect(screen.getByRole('status')).toHaveTextContent('true');
    await grow(box);
    expect(box.scrollTop).toBe(1000);
  });
});
