import type { GeoJSONSource, Map as MaplibreMap } from 'maplibre-gl';
import { useEffect, useRef } from 'react';
import { tacticCollections } from './ai';
import { tacticOf, type Shape } from './shapes';
import { withMap } from '../withMap';

const SOURCES = ['tactic-shapes', 'tactic-heads', 'tactic-marks', 'tactic-names'] as const;
const LAYERS = [
  'tactic-zone',
  'tactic-zone-line',
  'tactic-case',
  'tactic-approach',
  'tactic-escape',
  'tactic-heads',
  'tactic-heads-escape',
  'tactic-marks',
  'tactic-names',
] as const;
const FADE_MS = 200;

const css = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function canvas(size: number, draw: (context: CanvasRenderingContext2D) => void): ImageData | null {
  const element = document.createElement('canvas');
  element.width = size;
  element.height = size;
  const context = element.getContext('2d');
  if (!context) return null;
  draw(context);
  return context.getImageData(0, 0, size, size);
}

/**
 * The tactical shapes on the map as the plan draws its own, whoever drew them: the way to the fire in the blue of the crews,
 * the way out of it dashed, a place of safety hatched inside a dashed outline with a shield. The meaning keeps its colour; whose
 * drawing it is shows in the caption.
 */
export function useTacticLayer(
  map: MaplibreMap | null,
  shapes: readonly Shape[],
  zoneName: string,
) {
  const seen = useRef(new Set<string>());

  useEffect(() => {
    if (!map) return;
    const route = css('--c-route');
    const safe = css('--c-safe');
    const halo = css('--c-halo');
    // the way in is blue; the way out and the place of safety are green
    const ink = css('--c-ink');
    const empty = { type: 'FeatureCollection' as const, features: [] };
    for (const name of SOURCES)
      map.addSource(name, { type: 'geojson', data: empty, promoteId: 'id' });
    const hatch = canvas(24, (context) => {
      context.strokeStyle = safe;
      context.lineWidth = 2.5;
      context.lineCap = 'square';
      context.beginPath();
      for (const offset of [-24, 0, 24]) {
        context.moveTo(offset, 24);
        context.lineTo(offset + 24, 0);
      }
      context.stroke();
    });
    if (hatch) map.addImage('tactic-hatch', hatch, { pixelRatio: 2 });
    for (const [name, color] of [
      ['tactic-head', route],
      ['tactic-head-escape', safe],
    ] as const) {
      const head = canvas(40, (context) => {
        context.lineJoin = 'round';
        context.lineCap = 'round';
        context.beginPath();
        context.moveTo(18, 8);
        context.lineTo(34, 20);
        context.lineTo(18, 32);
        context.strokeStyle = halo;
        context.lineWidth = 12;
        context.stroke();
        context.strokeStyle = color;
        context.lineWidth = 6;
        context.stroke();
      });
      if (head) map.addImage(name, head, { pixelRatio: 2 });
    }
    const shield = canvas(40, (context) => {
      context.beginPath();
      context.moveTo(20, 4);
      context.lineTo(34, 9);
      context.lineTo(34, 21);
      context.quadraticCurveTo(34, 31, 20, 37);
      context.quadraticCurveTo(6, 31, 6, 21);
      context.lineTo(6, 9);
      context.closePath();
      context.lineJoin = 'round';
      context.strokeStyle = halo;
      context.lineWidth = 7;
      context.stroke();
      context.fillStyle = safe;
      context.fill();
    });
    if (shield) map.addImage('tactic-shield', shield, { pixelRatio: 2 });

    const state = (name: string) => ['boolean', ['feature-state', name], false];
    // what the assistant drew comes in with a fade; what the person draws is there at once
    const fade = ['case', ['all', ['get', 'ai'], ['!', state('shown')]], 0, 1];
    const transition = { duration: FADE_MS, delay: 0 };
    const tactic = (name: string) => ['==', ['get', 'tactic'], name];
    const line = ['!=', ['geometry-type'], 'Polygon'];
    map.addLayer({
      id: 'tactic-zone',
      type: 'fill',
      source: 'tactic-shapes',
      filter: ['all', ['==', ['geometry-type'], 'Polygon'], tactic('safe')] as never,
      paint: {
        'fill-pattern': 'tactic-hatch',
        'fill-opacity': ['*', 0.9, fade] as never,
        'fill-opacity-transition': transition,
      },
    });
    map.addLayer({
      id: 'tactic-zone-line',
      type: 'line',
      source: 'tactic-shapes',
      filter: ['all', ['==', ['geometry-type'], 'Polygon'], tactic('safe')] as never,
      layout: { 'line-join': 'round' },
      paint: {
        'line-color': safe,
        'line-width': ['+', 1.5, ['case', state('hover'), 1.5, 0]] as never,
        'line-dasharray': [3, 2],
        'line-opacity': fade as never,
        'line-opacity-transition': transition,
      },
    });
    const ways = ['any', tactic('approach'), tactic('escape')];
    map.addLayer({
      id: 'tactic-case',
      type: 'line',
      source: 'tactic-shapes',
      filter: ['all', line, ways] as never,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': halo,
        'line-width': ['+', 8, ['case', state('hover'), 2, 0]] as never,
        'line-opacity': fade as never,
        'line-opacity-transition': transition,
      },
    });
    map.addLayer({
      id: 'tactic-approach',
      type: 'line',
      source: 'tactic-shapes',
      filter: ['all', line, tactic('approach')] as never,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': route,
        'line-width': ['+', 4.5, ['case', state('hover'), 1.5, 0]] as never,
        'line-opacity': fade as never,
        'line-opacity-transition': transition,
      },
    });
    map.addLayer({
      id: 'tactic-escape',
      type: 'line',
      source: 'tactic-shapes',
      filter: ['all', line, tactic('escape')] as never,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': safe,
        'line-width': ['+', 3.5, ['case', state('hover'), 1.5, 0]] as never,
        'line-dasharray': [2, 1.6],
        'line-opacity': fade as never,
        'line-opacity-transition': transition,
      },
    });
    for (const [id, image, way] of [
      ['tactic-heads', 'tactic-head', 'approach'],
      ['tactic-heads-escape', 'tactic-head-escape', 'escape'],
    ] as const) {
      map.addLayer({
        id,
        type: 'symbol',
        source: 'tactic-heads',
        filter: tactic(way) as never,
        layout: {
          'icon-image': image,
          'icon-rotate': ['-', ['get', 'b'], 90],
          'icon-rotation-alignment': 'map',
          'icon-anchor': 'center',
          'icon-offset': [-4, 0],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
        },
        paint: { 'icon-opacity': fade as never, 'icon-opacity-transition': transition },
      });
    }
    map.addLayer({
      id: 'tactic-marks',
      type: 'symbol',
      source: 'tactic-marks',
      layout: { 'icon-image': 'tactic-shield', 'icon-size': 0.6, 'icon-allow-overlap': true },
      paint: { 'icon-opacity': fade as never, 'icon-opacity-transition': transition },
    });
    // the name of a zone of the person's own: over its edge, never on its hatching
    map.addLayer({
      id: 'tactic-names',
      type: 'symbol',
      source: 'tactic-names',
      layout: {
        'text-field': ['get', 'text'],
        'text-font': ['Noto Sans Bold'],
        'text-size': 12,
        'text-variable-anchor': ['bottom', 'top', 'left', 'right'],
        'text-radial-offset': 0.5,
        'text-allow-overlap': false,
      },
      paint: { 'text-color': ink, 'text-halo-color': halo, 'text-halo-width': 2 },
    });
    const done = seen.current;
    return () => {
      withMap(map, () => {
        for (const id of LAYERS) if (map.getLayer(id)) map.removeLayer(id);
        for (const name of SOURCES) if (map.getSource(name)) map.removeSource(name);
        for (const id of ['tactic-hatch', 'tactic-head', 'tactic-head-escape', 'tactic-shield']) {
          if (map.hasImage(id)) map.removeImage(id);
        }
      });
      done.clear();
    };
  }, [map]);

  useEffect(() => {
    if (!map) return;
    const collections = tacticCollections(shapes, zoneName);
    const data = {
      'tactic-shapes': collections.shapes,
      'tactic-heads': collections.heads,
      'tactic-marks': collections.marks,
      'tactic-names': collections.names,
    };
    for (const name of SOURCES) void map.getSource<GeoJSONSource>(name)?.setData(data[name]);
    const ids = new Set(
      shapes.flatMap((shape) =>
        shape.source === 'ai' && shape.id && tacticOf(shape) ? [shape.id] : [],
      ),
    );
    const fresh = [...ids].filter((id) => !seen.current.has(id));
    for (const id of [...seen.current].filter((old) => !ids.has(old))) {
      for (const name of SOURCES) map.removeFeatureState({ source: name, id });
      seen.current.delete(id);
    }
    for (const id of fresh) seen.current.add(id);
    const frame = requestAnimationFrame(() => {
      for (const id of fresh) {
        for (const name of SOURCES) map.setFeatureState({ source: name, id }, { shown: true });
      }
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [map, shapes, zoneName]);
}
