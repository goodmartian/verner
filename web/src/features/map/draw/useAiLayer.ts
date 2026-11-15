import type { Map as MaplibreMap, MapGeoJSONFeature, MapMouseEvent } from 'maplibre-gl';
import type { GeoJSONSource } from 'maplibre-gl';
import { useCallback, useEffect, useRef, useState } from 'react';
import { aiCollections } from './ai';
import type { LngLat } from './geometry';
import type { Shape } from './shapes';
import { withMap } from '../withMap';

const SOURCES = ['ai-shapes', 'ai-labels', 'ai-heads'] as const;
const LAYERS = [
  'ai-fill',
  'ai-case',
  'ai-line',
  'ai-hit',
  'ai-hitfill',
  'ai-points',
  'ai-heads',
  'ai-labels-area',
  'ai-labels-line',
  'ai-labels-point',
] as const;
// what a click on the map is left to when it is on one of these: a fire
const FIRES = ['fire-points'];
// the layers a pointer can hit
const HIT = ['ai-points', 'ai-hit', 'ai-hitfill'];
const FADE_MS = 200;

const css = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** An open chevron pointing east, its tip at the right, with a white edge: the end of a way. */
function chevron(ink: string, halo: string): ImageData | null {
  const canvas = document.createElement('canvas');
  canvas.width = 40;
  canvas.height = 40;
  const context = canvas.getContext('2d');
  if (!context) return null;
  context.lineJoin = 'round';
  context.lineCap = 'round';
  context.beginPath();
  context.moveTo(12, 8);
  context.lineTo(30, 20);
  context.lineTo(12, 32);
  context.strokeStyle = halo;
  context.lineWidth = 11;
  context.stroke();
  context.strokeStyle = ink;
  context.lineWidth = 5.5;
  context.stroke();
  return context.getImageData(0, 0, 40, 40);
}

/** A four-pointed spark in the violet: it stands before the caption of everything the assistant drew. */
function spark(ink: string): ImageData | null {
  const canvas = document.createElement('canvas');
  canvas.width = 24;
  canvas.height = 24;
  const context = canvas.getContext('2d');
  if (!context) return null;
  context.beginPath();
  context.moveTo(12, 1);
  context.quadraticCurveTo(13, 11, 23, 12);
  context.quadraticCurveTo(13, 13, 12, 23);
  context.quadraticCurveTo(11, 13, 1, 12);
  context.quadraticCurveTo(11, 11, 12, 1);
  context.fillStyle = ink;
  context.fill();
  return context.getImageData(0, 0, 24, 24);
}

/** A shape of the assistant the person has pressed, and where. */
export interface Picked {
  id: string;
  at: LngLat;
}

/**
 * The layers of the assistant's drawings: violet, apart from the person's own, which stay black. Each shape comes in with a short
 * fade (the state `shown` of its feature), so that what is drawn while the answer streams does not blink; the pointer over a shape
 * lights it, a press picks it.
 */
export function useAiLayer(map: MaplibreMap | null, shapes: readonly Shape[], active: boolean) {
  const [picked, setPicked] = useState<Picked | null>(null);
  const seen = useRef(new Set<string>());
  const hovered = useRef<string | null>(null);

  // the layers
  useEffect(() => {
    if (!map) return;
    const ink = css('--c-ai');
    const halo = css('--c-halo');
    const empty = { type: 'FeatureCollection' as const, features: [] };
    for (const name of SOURCES) {
      map.addSource(name, { type: 'geojson', data: empty, promoteId: 'id' });
    }
    const head = chevron(ink, halo);
    if (head) map.addImage('ai-head', head, { pixelRatio: 2 });
    const star = spark(ink);
    if (star) map.addImage('ai-spark', star, { pixelRatio: 2 });
    const state = (name: string) => ['boolean', ['feature-state', name], false];
    const shown = ['case', state('shown'), 1, 0];
    const fade = { duration: FADE_MS, delay: 0 };
    const isPolygon = ['==', ['geometry-type'], 'Polygon'];
    const plain = ['!', ['has', 'tactic']];
    const notPoint = ['!=', ['geometry-type'], 'Point'];
    map.addLayer({
      id: 'ai-fill',
      type: 'fill',
      source: 'ai-shapes',
      filter: ['all', isPolygon, plain] as never,
      paint: {
        'fill-color': ink,
        'fill-opacity': ['*', shown, ['case', state('hover'), 0.2, 0.12]] as never,
        'fill-opacity-transition': fade,
      },
    });
    map.addLayer({
      id: 'ai-case',
      type: 'line',
      source: 'ai-shapes',
      filter: ['all', notPoint, plain] as never,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': halo,
        'line-width': ['+', ['case', isPolygon, 5, 6], ['case', state('hover'), 2, 0]] as never,
        'line-opacity': shown as never,
        'line-opacity-transition': fade,
      },
    });
    map.addLayer({
      id: 'ai-line',
      type: 'line',
      source: 'ai-shapes',
      filter: ['all', notPoint, plain] as never,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': ink,
        'line-width': ['+', ['case', isPolygon, 2, 2.5], ['case', state('hover'), 1.5, 0]] as never,
        'line-opacity': shown as never,
        'line-opacity-transition': fade,
      },
    });
    // a wide line nobody sees, so that a thin one is easy to hit
    map.addLayer({
      id: 'ai-hit',
      type: 'line',
      source: 'ai-shapes',
      filter: notPoint as never,
      paint: { 'line-color': ink, 'line-width': 16, 'line-opacity': 0 },
    });
    // the same for a surface: what the person presses inside an area is the area
    map.addLayer({
      id: 'ai-hitfill',
      type: 'fill',
      source: 'ai-shapes',
      filter: isPolygon as never,
      paint: { 'fill-color': ink, 'fill-opacity': 0 },
    });
    map.addLayer({
      id: 'ai-points',
      type: 'circle',
      source: 'ai-shapes',
      filter: ['all', ['==', ['geometry-type'], 'Point'], plain] as never,
      paint: {
        'circle-radius': ['case', state('hover'), 8, 6] as never,
        'circle-color': ink,
        'circle-stroke-color': halo,
        'circle-stroke-width': 2,
        'circle-opacity': shown as never,
        'circle-stroke-opacity': shown as never,
        'circle-opacity-transition': fade,
        'circle-stroke-opacity-transition': fade,
      },
    });
    map.addLayer({
      id: 'ai-heads',
      type: 'symbol',
      source: 'ai-heads',
      layout: {
        'icon-image': 'ai-head',
        'icon-rotate': ['-', ['get', 'b'], 90],
        'icon-rotation-alignment': 'map',
        'icon-anchor': 'center',
        'icon-offset': [-3, 0],
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
      },
      paint: { 'icon-opacity': shown as never, 'icon-opacity-transition': fade },
    });
    // the caption stands beside the shape: over an area, to the side of the start of a way, under a point; where it would
    // cover another caption or the shape of another it gives way, the variable anchors being tried in turn
    for (const [id, kind, anchors, offset] of [
      ['ai-labels-area', 'area', ['bottom', 'top'], 0.4],
      ['ai-labels-line', 'line', ['left', 'right', 'top', 'bottom'], 0.9],
      ['ai-labels-point', 'point', ['top', 'bottom', 'left', 'right'], 0.9],
    ] as const) {
      map.addLayer({
        id,
        type: 'symbol',
        source: 'ai-labels',
        filter: ['==', ['get', 'kind'], kind],
        layout: {
          'text-field': [
            'format',
            ['image', 'ai-spark'],
            {},
            ' ',
            {},
            ['get', 'label'],
            {},
          ] as never,
          'text-font': ['Noto Sans Bold'],
          'text-size': 12,
          'text-max-width': 9,
          'text-variable-anchor': [...anchors],
          'text-radial-offset': offset,
          'text-allow-overlap': false,
        },
        paint: {
          'text-color': ink,
          'text-halo-color': halo,
          'text-halo-width': 2,
          'text-opacity': shown as never,
          'text-opacity-transition': fade,
        },
      });
    }
    const done = seen.current;
    return () => {
      withMap(map, () => {
        for (const id of LAYERS) if (map.getLayer(id)) map.removeLayer(id);
        for (const name of SOURCES) if (map.getSource(name)) map.removeSource(name);
        for (const image of ['ai-head', 'ai-spark'])
          if (map.hasImage(image)) map.removeImage(image);
      });
      done.clear();
      hovered.current = null;
    };
  }, [map]);

  // the shapes: new ones fade in, gone ones leave their state behind them no longer
  useEffect(() => {
    if (!map) return;
    const collections = aiCollections(shapes);
    const data = {
      'ai-shapes': collections.shapes,
      'ai-labels': collections.labels,
      'ai-heads': collections.heads,
    };
    for (const name of SOURCES) void map.getSource<GeoJSONSource>(name)?.setData(data[name]);
    const ids = new Set(
      shapes.flatMap((shape) => (shape.source === 'ai' && shape.id ? [shape.id] : [])),
    );
    const fresh = [...ids].filter((id) => !seen.current.has(id));
    for (const id of [...seen.current].filter((old) => !ids.has(old))) {
      for (const name of SOURCES) map.removeFeatureState({ source: name, id });
      seen.current.delete(id);
    }
    for (const id of fresh) seen.current.add(id);
    // the state is set a frame after the data, so that the first thing drawn is the faded-out shape
    const frame = requestAnimationFrame(() => {
      for (const id of fresh) {
        for (const name of SOURCES) map.setFeatureState({ source: name, id }, { shown: true });
      }
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [map, shapes]);

  // the pointer lights a shape, a press picks it
  useEffect(() => {
    if (!map || !active) return;
    const hit = (event: MapMouseEvent): MapGeoJSONFeature | undefined => {
      const layers = HIT.filter((id) => map.getLayer(id));
      return layers.length > 0 ? map.queryRenderedFeatures(event.point, { layers })[0] : undefined;
    };
    const light = (id: string | null) => {
      if (hovered.current === id) return;
      // the tactical shapes are drawn from a source of their own, the same name in both
      for (const source of ['ai-shapes', 'tactic-shapes']) {
        if (hovered.current) map.setFeatureState({ source, id: hovered.current }, { hover: false });
        if (id) map.setFeatureState({ source, id }, { hover: true });
      }
      hovered.current = id;
      map.getCanvas().style.cursor = id ? 'pointer' : '';
    };
    const onMove = (event: MapMouseEvent) => {
      const id = hit(event)?.properties.id as string | undefined;
      light(id ?? null);
    };
    const onClick = (event: MapMouseEvent) => {
      const onFire = map.queryRenderedFeatures(event.point, {
        layers: FIRES.filter((id) => map.getLayer(id)),
      });
      const id = hit(event)?.properties.id as string | undefined;
      if (id && onFire.length === 0) setPicked({ id, at: [event.lngLat.lng, event.lngLat.lat] });
      else setPicked(null);
    };
    map.on('mousemove', onMove);
    map.on('click', onClick);
    return () => {
      map.off('mousemove', onMove);
      map.off('click', onClick);
      light(null);
    };
  }, [map, active]);

  // a shape that is gone cannot stay picked
  const gone = picked !== null && !shapes.some((shape) => shape.id === picked.id);
  const dismiss = useCallback(() => {
    setPicked(null);
  }, []);
  return { picked: gone ? null : picked, dismiss };
}
