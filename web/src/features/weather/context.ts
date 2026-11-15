import { createContext, useContext } from 'react';
import { readStored } from '../../lib/storage';

/** Where the wind is drawn: by the fires, over the whole map, or not at all. */
export type WindMode = 'fires' | 'all' | 'off';
export const WIND_MODES: readonly WindMode[] = ['fires', 'all', 'off'];
export const WIND_STORAGE_KEY = 'senda-wind';
export const ANIMATION_STORAGE_KEY = 'senda-wind-animation';

/** The pictures of the weather that can be laid on the map. */
export type WeatherLayer = 'rain' | 'dryness';

export function readWindMode(): WindMode {
  const stored = readStored(WIND_STORAGE_KEY);
  return WIND_MODES.find((mode) => mode === stored) ?? 'fires';
}

/** The animation of the wind is on unless it was turned off, and off for a person who asks the system for less motion. */
export function readAnimation(): boolean {
  const stored = readStored(ANIMATION_STORAGE_KEY);
  if (stored === 'on') return true;
  if (stored === 'off') return false;
  return !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export interface Weather {
  wind: WindMode;
  setWind: (wind: WindMode) => void;
  /** The wind moves over the map as lines; it does not depend on where the wind is marked. */
  animation: boolean;
  setAnimation: (animation: boolean) => void;
  /** The pictures on the map; both can be on, the rain over the dryness. */
  layers: readonly WeatherLayer[];
  toggleLayer: (layer: WeatherLayer) => void;
  /** Switches layers on, those that are on staying on. */
  showLayers: (layers: readonly WeatherLayer[]) => void;
  /** The layers of the weather on the map of the calendar, as `month:fwi` or `day:rain`. */
  climate: readonly string[];
  toggleClimate: (id: string) => void;
}

export const WeatherContext = createContext<Weather | null>(null);

export function useWeatherState(): Weather {
  const value = useContext(WeatherContext);
  if (!value) throw new Error('useWeatherState needs a WeatherProvider above it');
  return value;
}
