import type { GeoJSONSource, Map as MaplibreMap } from 'maplibre-gl';
import type { FeatureCollection, MultiPolygon, Polygon } from 'geojson';
import { useEffect } from 'react';
import { withMap } from './withMap';

const CELLS = 'calendar-cells';
const HEAT = 'calendar-heat';
const OUTLINE = 'calendar-outline';
const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

const cssColor = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** What the calendar draws: the satellites' cells of a month seen as dots, a month ahead as a heat surface. */
interface CalendarCells {
  kind: string;
  collection: FeatureCollection;
}

/** The calendar on the map: dots sized and coloured by detections, or a heat surface ahead, inside the area's outline. */
export function useCalendarLayers(
  map: MaplibreMap | null,
  cells: CalendarCells | null,
  outline: Polygon | MultiPolygon | null,
) {
  useEffect(() => {
    if (!map) return;
    // the two palest steps have tones of their own on the map: with the common ones the second and third steps run
    // together for a person with deuteranopia and in grey (CIELAB difference under 8); these keep every step apart
    const [f1, f2, f3, f4, f5] = [
      '--fire-map-1',
      '--fire-map-2',
      '--fire-3',
      '--fire-4',
      '--fire-5',
    ].map(cssColor);
    map.addSource(OUTLINE, { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: OUTLINE,
      type: 'line',
      source: OUTLINE,
      paint: {
        'line-color': cssColor('--c-ink'),
        'line-width': 1.5,
        'line-opacity': 0.5,
        'line-dasharray': [3, 2],
      },
    });
    map.addSource(HEAT, { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: HEAT,
      type: 'heatmap',
      source: HEAT,
      paint: {
        // the weight of a cell is its share of the busiest cell
        'heatmap-weight': ['get', 'w'],
        'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 4, 0.5, 7, 0.8, 9, 1],
        'heatmap-radius': ['interpolate', ['exponential', 2], ['zoom'], 4, 10, 7, 64, 9, 240],
        'heatmap-opacity': 0.85,
        'heatmap-color': [
          'interpolate',
          ['linear'],
          ['heatmap-density'],
          0,
          `${f1 ?? '#feeab4'}00`,
          0.15,
          f1 ?? '#feeab4',
          0.4,
          f2 ?? '#fec170',
          0.65,
          f3 ?? '#fd8d3c',
          0.85,
          f4 ?? '#f03b20',
          1,
          f5 ?? '#bd0026',
        ],
      },
    });
    map.addSource(CELLS, { type: 'geojson', data: EMPTY });
    map.addLayer({
      id: CELLS,
      type: 'circle',
      source: CELLS,
      paint: {
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['zoom'],
          5,
          ['max', 1.5, ['min', 14, ['*', 0.28, ['sqrt', ['get', 'v']]]]],
          9,
          ['max', 3, ['min', 40, ['*', 1.2, ['sqrt', ['get', 'v']]]]],
        ],
        'circle-color': [
          'interpolate',
          ['linear'],
          ['get', 'v'],
          1,
          f1 ?? '#feeab4',
          20,
          f2 ?? '#fec170',
          100,
          f3 ?? '#fd8d3c',
          300,
          f4 ?? '#f03b20',
          1000,
          f5 ?? '#bd0026',
        ],
        'circle-opacity': 0.8,
        'circle-stroke-color': cssColor('--c-halo'),
        'circle-stroke-width': 0.75,
      },
    });
    return () => {
      withMap(map, () => {
        for (const id of [CELLS, HEAT, OUTLINE]) {
          map.removeLayer(id);
          map.removeSource(id);
        }
      });
    };
  }, [map]);

  useEffect(() => {
    // a month ahead is a surface of heat, a month seen is its cells; each cell is a dot, the busiest on top
    const ahead = cells?.kind === 'forecast';
    const ordered: FeatureCollection | null = cells
      ? {
          ...cells.collection,
          features: [...cells.collection.features].sort(
            (a, b) => Number(a.properties?.v ?? 0) - Number(b.properties?.v ?? 0),
          ),
        }
      : null;
    void map?.getSource<GeoJSONSource>(HEAT)?.setData(ahead && ordered ? ordered : EMPTY);
    void map?.getSource<GeoJSONSource>(CELLS)?.setData(!ahead && ordered ? ordered : EMPTY);
  }, [map, cells]);

  useEffect(() => {
    void map
      ?.getSource<GeoJSONSource>(OUTLINE)
      ?.setData(outline ? { type: 'Feature', properties: {}, geometry: outline } : EMPTY);
  }, [map, outline]);
}
