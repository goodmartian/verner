import type { FeatureCollection } from 'geojson';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useEffect } from 'react';
import { withMap } from './withMap';

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

/** The map lists a source in its credits only while a layer draws it, so the credits get one that draws nothing. */
export function useMapCredits(map: MaplibreMap | null, id: string, credits: string | null) {
  useEffect(() => {
    if (!map || !credits) return;
    map.addSource(id, { type: 'geojson', data: EMPTY, attribution: credits });
    map.addLayer({ id, type: 'fill', source: id });
    return () => {
      withMap(map, () => {
        map.removeLayer(id);
        map.removeSource(id);
      });
    };
  }, [map, id, credits]);
}
