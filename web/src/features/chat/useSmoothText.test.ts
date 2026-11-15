import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useSmoothText } from './useSmoothText';

afterEach(() => {
  vi.useRealTimers();
});

const TEXT = 'alpha beta gamma delta epsilon zeta eta theta';

describe('useSmoothText', () => {
  it('lets a streaming text out by whole words, never a word half written', async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSmoothText(TEXT, true));
    const seen = new Set<string>();
    for (let step = 0; step < 40; step += 1) {
      await act(() => vi.advanceTimersByTimeAsync(40));
      seen.add(result.current);
    }
    expect(seen.size).toBeGreaterThan(2);
    for (const shown of seen) {
      expect(TEXT.startsWith(shown)).toBe(true);
      // a shown text ends where a word ends
      expect(shown === '' || shown === TEXT || TEXT[shown.length] === ' ').toBe(true);
    }
  });

  it('shows the whole text once the answer is over', async () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ live }) => useSmoothText(TEXT, live), {
      initialProps: { live: true },
    });
    rerender({ live: false });
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(result.current).toBe(TEXT);
  });
});
