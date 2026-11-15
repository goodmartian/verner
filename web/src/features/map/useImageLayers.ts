import type { ImageSource, Map as MaplibreMap } from 'maplibre-gl';
import { useEffect } from 'react';
import { withMap } from './withMap';

type Corner = [number, number];
type Corners = [Corner, Corner, Corner, Corner];

// what an image layer holds until its first picture is there
const BLANK =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';

/** A picture of the server laid on the map: shown while it has an address, taken off when it has none. */
export interface Picture {
  id: string;
  url: string | null;
  opacity: number | undefined;
}

/** The four corners the server gives (north-west, north-east, south-east, south-west) as a source wants them. */
export function cornersOf(coordinates: readonly (readonly number[])[]): Corners | null {
  const [a, b, c, d] = coordinates.map((corner): Corner => [corner[0] ?? 0, corner[1] ?? 0]);
  return a && b && c && d ? [a, b, c, d] : null;
}

/**
 * Pictures of one grid on the map, in the order given, the last on top, under the layer `before`. Each has its own layer
 * and source, `${prefix}-${id}`, which wait empty for an address; the address is swapped in as the hour or the layer changes.
 */
export function useImageLayers(
  map: MaplibreMap | null,
  prefix: string,
  corners: Corners | null,
  pictures: readonly Picture[],
  before: string | undefined,
) {
  const ids = pictures.map((picture) => picture.id).join(',');
  useEffect(() => {
    if (!map || !corners || !ids) return;
    const list = ids.split(',');
    for (const id of list) {
      map.addSource(`${prefix}-${id}`, { type: 'image', url: BLANK, coordinates: corners });
      map.addLayer(
        {
          id: `${prefix}-${id}`,
          type: 'raster',
          source: `${prefix}-${id}`,
          layout: { visibility: 'none' },
          paint: { 'raster-resampling': 'linear', 'raster-fade-duration': 0 },
        },
        before && map.getLayer(before) ? before : undefined,
      );
    }
    return () => {
      withMap(map, () => {
        for (const id of list) {
          map.removeLayer(`${prefix}-${id}`);
          map.removeSource(`${prefix}-${id}`);
        }
      });
    };
  }, [map, prefix, corners, ids, before]);

  useEffect(() => {
    if (!map || !corners) return;
    for (const { id, url, opacity } of pictures) {
      const source = map.getSource<ImageSource>(`${prefix}-${id}`);
      if (!source) continue;
      map.setLayoutProperty(`${prefix}-${id}`, 'visibility', url ? 'visible' : 'none');
      if (opacity !== undefined) map.setPaintProperty(`${prefix}-${id}`, 'raster-opacity', opacity);
      if (url) source.updateImage({ url });
    }
  }, [map, prefix, corners, pictures]);
}
