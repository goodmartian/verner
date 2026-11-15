import type { Map as MaplibreMap } from 'maplibre-gl';
import { useEffect } from 'react';
import { withMap } from './withMap';

interface Cover {
  /** The grid as a picture. */
  image: string;
  /** West, south, east, north. */
  bbox: readonly number[];
}

/** The vegetation around the open fire, laid under the fire's own layers while the card is on. */
export function useCoverLayer(map: MaplibreMap | null, cover: Cover | null, on: boolean) {
  useEffect(() => {
    if (!map || !cover || !on) return;
    const [w = 0, s = 0, e = 0, n = 0] = cover.bbox;
    map.addSource('fire-cover', {
      type: 'image',
      url: cover.image,
      coordinates: [
        [w, n],
        [e, n],
        [e, s],
        [w, s],
      ],
    });
    map.addLayer(
      {
        id: 'fire-cover',
        type: 'raster',
        source: 'fire-cover',
        paint: { 'raster-opacity': 0.55, 'raster-resampling': 'nearest' },
      },
      map.getLayer('fire-scar-fill') ? 'fire-scar-fill' : undefined,
    );
    return () => {
      withMap(map, () => {
        if (map.getLayer('fire-cover')) map.removeLayer('fire-cover');
        if (map.getSource('fire-cover')) map.removeSource('fire-cover');
      });
    };
  }, [map, cover, on]);
}
