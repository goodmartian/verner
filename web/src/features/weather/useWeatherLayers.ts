import type { FeatureCollection } from 'geojson';
import type { GeoJSONSource, Map as MaplibreMap } from 'maplibre-gl';
import { useEffect, useMemo } from 'react';
import type { GridBounds, WeatherLegend, WindPoints } from '../../api/types';
import { cornersOf, useImageLayers, type Picture } from '../map/useImageLayers';
import { useMapCredits } from '../map/useMapCredits';
import type { WeatherLayer } from './context';
import { withMap } from '../map/withMap';

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };
// the dryness lies under the rain
const PICTURES = ['dryness', 'rain'] as const satisfies readonly WeatherLayer[];
// the weather goes under the drawings, the person's and the assistant's, which come before the fires among the layers: a picture
// of the dryness over a drawing would grey it out
const UNDER = 'sketch-fill';

const css = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// the width of a speed written beside its arrow, and the space kept from the tools below
const LABEL_W = 96;
const EDGE = 8;

function keepClear(map: MaplibreMap, fires: FeatureCollection): FeatureCollection {
  const { clientWidth: width, clientHeight: height } = map.getContainer();
  const tools =
    Number.parseFloat(getComputedStyle(map.getContainer()).getPropertyValue('--tools-h')) || 0;
  return {
    ...fires,
    features: fires.features.flatMap((feature) => {
      if (feature.geometry.type !== 'Point') return [feature];
      const [lng, lat] = feature.geometry.coordinates;
      if (lng === undefined || lat === undefined) return [feature];
      const at = map.project([lng, lat]);
      if (at.x < EDGE || at.y < EDGE || at.y > height - tools - EDGE || at.x > width - EDGE)
        return [];
      if (at.x <= width - LABEL_W) return [feature];
      return [{ ...feature, properties: { ...feature.properties, label: '' } }];
    }),
  };
}

export interface WeatherLayersState {
  bounds: GridBounds | undefined;
  legend: WeatherLegend | undefined;
  /** The pictures asked for. */
  layers: readonly WeatherLayer[];
  /** The hour the pictures are for; null when the data has no such hour. */
  hour: string | null;
  /** The arrows over the whole map, when they are asked for. */
  wind: WindPoints | null;
  /** The arrow and the speed at each fire, when they are asked for. */
  fires: FeatureCollection | null;
  /** The credits of the data in use, for the (i) of the map. */
  credits: string | null;
}

/** The weather on the map: the arrows of the wind, the pictures of the rain and the dryness, and the credits. */
export function useWeatherLayers(
  map: MaplibreMap | null,
  { bounds, legend, layers, hour, wind, fires, credits }: WeatherLayersState,
) {
  // the arrows are small, white, drawn into the colour of their band by the layer
  useEffect(() => {
    if (!map) return;
    const arrow = document.createElement('canvas');
    arrow.width = 48;
    arrow.height = 48;
    const context = arrow.getContext('2d');
    if (!context) return;
    context.fillStyle = '#fff';
    context.beginPath();
    context.moveTo(24, 4);
    context.lineTo(38, 24);
    context.lineTo(28, 24);
    context.lineTo(28, 44);
    context.lineTo(20, 44);
    context.lineTo(20, 24);
    context.lineTo(10, 24);
    context.closePath();
    context.fill();
    map.addImage('wind-arrow', context.getImageData(0, 0, 48, 48), { sdf: true, pixelRatio: 2 });
    map.addSource('weather-wind', { type: 'geojson', data: EMPTY });
    map.addLayer(
      {
        id: 'weather-wind',
        type: 'symbol',
        source: 'weather-wind',
        layout: {
          visibility: 'none',
          'icon-image': 'wind-arrow',
          // the arrow points where the wind goes: the opposite of where it comes from
          'icon-rotate': ['+', ['get', 'from_deg'], 180],
          'icon-rotation-alignment': 'map',
          'icon-size': ['interpolate', ['linear'], ['zoom'], 3, 0.7, 6, 0.85, 9, 1.05],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
        },
        paint: {
          'icon-color': ['get', 'color'],
          'icon-halo-color': css('--c-ink'),
          'icon-halo-width': 1,
        },
      },
      map.getLayer(UNDER) ? UNDER : undefined,
    );
    // at the fires: the arrow close to the dot and the speed beside it; where they would cover a name of a place or each
    // other the speed goes, then the arrow; the stronger wind keeps its place
    map.addSource('weather-fires', { type: 'geojson', data: EMPTY });
    map.addLayer(
      {
        id: 'weather-fires',
        type: 'symbol',
        source: 'weather-fires',
        layout: {
          'icon-image': 'wind-arrow',
          'icon-rotate': ['get', 'to'],
          'icon-rotation-alignment': 'map',
          'icon-size': 0.9,
          'icon-padding': 2,
          'text-field': ['get', 'label'],
          'text-font': ['Noto Sans Bold'],
          'text-size': 12,
          'text-anchor': 'left',
          'text-offset': [2.1, -1.2],
          'text-padding': 2,
          'text-optional': true,
          'symbol-sort-key': ['-', 0, ['get', 'speed']],
        },
        paint: {
          'icon-color': ['get', 'color'],
          'icon-halo-color': css('--c-halo'),
          'icon-halo-width': 2,
          // the arrow sits up and to the right of the dot; the translate is not turned with the arrow
          'icon-translate': [16, -14],
          'text-color': css('--c-ink'),
          'text-halo-color': css('--c-halo'),
          'text-halo-width': 1.5,
        },
      },
      // no layer below which: the marks of the wind stand over the outline and the dots of the fire, which would dim them
    );
    return () => {
      withMap(map, () => {
        map.removeLayer('weather-fires');
        map.removeSource('weather-fires');
        map.removeLayer('weather-wind');
        map.removeSource('weather-wind');
        map.removeImage('wind-arrow');
      });
    };
  }, [map]);

  // a mark does not go under the tools at the foot of the map, and a speed does not run past the right edge: it waits until the map is moved
  useEffect(() => {
    const source = map?.getSource<GeoJSONSource>('weather-fires');
    if (!map || !source) return;
    const show = () => {
      void source.setData(fires ? keepClear(map, fires) : EMPTY);
    };
    show();
    map.on('moveend', show);
    return () => {
      map.off('moveend', show);
    };
  }, [map, fires]);

  useEffect(() => {
    if (!map?.getSource('weather-wind')) return;
    void map.getSource<GeoJSONSource>('weather-wind')?.setData(wind ?? EMPTY);
    map.setLayoutProperty('weather-wind', 'visibility', wind ? 'visible' : 'none');
  }, [map, wind]);

  // the pictures of the rain and the dryness, from the server, for the hour on screen
  const corners = useMemo(() => (bounds ? cornersOf(bounds.coordinates) : null), [bounds]);
  const pictures = useMemo(
    () =>
      PICTURES.map((id): Picture => {
        const url = new URL('/api/weather/grid.png', window.location.origin);
        if (hour) url.search = new URLSearchParams({ layer: id, time: hour }).toString();
        return {
          id,
          url: hour && layers.includes(id) ? url.href : null,
          opacity: legend?.layers.find((layer) => layer.layer === id)?.opacity,
        };
      }),
    [legend, layers, hour],
  );
  useImageLayers(map, 'weather', corners, pictures, 'weather-wind');

  useMapCredits(map, 'weather-credits', credits);
}
