import type { Feature, FeatureCollection } from 'geojson';
import type {
  ExpressionSpecification,
  LineLayerSpecification,
  GeoJSONSource,
  Map as MaplibreMap,
  MapMouseEvent,
} from 'maplibre-gl';
import { useEffect, useRef } from 'react';
import type { LngLat } from './draw/geometry';
import { withMap } from './withMap';

type Collection = FeatureCollection;

export interface FireLayerData {
  points: Collection;
  scar: Collection;
  core: Collection;
  detections: Collection;
  contours: Collection;
  access: Collection;
  accessStart: Collection;
  planLines: Collection;
  planZones: Collection;
  planPins: Collection;
  planHeads: Collection;
  /** Whose data it is; shown with the credits of the map. */
  credits: string | null;
  /** The crew whose lines are drawn heavier, the one the pointer is on in the plan window; 0 for none. */
  crewHi: number;
  /** The fire the pointer is on in the list; its dot gets the dark ring of the open one. */
  hovered: string | null;
}

export interface FireLayerHandlers {
  onSelect: (id: string) => void;
  /** Set while a mark is being placed: the next click on the map gives its position. */
  placing: boolean;
  onPlace: (position: LngLat) => void;
}

const EMPTY: Collection = { type: 'FeatureCollection', features: [] };
const NAMES = [
  'points',
  'scar',
  'core',
  'detections',
  'contours',
  'access',
  'accessStart',
  'planLines',
  'planZones',
  'planPins',
  'planHeads',
] as const;

type LinePaint = NonNullable<LineLayerSpecification['paint']>;

const DOT: ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['sqrt', ['get', 'frp']],
  1,
  0.25,
  3,
  0.5,
  7,
  0.8,
  14,
  1,
];

const css = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** The fires on the map: dots, burn scar, forecast fronts, the way in, and the work plan over them. */
export function useFireLayers(
  map: MaplibreMap | null,
  data: FireLayerData | null,
  handlers: FireLayerHandlers,
) {
  const latest = useRef(handlers);
  useEffect(() => {
    latest.current = handlers;
  });

  useEffect(() => {
    if (!map) return;
    const ink = css('--c-ink');
    const halo = css('--c-halo');
    const route = css('--c-route');
    // the way out and the place of safety are green, as on the maps of the fire services: the way in is blue
    const safe = css('--c-safe');
    const fire = [1, 2, 3, 4, 5].map((n) => css(`--fire-${String(n)}`));
    for (const name of NAMES) map.addSource(`fire-${name}`, { type: 'geojson', data: EMPTY });
    const source = (name: (typeof NAMES)[number]) => `fire-${name}`;
    map.addLayer({
      id: 'fire-scar-fill',
      type: 'fill',
      source: source('scar'),
      paint: { 'fill-color': fire[2] ?? ink, 'fill-opacity': 0.14 },
    });
    map.addLayer({
      id: 'fire-core-fill',
      type: 'fill',
      source: source('core'),
      paint: { 'fill-color': fire[3] ?? ink, 'fill-opacity': 0.32 },
    });
    map.addLayer({
      id: 'fire-contours-fill',
      type: 'fill',
      source: source('contours'),
      paint: {
        'fill-color': [
          'match',
          ['get', 'hours'],
          1,
          fire[3] ?? ink,
          3,
          fire[1] ?? ink,
          fire[0] ?? ink,
        ],
        'fill-opacity': 0.2,
      },
    });
    map.addLayer({
      id: 'fire-contours-line',
      type: 'line',
      source: source('contours'),
      paint: { 'line-color': fire[3] ?? ink, 'line-width': 1.5, 'line-dasharray': [2, 2] },
    });
    map.addLayer({
      id: 'fire-detections',
      type: 'circle',
      source: source('detections'),
      minzoom: 8,
      paint: {
        // the size follows the fire power: a weak pixel is a speck, a strong one keeps the full size
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['zoom'],
          8,
          ['*', 2, DOT],
          12,
          ['*', 4.5, DOT],
          15,
          ['*', 8, DOT],
        ],
        'circle-color': fire[4] ?? ink,
        'circle-opacity': ['case', ['get', 'now'], 0.9, 0.5],
      },
    });
    // a safety zone: diagonal hatching inside a dashed outline, as on a paper plan
    const hatch = document.createElement('canvas');
    hatch.width = 24;
    hatch.height = 24;
    const hatchContext = hatch.getContext('2d');
    if (hatchContext && !map.hasImage('zone-hatch')) {
      hatchContext.strokeStyle = safe;
      hatchContext.lineWidth = 2.5;
      hatchContext.lineCap = 'square';
      hatchContext.beginPath();
      for (const offset of [-24, 0, 24]) {
        hatchContext.moveTo(offset, 24);
        hatchContext.lineTo(offset + 24, 0);
      }
      hatchContext.stroke();
      map.addImage('zone-hatch', hatchContext.getImageData(0, 0, 24, 24), { pixelRatio: 2 });
    }
    map.addLayer({
      id: 'fire-zones',
      type: 'fill',
      source: source('planZones'),
      paint: { 'fill-pattern': 'zone-hatch', 'fill-opacity': 0.9 },
    });
    map.addLayer({
      id: 'fire-zones-line',
      type: 'line',
      source: source('planZones'),
      layout: { 'line-join': 'round' },
      paint: { 'line-color': safe, 'line-width': 1.5, 'line-dasharray': [3, 2] },
    });
    map.addLayer({
      id: 'fire-access',
      type: 'line',
      source: source('access'),
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': route,
        'line-width': 3,
        'line-dasharray': [
          'case',
          ['==', ['get', 'kind'], 'walk'],
          ['literal', [2, 2]],
          ['literal', [1, 0]],
        ],
      },
    });
    map.addLayer({
      id: 'fire-access-start',
      type: 'circle',
      source: source('accessStart'),
      paint: {
        'circle-radius': 5,
        'circle-color': route,
        'circle-stroke-color': halo,
        'circle-stroke-width': 2,
      },
    });
    const lines = (id: string, filter: ExpressionSpecification | undefined, paint: LinePaint) =>
      map.addLayer({
        id,
        type: 'line',
        source: source('planLines'),
        ...(filter ? { filter } : {}),
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint,
      });
    lines('fire-plan-case', undefined, { 'line-color': halo, 'line-width': 8 });
    lines('fire-plan-attack', ['==', ['get', 'kind'], 'attack'], {
      'line-color': route,
      'line-width': 4.5,
    });
    lines('fire-plan-blocked', ['==', ['get', 'kind'], 'blocked'], {
      'line-color': css('--c-field'),
      'line-width': 3.5,
      'line-dasharray': [1.5, 1.5],
    });
    lines('fire-plan-escape', ['==', ['get', 'kind'], 'escape'], {
      'line-color': safe,
      'line-width': 3.5,
      'line-dasharray': [2, 1.6],
    });
    lines('fire-plan-hi', ['==', ['get', 'crew'], 0], {
      'line-color': ink,
      'line-width': 7,
      'line-opacity': 0.35,
    });
    // arrowheads: an open chevron pointing east, its tip on the anchor, turned to the bearing of the way it sits on
    for (const [name, color] of [
      ['route-head', route],
      ['escape-head', safe],
    ] as const) {
      const arrow = document.createElement('canvas');
      arrow.width = 40;
      arrow.height = 40;
      const arrowContext = arrow.getContext('2d');
      if (!arrowContext) continue;
      arrowContext.lineJoin = 'round';
      arrowContext.lineCap = 'round';
      arrowContext.beginPath();
      arrowContext.moveTo(18, 8);
      arrowContext.lineTo(34, 20);
      arrowContext.lineTo(18, 32);
      arrowContext.strokeStyle = halo;
      arrowContext.lineWidth = 12;
      arrowContext.stroke();
      arrowContext.strokeStyle = color;
      arrowContext.lineWidth = 6;
      arrowContext.stroke();
      map.addImage(name, arrowContext.getImageData(0, 0, 40, 40), { pixelRatio: 2 });
    }
    map.addLayer({
      id: 'fire-plan-heads',
      type: 'symbol',
      source: source('planHeads'),
      layout: {
        'icon-image': ['case', ['==', ['get', 'kind'], 'escape'], 'escape-head', 'route-head'],
        'icon-rotate': ['-', ['get', 'b'], 90],
        'icon-rotation-alignment': 'map',
        'icon-anchor': 'center',
        'icon-offset': [-4, 0],
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
      },
    });
    map.addLayer({
      id: 'fire-plan-pins',
      type: 'circle',
      source: source('planPins'),
      paint: {
        'circle-radius': 7,
        'circle-color': route,
        'circle-stroke-color': halo,
        'circle-stroke-width': 3,
      },
    });
    map.addLayer({
      id: 'fire-points',
      type: 'circle',
      source: source('points'),
      maxzoom: 9,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'ha']], 8, 6, 120, 16],
        'circle-color': fire[3] ?? ink,
        'circle-opacity': 0.85,
        'circle-stroke-color': ['case', ['get', 'selected'], ink, halo],
        'circle-stroke-width': 2,
      },
    });

    const onFire = (event: MapMouseEvent & { features?: Feature[] }) => {
      const id = event.features?.[0]?.properties?.id as string | undefined;
      if (id && !latest.current.placing) latest.current.onSelect(id);
    };
    const onClick = (event: MapMouseEvent) => {
      if (latest.current.placing) latest.current.onPlace([event.lngLat.lng, event.lngLat.lat]);
    };
    const pointer = () => {
      map.getCanvas().style.cursor = 'pointer';
    };
    const normal = () => {
      map.getCanvas().style.cursor = latest.current.placing ? 'crosshair' : '';
    };
    map.on('click', 'fire-points', onFire);
    map.on('click', onClick);
    map.on('mouseenter', 'fire-points', pointer);
    map.on('mouseleave', 'fire-points', normal);
    return () => {
      map.off('click', 'fire-points', onFire);
      map.off('click', onClick);
      map.off('mouseenter', 'fire-points', pointer);
      map.off('mouseleave', 'fire-points', normal);
      withMap(map, () => {
        for (const id of [
          'fire-points',
          'fire-plan-pins',
          'fire-plan-heads',
          'fire-plan-hi',
          'fire-plan-escape',
          'fire-plan-blocked',
          'fire-plan-attack',
          'fire-plan-case',
          'fire-access-start',
          'fire-access',
          'fire-zones-line',
          'fire-zones',
          'fire-detections',
          'fire-contours-line',
          'fire-contours-fill',
          'fire-core-fill',
          'fire-scar-fill',
        ]) {
          map.removeLayer(id);
        }
        for (const name of NAMES) map.removeSource(`fire-${name}`);
      });
    };
  }, [map]);

  useEffect(() => {
    if (!map) return;
    for (const name of NAMES) {
      void map.getSource<GeoJSONSource>(`fire-${name}`)?.setData(data?.[name] ?? EMPTY);
    }
  }, [map, data]);

  const hovered = data?.hovered ?? null;
  useEffect(() => {
    if (!map?.getLayer('fire-points')) return;
    map.setPaintProperty('fire-points', 'circle-stroke-color', [
      'case',
      ['any', ['get', 'selected'], ['==', ['get', 'id'], hovered ?? '']],
      css('--c-ink'),
      css('--c-halo'),
    ]);
  }, [map, hovered]);

  const crewHi = data?.crewHi ?? 0;
  useEffect(() => {
    if (map?.getLayer('fire-plan-hi'))
      map.setFilter('fire-plan-hi', ['==', ['get', 'crew'], crewHi]);
  }, [map, crewHi]);

  // the map lists a source in its credits only while a layer draws it, so the credits get one that draws nothing
  const credits = data?.credits;
  useEffect(() => {
    if (!map || !credits) return;
    map.addSource('fire-credits', { type: 'geojson', data: EMPTY, attribution: credits });
    map.addLayer({ id: 'fire-credits', type: 'fill', source: 'fire-credits' });
    return () => {
      withMap(map, () => {
        map.removeLayer('fire-credits');
        map.removeSource('fire-credits');
      });
    };
  }, [map, credits]);

  // marks are placed with a cross for a cursor
  useEffect(() => {
    if (map && data) map.getCanvas().style.cursor = handlers.placing ? 'crosshair' : '';
  }, [map, data, handlers.placing]);
}
