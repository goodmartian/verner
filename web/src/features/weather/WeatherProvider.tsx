import { useMemo, useState, type ReactNode } from 'react';
import { writeStored } from '../../lib/storage';
import {
  ANIMATION_STORAGE_KEY,
  readAnimation,
  readWindMode,
  WeatherContext,
  WIND_STORAGE_KEY,
  type Weather,
  type WeatherLayer,
  type WindMode,
} from './context';

export function WeatherProvider({ children }: { children: ReactNode }) {
  const [wind, setWindState] = useState<WindMode>(readWindMode);
  const [animation, setAnimationState] = useState(readAnimation);
  const [layers, setLayers] = useState<readonly WeatherLayer[]>([]);
  const [climate, setClimate] = useState<readonly string[]>([]);

  const value = useMemo<Weather>(
    () => ({
      wind,
      // kept like the language
      setWind: (next) => {
        setWindState(next);
        writeStored(WIND_STORAGE_KEY, next);
      },
      animation,
      setAnimation: (next) => {
        setAnimationState(next);
        writeStored(ANIMATION_STORAGE_KEY, next ? 'on' : 'off');
      },
      layers,
      toggleLayer: (layer) => {
        setLayers((now) =>
          now.includes(layer) ? now.filter((item) => item !== layer) : [...now, layer],
        );
      },
      showLayers: (next) => {
        setLayers((now) => [...now, ...next.filter((layer) => !now.includes(layer))]);
      },
      climate,
      toggleClimate: (id) => {
        setClimate((now) => (now.includes(id) ? now.filter((item) => item !== id) : [...now, id]));
      },
    }),
    [wind, animation, layers, climate],
  );

  return <WeatherContext value={value}>{children}</WeatherContext>;
}
