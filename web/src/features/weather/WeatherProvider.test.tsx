import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ANIMATION_STORAGE_KEY, useWeatherState, WIND_STORAGE_KEY } from './context';
import { WeatherProvider } from './WeatherProvider';

const wrapper = ({ children }: { children: ReactNode }) => (
  <WeatherProvider>{children}</WeatherProvider>
);

beforeEach(() => {
  localStorage.clear();
});

describe('WeatherProvider', () => {
  it('shows the wind at the fires until told otherwise', () => {
    const { result } = renderHook(useWeatherState, { wrapper });
    expect(result.current.wind).toBe('fires');
    expect(result.current.layers).toEqual([]);
  });

  it('keeps the choice of the wind like the language', () => {
    const first = renderHook(useWeatherState, { wrapper });
    act(() => {
      first.result.current.setWind('all');
    });
    expect(localStorage.getItem(WIND_STORAGE_KEY)).toBe('all');
    first.unmount();
    expect(renderHook(useWeatherState, { wrapper }).result.current.wind).toBe('all');
  });

  it('ignores a stored value it does not know', () => {
    localStorage.setItem(WIND_STORAGE_KEY, 'gale');
    expect(renderHook(useWeatherState, { wrapper }).result.current.wind).toBe('fires');
  });

  it('turns the layers on and off, both at once if asked', () => {
    const { result } = renderHook(useWeatherState, { wrapper });
    act(() => {
      result.current.toggleLayer('dryness');
      result.current.toggleLayer('rain');
    });
    expect(result.current.layers).toEqual(['dryness', 'rain']);
    act(() => {
      result.current.toggleLayer('dryness');
    });
    expect(result.current.layers).toEqual(['rain']);
  });

  it('keeps the layers of the calendar apart from those of the fires', () => {
    const { result } = renderHook(useWeatherState, { wrapper });
    act(() => {
      result.current.toggleClimate('day:rain');
    });
    expect(result.current.climate).toEqual(['day:rain']);
    expect(result.current.layers).toEqual([]);
    act(() => {
      result.current.toggleClimate('day:rain');
    });
    expect(result.current.climate).toEqual([]);
  });

  it('has the animation of the wind on, and keeps the choice like the language', () => {
    const first = renderHook(useWeatherState, { wrapper });
    expect(first.result.current.animation).toBe(true);
    act(() => {
      first.result.current.setAnimation(false);
    });
    expect(localStorage.getItem(ANIMATION_STORAGE_KEY)).toBe('off');
    first.unmount();
    expect(renderHook(useWeatherState, { wrapper }).result.current.animation).toBe(false);
  });

  it('leaves the animation off for a person who asks for less motion, until they turn it on', () => {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: true,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    try {
      const first = renderHook(useWeatherState, { wrapper });
      expect(first.result.current.animation).toBe(false);
      act(() => {
        first.result.current.setAnimation(true);
      });
      first.unmount();
      expect(renderHook(useWeatherState, { wrapper }).result.current.animation).toBe(true);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
