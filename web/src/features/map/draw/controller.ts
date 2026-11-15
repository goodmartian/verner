import type { DrawShape } from '../../../api/types';
import { withDrawn } from './ai';
import { circleRing, rectangleRing, type LngLat } from './geometry';
import { commit, redo, startHistory, undo, type History } from './history';
import { isAi, isMark, tacticOf, type MarkKind, type Shape, type ShapeKind } from './shapes';

export type Tool = 'pan' | ShapeKind;

export interface Pixel {
  x: number;
  y: number;
}

export interface MapEvent {
  lngLat: { lng: number; lat: number };
  point: Pixel;
  originalEvent?: { button?: number };
  preventDefault: () => void;
}

/** What the drawing needs from the map; the real map is adapted to it. */
export interface MapLike {
  on: (type: string, listener: (event: MapEvent) => void) => void;
  off: (type: string, listener: (event: MapEvent) => void) => void;
  project: (point: LngLat) => Pixel;
  setCursor: (cursor: string) => void;
  setPanning: (enabled: boolean) => void;
  setDoubleClickZoom: (enabled: boolean) => void;
}

export interface DrawState {
  tool: Tool;
  shapes: readonly Shape[];
  /** The shape being drawn right now. */
  draft: Shape | null;
  canUndo: boolean;
  canRedo: boolean;
  /** The area just closed, which has the button to ask about it beside it; null when none has. */
  asking: string | null;
}

// a shape smaller than this many pixels is a stray click, not a drawing
const MIN_PX = 8;
// a click this close to the first corner closes a polygon
const CLOSE_PX = 12;
// a pencil line that ends this close to its start becomes a closed shape
const PENCIL_CLOSE_PX = 40;
const PENCIL_STEP_PX = 3;

const DRAG_TOOLS: readonly Tool[] = [
  'rectangle',
  'circle',
  'ruler',
  'pencil',
  'approach',
  'escape',
  'safe',
];
// a way is drawn by a drag, or by two clicks: from where and to where
const isWay = (tool: Tool): tool is 'approach' | 'escape' =>
  tool === 'approach' || tool === 'escape';
const DOWN = ['mousedown', 'touchstart'] as const;
const MOVE = ['mousemove', 'touchmove'] as const;
const UP = ['mouseup', 'touchend'] as const;

const lngLat = (event: MapEvent): LngLat => [event.lngLat.lng, event.lngLat.lat];

/** The drawing tools of the map as a state machine: events in, shapes out. */
export function createDrawing(map: MapLike, onChange: (state: DrawState) => void) {
  let tool: Tool = 'pan';
  let shapes: History<readonly Shape[]> = startHistory([]);
  let draft: Shape | null = null;
  let origin: LngLat | null = null;
  let polygon: LngLat[] | null = null;
  let cursor: LngLat | null = null;
  // where the pointer is now, for the shape that is being dragged
  let end: LngLat | null = null;
  // the first click of a way drawn by two clicks
  let wayStart: LngLat | null = null;

  const px = (a: LngLat, b: LngLat) => {
    const p = map.project(a);
    const q = map.project(b);
    return Math.hypot(p.x - q.x, p.y - q.y);
  };

  const emit = () => {
    const live: Shape | null =
      polygon && cursor
        ? { kind: 'polygon', points: [...polygon, cursor], closed: false }
        : wayStart && cursor && isWay(tool)
          ? { kind: tool as ShapeKind, points: [wayStart, cursor], closed: false }
          : draft;
    onChange({
      tool,
      shapes: shapes.present,
      draft: live,
      canUndo: shapes.past.length > 0,
      canRedo: shapes.future.length > 0,
      asking,
    });
  };

  let named = 0;
  let marked = 0;
  let asking: string | null = null;
  const add = (shape: Shape) => {
    // a closed shape is an area and gets a name that is never given twice
    const entry = shape.closed ? { ...shape, id: `U${String((named += 1))}` } : shape;
    shapes = commit(shapes, [...shapes.present, entry]);
    asking = entry.closed ? (entry.id ?? null) : asking;
  };

  const finishPolygon = () => {
    const points = polygon;
    polygon = null;
    cursor = null;
    const first = points?.[0];
    if (points && first && points.length >= 3) {
      add({ kind: 'polygon', points: [...points, first], closed: true });
    }
    emit();
  };

  const cancel = () => {
    wayStart = null;
    draft = null;
    origin = null;
    end = null;
    polygon = null;
    cursor = null;
    emit();
  };

  const onDown = (event: MapEvent) => {
    if (!DRAG_TOOLS.includes(tool)) return;
    if (event.originalEvent?.button !== undefined && event.originalEvent.button !== 0) return;
    event.preventDefault();
    // the second click of a way: it ends where the press is
    if (wayStart && isWay(tool)) {
      const start = wayStart;
      wayStart = null;
      cursor = null;
      if (px(start, lngLat(event)) >= MIN_PX) {
        add({ kind: tool, points: [start, lngLat(event)], closed: false });
      }
      emit();
      return;
    }
    origin = lngLat(event);
    end = origin;
    draft = { kind: tool as ShapeKind, points: [origin], closed: false };
    emit();
  };

  const onMove = (event: MapEvent) => {
    const at = lngLat(event);
    if (wayStart) {
      cursor = at;
      emit();
      return;
    }
    if (polygon) {
      cursor = at;
      emit();
      return;
    }
    if (!draft || !origin) return;
    end = at;
    switch (draft.kind) {
      case 'rectangle':
        draft = { kind: 'rectangle', points: rectangleRing(origin, at), closed: true };
        break;
      case 'circle':
        draft = { kind: 'circle', points: circleRing(origin, at), closed: true };
        break;
      case 'ruler':
        draft = { kind: 'ruler', points: [origin, at], closed: false };
        break;
      case 'approach':
      case 'escape':
        draft = { kind: draft.kind, points: [origin, at], closed: false };
        break;
      case 'safe':
        draft = { kind: 'safe', points: rectangleRing(origin, at), closed: true };
        break;
      default: {
        const last = draft.points.at(-1);
        if (last && px(last, at) >= PENCIL_STEP_PX) {
          draft = { ...draft, points: [...draft.points, at] };
        }
      }
    }
    emit();
  };

  const onUp = () => {
    const shape = draft;
    const start = origin;
    const finish = end;
    draft = null;
    origin = null;
    end = null;
    if (!shape || !start || !finish) return;
    const dragged = px(start, finish);
    const from = map.project(start);
    const to = map.project(finish);
    const big =
      shape.kind === 'rectangle' || shape.kind === 'safe'
        ? Math.abs(from.x - to.x) >= MIN_PX && Math.abs(from.y - to.y) >= MIN_PX
        : shape.kind === 'pencil'
          ? shape.points.length >= 2
          : dragged >= MIN_PX;
    // a way that was only clicked goes on to the second click
    if (!big && isWay(tool)) wayStart = start;
    if (big) {
      add(
        shape.kind === 'pencil' && shape.points.length > 8 && dragged < PENCIL_CLOSE_PX
          ? { kind: 'pencil', points: [...shape.points, start], closed: true }
          : shape,
      );
    }
    emit();
  };

  const onClick = (event: MapEvent) => {
    if (tool !== 'polygon') return;
    const at = lngLat(event);
    if (!polygon) {
      polygon = [at];
      cursor = at;
      emit();
      return;
    }
    const [first] = polygon;
    if (first && polygon.length >= 3 && px(first, at) < CLOSE_PX) {
      finishPolygon();
      return;
    }
    polygon = [...polygon, at];
    emit();
  };

  const onDoubleClick = () => {
    if (tool === 'polygon' && polygon) finishPolygon();
  };

  for (const type of DOWN) map.on(type, onDown);
  for (const type of MOVE) map.on(type, onMove);
  for (const type of UP) map.on(type, onUp);
  map.on('click', onClick);
  map.on('dblclick', onDoubleClick);

  emit();

  return {
    setTool(next: Tool) {
      if (next !== 'polygon') {
        polygon = null;
        cursor = null;
      }
      draft = null;
      origin = null;
      end = null;
      wayStart = null;
      cursor = null;
      tool = next;
      map.setCursor(next === 'pan' ? '' : 'crosshair');
      map.setPanning(next === 'pan' || next === 'polygon');
      map.setDoubleClickZoom(next !== 'polygon');
      emit();
    },
    finishPolygon,
    cancel,
    /** The button beside the area was used or is not wanted any more. */
    dismissAsk() {
      asking = null;
      emit();
    },
    undo() {
      asking = null;
      shapes = undo(shapes);
      emit();
    },
    redo() {
      asking = null;
      shapes = redo(shapes);
      emit();
    },
    /** A mark goes among the shapes, so that undo and redo treat it as they treat a drawing. */
    addMark(kind: MarkKind, position: LngLat) {
      shapes = commit(shapes, [
        ...shapes.present,
        { kind, id: `M${String((marked += 1))}`, points: [position], closed: false },
      ]);
      emit();
    },
    moveMark(id: string, position: LngLat) {
      shapes = commit(
        shapes,
        shapes.present.map((shape) => (shape.id === id ? { ...shape, points: [position] } : shape)),
      );
      emit();
    },
    clearMarks(kind: MarkKind) {
      if (shapes.present.some((shape) => shape.kind === kind)) {
        shapes = commit(
          shapes,
          shapes.present.filter((shape) => shape.kind !== kind),
        );
        emit();
      }
    },
    /** Puts these marks in place of the ones there are. */
    loadMarks(marks: readonly { kind: MarkKind; position: LngLat }[]) {
      shapes = commit(shapes, [
        ...shapes.present.filter((shape) => !isMark(shape)),
        ...marks.map(({ kind, position }) => ({
          kind,
          id: `M${String((marked += 1))}`,
          points: [position],
          closed: false,
        })),
      ]);
      emit();
    },
    /** The assistant draws: its shapes join the others in the history, so that undo and redo take them as they take the person's own. */
    loadAi(drawn: readonly DrawShape[], replace: boolean) {
      asking = null;
      shapes = commit(shapes, withDrawn(shapes.present, drawn, replace));
      emit();
    },
    /** The assistant's drawings are gone for good, from the history too: another chat has none of them. */
    dropAi() {
      const own = (list: readonly Shape[]) => list.filter((shape) => !isAi(shape));
      shapes = {
        past: shapes.past.map(own),
        present: own(shapes.present),
        future: shapes.future.map(own),
      };
      asking = null;
      emit();
    },
    /** A copy of the assistant's drawing among the person's own, which all the tools then work on; its name; null when there is no copy, or when the copy is an open line, which has no name. */
    adopt(id: string): string | null {
      const shape = shapes.present.find((item) => item.id === id && isAi(item));
      if (!shape) return null;
      // a tactical shape stays what it is in the copy: a way to the fire, a way out, a safe zone
      const tactic = tacticOf(shape);
      const copy: Shape | null = shape.closed
        ? {
            kind: tactic === 'safe' ? 'safe' : 'polygon',
            points: shape.points,
            closed: true,
            ...(shape.holes ? { holes: shape.holes } : {}),
            // the mark of the zone stays where the assistant put it
            ...(shape.labelAt ? { labelAt: shape.labelAt } : {}),
            id: `U${String((named += 1))}`,
          }
        : shape.kind === 'line'
          ? {
              kind: tactic === 'approach' || tactic === 'escape' ? tactic : 'pencil',
              points: shape.points,
              closed: false,
            }
          : null;
      if (!copy) return null;
      shapes = commit(shapes, [...shapes.present, copy]);
      emit();
      return copy.id ?? null;
    },
    remove(id: string) {
      asking = null;
      shapes = commit(
        shapes,
        shapes.present.filter((shape) => shape.id !== id),
      );
      emit();
    },
    clear() {
      asking = null;
      if (shapes.present.length > 0) shapes = commit(shapes, []);
      cancel();
    },
    destroy() {
      for (const type of DOWN) map.off(type, onDown);
      for (const type of MOVE) map.off(type, onMove);
      for (const type of UP) map.off(type, onUp);
      map.off('click', onClick);
      map.off('dblclick', onDoubleClick);
      map.setCursor('');
      map.setPanning(true);
      map.setDoubleClickZoom(true);
    },
  };
}

export type Drawing = ReturnType<typeof createDrawing>;
