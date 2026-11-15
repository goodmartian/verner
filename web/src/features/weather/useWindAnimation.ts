import type { Map as MaplibreMap } from 'maplibre-gl';
import { useEffect, useRef } from 'react';
import type { GridBounds } from '../../api/types';
import { WindLayer, type WindField } from './WindLayer';
import { fieldAddress } from './windMath';
import { withMap } from '../map/withMap';

/** The field of the wind of the server: what its picture covers, and the wind that a value of 0 and of 255 stand for. */
export function fieldOf(bounds: GridBounds): WindField {
  const [w = 0, s = 0, e = 0, n = 0] = bounds.bounds;
  const info = bounds.wind_field;
  return { bounds: [w, s, e, n], min: [info.u_min, info.v_min], max: [info.u_max, info.v_max] };
}

interface Options {
  /** The animation is on, and there is a field and an hour for it. */
  enabled: boolean;
  bounds: GridBounds | undefined;
  /** The hour of the field; null when the data has none. */
  hour: string | null;
  /** The base map is light or dark: the lines are the other. */
  tone: 'dark' | 'light';
}

/** The wind as moving lines over the map, under the marks of the fires. */
export function useWindAnimation(
  map: MaplibreMap | null,
  { enabled, bounds, hour, tone }: Options,
) {
  const layer = useRef<WindLayer | null>(null);
  const on = enabled && bounds !== undefined && hour !== null;

  useEffect(() => {
    if (!map || !on) return;
    const added = new WindLayer();
    map.addLayer(added, map.getLayer('weather-wind') ? 'weather-wind' : undefined);
    layer.current = added;
    return () => {
      layer.current = null;
      withMap(map, () => {
        if (map.getLayer(added.id)) map.removeLayer(added.id);
      });
    };
  }, [map, on]);

  useEffect(() => {
    layer.current?.setTone(tone);
  }, [map, tone, on]);

  useEffect(() => {
    if (!on) return;
    // a field that cannot be had leaves the one on screen as it is
    void layer.current?.setField(fieldOf(bounds), fieldAddress(hour)).catch(() => undefined);
  }, [map, on, bounds, hour]);
}
