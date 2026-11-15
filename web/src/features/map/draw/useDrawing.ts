import type { GeoJSONSource, Map as MaplibreMap, MapMouseEvent } from 'maplibre-gl';
import { Marker } from 'maplibre-gl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useI18n } from '../../../i18n/context';
import { LOCALES } from '../../../i18n/lang';
import {
  createDrawing,
  type Drawing,
  type DrawState,
  type MapEvent,
  type MapLike,
  type Tool,
} from './controller';
import { distanceM, toLength, type LngLat } from './geometry';
import {
  isAi,
  isMark,
  tacticOf,
  toFeature,
  type MarkKind,
  type Shape,
  type ShapeKind,
} from './shapes';
import { useAiLayer } from './useAiLayer';
import { useTacticLayer } from './useTacticLayer';
import type { DrawShape } from '../../../api/types';
import styles from './Ruler.module.css';
import { withMap } from '../withMap';

const SOURCE = 'sketch';
const LAYERS = ['sketch-fill', 'sketch-case', 'sketch-line'] as const;

const EMPTY: DrawState = {
  tool: 'pan',
  shapes: [],
  draft: null,
  canUndo: false,
  canRedo: false,
  asking: null,
};

const SHAPE_KEYS: Record<string, ShapeKind> = {
  r: 'rectangle',
  o: 'circle',
  p: 'polygon',
  l: 'ruler',
  a: 'approach',
  e: 'escape',
  z: 'safe',
};

const cssColor = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function adapt(map: MaplibreMap): MapLike {
  const listeners = new Map<(event: MapEvent) => void, (event: MapMouseEvent) => void>();
  return {
    on: (type, listener) => {
      const wrapped = (event: MapMouseEvent) => {
        listener(event);
      };
      listeners.set(listener, wrapped);
      map.on(type as 'click', wrapped);
    },
    off: (type, listener) => {
      const wrapped = listeners.get(listener);
      if (wrapped) map.off(type as 'click', wrapped);
    },
    project: (point) => map.project(point),
    setCursor: (cursor) => {
      map.getCanvas().style.cursor = cursor;
    },
    setPanning: (enabled) => {
      if (enabled) map.dragPan.enable();
      else map.dragPan.disable();
    },
    setDoubleClickZoom: (enabled) => {
      if (enabled) map.doubleClickZoom.enable();
      else map.doubleClickZoom.disable();
    },
  };
}

const isTyping = () => {
  const element = document.activeElement;
  return element instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(element.tagName);
};

/** The drawing tools of the map: the shapes, the keys, the layers they are painted on. */
export function useDrawing(map: MaplibreMap | null) {
  const { t, lang } = useI18n();
  const drawing = useRef<Drawing | null>(null);
  const [state, setState] = useState<DrawState>(EMPTY);
  const [shape, setShape] = useState<ShapeKind>('rectangle');
  const rulers = useRef<Marker[]>([]);

  useEffect(() => {
    if (!map) return;
    const ink = cssColor('--c-ink');
    map.addSource(SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({
      id: 'sketch-fill',
      type: 'fill',
      source: SOURCE,
      filter: ['==', ['geometry-type'], 'Polygon'],
      paint: { 'fill-color': ink, 'fill-opacity': 0.06 },
    });
    map.addLayer({
      id: 'sketch-case',
      type: 'line',
      source: SOURCE,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': cssColor('--c-halo'), 'line-width': 6 },
    });
    map.addLayer({
      id: 'sketch-line',
      type: 'line',
      source: SOURCE,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': ink, 'line-width': 2.5 },
    });
    const controller = createDrawing(adapt(map), setState);
    drawing.current = controller;
    return () => {
      controller.destroy();
      drawing.current = null;
      for (const marker of rulers.current) marker.remove();
      rulers.current = [];
      withMap(map, () => {
        for (const id of LAYERS) map.removeLayer(id);
        map.removeSource(SOURCE);
      });
    };
  }, [map]);

  // paint what is drawn
  useEffect(() => {
    if (!map) return;
    const shapes: Shape[] = (
      state.draft ? [...state.shapes, state.draft] : [...state.shapes]
    ).filter((shape) => !isMark(shape) && !isAi(shape) && tacticOf(shape) === null);
    void map.getSource<GeoJSONSource>(SOURCE)?.setData({
      type: 'FeatureCollection',
      features: shapes.map(toFeature),
    });
  }, [map, state]);

  // each ruler carries its length
  useEffect(() => {
    if (!map) return;
    for (const marker of rulers.current) marker.remove();
    const lines = (state.draft ? [...state.shapes, state.draft] : state.shapes).filter(
      (shape) => shape.kind === 'ruler' && shape.points.length === 2,
    );
    rulers.current = lines.map((line) => {
      const [a, b] = line.points as [LngLat, LngLat];
      const { value, unit } = toLength(distanceM(a, b));
      const label = document.createElement('div');
      label.className = styles.ruler ?? '';
      label.textContent = `${new Intl.NumberFormat(LOCALES[lang]).format(value)} ${t(`unit.${unit}`)}`;
      return new Marker({ element: label, anchor: 'bottom', offset: [0, -6] })
        .setLngLat([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2])
        .addTo(map);
    });
  }, [map, state, lang, t]);

  // the assistant's drawings: their layers, which of them is pressed, and what the map is asked to do with them
  const layer = useAiLayer(map, state.shapes, state.tool === 'pan');
  const everything = useMemo(
    () => (state.draft ? [...state.shapes, state.draft] : state.shapes),
    [state.shapes, state.draft],
  );
  useTacticLayer(map, everything, t('pl.chSafe'));
  const shapes = useRef<readonly Shape[]>([]);
  useEffect(() => {
    shapes.current = state.shapes;
  }, [state.shapes]);
  const drawAi = useCallback((drawn: readonly DrawShape[], replace: boolean) => {
    drawing.current?.loadAi(drawn, replace);
  }, []);
  const clearAi = useCallback(() => {
    drawing.current?.dropAi();
  }, []);
  const showAi = useCallback(
    (id: string) => {
      const shape = shapes.current.find((item) => item.id === id && isAi(item));
      if (!map || !shape) return;
      const lngs = shape.points.map((point) => point[0]);
      const lats = shape.points.map((point) => point[1]);
      if (shape.points.length === 1) {
        map.easeTo({ center: shape.points[0] ?? [0, 0], zoom: Math.max(map.getZoom(), 12) });
      } else {
        map.fitBounds(
          [
            [Math.min(...lngs), Math.min(...lats)],
            [Math.max(...lngs), Math.max(...lats)],
          ],
          { padding: 90, maxZoom: 13 },
        );
      }
    },
    [map],
  );
  const adoptAi = useCallback((id: string) => drawing.current?.adopt(id) ?? null, []);

  const chooseTool = useCallback((tool: Tool) => {
    drawing.current?.setTool(tool);
  }, []);

  const chooseShape = useCallback(
    (next: ShapeKind) => {
      setShape(next);
      chooseTool(next);
    },
    [chooseTool],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const controller = drawing.current;
      if (!controller || isTyping()) return;
      const key = event.key.toLowerCase();
      if (event.metaKey || event.ctrlKey) {
        if (event.altKey) return;
        if (key === 'z') {
          event.preventDefault();
          if (event.shiftKey) controller.redo();
          else controller.undo();
        } else if (key === 'y') {
          event.preventDefault();
          controller.redo();
        }
        return;
      }
      if (event.altKey) return;
      if (event.key === 'Escape') {
        if (state.draft) controller.cancel();
        else if (state.tool !== 'pan') controller.setTool('pan');
      } else if (event.key === 'Enter') {
        controller.finishPolygon();
      } else {
        const kind = SHAPE_KEYS[key];
        if (kind) {
          event.preventDefault();
          chooseShape(kind);
        }
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [state.draft, state.tool, chooseShape]);

  // the shapes that close on themselves: areas a question can be asked about, each with its name
  const areas = useMemo(
    () =>
      state.shapes.flatMap((item) =>
        item.closed && item.kind !== 'ruler' && item.id
          ? [
              {
                id: item.id,
                points: item.points,
                role: tacticOf(item) === 'safe' ? ('safe_zone' as const) : ('area' as const),
              },
            ]
          : [],
      ),
    [state.shapes],
  );

  const marks = useMemo(
    () =>
      state.shapes.flatMap((item) =>
        isMark(item) && item.id && item.points[0]
          ? [{ id: item.id, kind: item.kind, position: item.points[0] }]
          : [],
      ),
    [state.shapes],
  );
  const addMark = useCallback((kind: MarkKind, position: LngLat) => {
    drawing.current?.addMark(kind, position);
  }, []);
  const moveMark = useCallback((id: string, position: LngLat) => {
    drawing.current?.moveMark(id, position);
  }, []);
  const clearMarks = useCallback((kind: MarkKind) => {
    drawing.current?.clearMarks(kind);
  }, []);
  const loadMarks = useCallback((list: readonly { kind: MarkKind; position: LngLat }[]) => {
    drawing.current?.loadMarks(list);
  }, []);

  return {
    ai: {
      picked: layer.picked,
      dismiss: layer.dismiss,
      shapes: state.shapes.filter(isAi),
      draw: drawAi,
      clear: clearAi,
      show: showAi,
      adopt: adoptAi,
    },
    areas,
    asking: state.asking,
    dismissAsk: () => {
      drawing.current?.dismissAsk();
    },
    marks,
    addMark,
    moveMark,
    clearMarks,
    loadMarks,
    tool: state.tool,
    shape,
    canUndo: state.canUndo,
    canRedo: state.canRedo,
    chooseTool,
    chooseShape,
    undo: () => drawing.current?.undo(),
    redo: () => drawing.current?.redo(),
    remove: (id: string) => {
      drawing.current?.remove(id);
    },
    clear: () => drawing.current?.clear(),
  };
}
