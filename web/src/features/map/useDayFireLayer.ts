import type { FeatureCollection } from 'geojson';
import type { GeoJSONSource, Map as MaplibreMap, MapMouseEvent } from 'maplibre-gl';
import { useEffect, useRef } from 'react';
import { withMap } from './withMap';

const ID = 'day-fires';
const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

const css = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** The clusters of fires of the picked day as dots sized by their detections; the open one has a dark ring, a press opens one. */
export function useDayFireLayer(
  map: MaplibreMap | null,
  clusters: FeatureCollection | null,
  selected: string | null,
  onSelect: (id: string) => void,
) {
  const latest = useRef(onSelect);
  useEffect(() => {
    latest.current = onSelect;
  });

  useEffect(() => {
    if (!map) return;
    map.addSource(ID, { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: ID,
      type: 'circle',
      source: ID,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'detections']], 1, 5, 20, 14],
        'circle-color': css('--fire-3'),
        'circle-opacity': 0.85,
        'circle-stroke-color': css('--c-halo'),
        'circle-stroke-width': 2,
      },
    });
    const press = (event: MapMouseEvent & { features?: { properties: { id?: unknown } }[] }) => {
      const id = event.features?.[0]?.properties.id;
      if (typeof id === 'string') latest.current(id);
    };
    const pointer = () => {
      map.getCanvas().style.cursor = 'pointer';
    };
    const plain = () => {
      map.getCanvas().style.cursor = '';
    };
    map.on('click', ID, press);
    map.on('mouseenter', ID, pointer);
    map.on('mouseleave', ID, plain);
    return () => {
      map.off('click', ID, press);
      map.off('mouseenter', ID, pointer);
      map.off('mouseleave', ID, plain);
      withMap(map, () => {
        map.removeLayer(ID);
        map.removeSource(ID);
      });
    };
  }, [map]);

  useEffect(() => {
    if (!map?.getSource(ID)) return;
    void map.getSource<GeoJSONSource>(ID)?.setData(clusters ?? EMPTY);
  }, [map, clusters]);

  useEffect(() => {
    if (!map?.getLayer(ID)) return;
    map.setPaintProperty(ID, 'circle-stroke-color', [
      'case',
      ['==', ['get', 'id'], selected ?? ''],
      css('--c-ink'),
      css('--c-halo'),
    ]);
    map.setPaintProperty(ID, 'circle-stroke-width', [
      'case',
      ['==', ['get', 'id'], selected ?? ''],
      3,
      2,
    ]);
  }, [map, selected]);
}
