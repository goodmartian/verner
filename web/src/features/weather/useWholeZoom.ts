import type { Map as MaplibreMap } from 'maplibre-gl';
import { useCallback, useSyncExternalStore } from 'react';

const OVERVIEW = 5;

/** The zoom of the map rounded to a whole number; it changes only when the map has settled on another one. */
export function useWholeZoom(map: MaplibreMap | null): number {
  const subscribe = useCallback(
    (notify: () => void) => {
      map?.on('zoomend', notify);
      return () => {
        map?.off('zoomend', notify);
      };
    },
    [map],
  );
  return useSyncExternalStore(subscribe, () => (map ? Math.round(map.getZoom()) : OVERVIEW));
}
