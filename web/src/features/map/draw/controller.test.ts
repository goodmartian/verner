import { describe, expect, it, vi } from 'vitest';
import type { DrawShape } from '../../../api/types';
import { createDrawing, type DrawState, type MapEvent, type MapLike } from './controller';

// one degree is a hundred pixels, so a tenth of a degree is ten pixels
function fakeMap() {
  const handlers = new Map<string, Set<(event: MapEvent) => void>>();
  const map: MapLike & { cursor: string; panning: boolean; doubleClick: boolean } = {
    cursor: '',
    panning: true,
    doubleClick: true,
    on: (type, listener) => {
      handlers.set(type, (handlers.get(type) ?? new Set()).add(listener));
    },
    off: (type, listener) => {
      handlers.get(type)?.delete(listener);
    },
    project: ([x, y]) => ({ x: x * 100, y: y * 100 }),
    setCursor: (cursor) => {
      map.cursor = cursor;
    },
    setPanning: (enabled) => {
      map.panning = enabled;
    },
    setDoubleClickZoom: (enabled) => {
      map.doubleClick = enabled;
    },
  };
  const fire = (type: string, lng: number, lat: number, button = 0) => {
    const event: MapEvent = {
      lngLat: { lng, lat },
      point: { x: lng * 100, y: lat * 100 },
      originalEvent: { button },
      preventDefault: () => undefined,
    };
    handlers.get(type)?.forEach((listener) => {
      listener(event);
    });
  };
  const count = () => [...handlers.values()].reduce((sum, set) => sum + set.size, 0);
  return { map, fire, count };
}

function setup() {
  const world = fakeMap();
  let state: DrawState | undefined;
  const drawing = createDrawing(world.map, (next) => {
    state = next;
  });
  const now = () => {
    if (!state) throw new Error('no state yet');
    return state;
  };
  const drag = (from: [number, number], to: [number, number], steps: [number, number][] = []) => {
    world.fire('mousedown', ...from);
    for (const step of steps) world.fire('mousemove', ...step);
    world.fire('mousemove', ...to);
    world.fire('mouseup', ...to);
  };
  return { ...world, drawing, now, drag };
}

describe('drawing', () => {
  it('starts on the pan tool and ignores drags there', () => {
    const { drag, now } = setup();
    drag([0, 0], [1, 1]);
    expect(now().tool).toBe('pan');
    expect(now().shapes).toHaveLength(0);
  });

  it('draws a rectangle by dragging and can undo and redo it', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('rectangle');
    drag([0, 0], [2, 1]);
    expect(now().shapes).toHaveLength(1);
    expect(now().shapes[0]).toMatchObject({ kind: 'rectangle', closed: true });
    expect(now().shapes[0]?.points).toHaveLength(5);
    expect(now().canUndo).toBe(true);
    drawing.undo();
    expect(now().shapes).toHaveLength(0);
    expect(now().canRedo).toBe(true);
    drawing.redo();
    expect(now().shapes).toHaveLength(1);
  });

  it('shows the shape while it is dragged', () => {
    const { drawing, fire, now } = setup();
    drawing.setTool('rectangle');
    fire('mousedown', 0, 0);
    fire('mousemove', 3, 2);
    expect(now().draft?.kind).toBe('rectangle');
    expect(now().shapes).toHaveLength(0);
  });

  it('throws away a stray click', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('rectangle');
    drag([0, 0], [0.05, 0.05]);
    drawing.setTool('circle');
    drag([0, 0], [0.05, 0]);
    drawing.setTool('ruler');
    drag([0, 0], [0.05, 0]);
    expect(now().shapes).toHaveLength(0);
    expect(now().draft).toBeNull();
  });

  it('ignores the right mouse button', () => {
    const { drawing, fire, now } = setup();
    drawing.setTool('rectangle');
    fire('mousedown', 0, 0, 2);
    expect(now().draft).toBeNull();
  });

  it('draws a closed circle', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('circle');
    drag([0, 0], [1, 0]);
    expect(now().shapes[0]).toMatchObject({ kind: 'circle', closed: true });
    expect(now().shapes[0]?.points).toHaveLength(65);
  });

  it('draws a ruler as an open line of two points', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('ruler');
    drag([0, 0], [1, 1]);
    expect(now().shapes[0]).toMatchObject({ kind: 'ruler', closed: false });
    expect(now().shapes[0]?.points).toEqual([
      [0, 0],
      [1, 1],
    ]);
  });

  it('draws a pencil line, and closes it when it comes back to its start', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('pencil');
    drag(
      [0, 0],
      [0.1, 0.1],
      [
        [0.1, 0],
        [0.2, 0],
        [0.3, 0.1],
        [0.3, 0.2],
        [0.2, 0.3],
        [0.1, 0.3],
        [0.05, 0.2],
        [0.05, 0.1],
      ],
    );
    expect(now().shapes[0]).toMatchObject({ kind: 'pencil', closed: true });

    drag(
      [5, 5],
      [8, 5],
      [
        [6, 5],
        [7, 5],
      ],
    );
    expect(now().shapes[1]).toMatchObject({ kind: 'pencil', closed: false });
  });

  it('builds a polygon from clicks and closes it on the first corner', () => {
    const { drawing, fire, now } = setup();
    drawing.setTool('polygon');
    fire('click', 0, 0);
    fire('click', 3, 0);
    fire('mousemove', 3, 2);
    expect(now().draft?.points).toHaveLength(3);
    fire('click', 3, 2);
    fire('click', 0.05, 0.05);
    expect(now().shapes).toHaveLength(1);
    expect(now().shapes[0]).toMatchObject({ kind: 'polygon', closed: true });
    expect(now().shapes[0]?.points).toHaveLength(4);
    expect(now().draft).toBeNull();
  });

  it('closes a polygon on a double click or Enter, but not with fewer than three corners', () => {
    const { drawing, fire, now } = setup();
    drawing.setTool('polygon');
    fire('click', 0, 0);
    fire('click', 3, 0);
    drawing.finishPolygon();
    expect(now().shapes).toHaveLength(0);

    fire('click', 0, 0);
    fire('click', 3, 0);
    fire('click', 3, 2);
    fire('dblclick', 3, 2);
    expect(now().shapes).toHaveLength(1);

    fire('click', 10, 10);
    fire('click', 13, 10);
    fire('click', 13, 12);
    drawing.finishPolygon();
    expect(now().shapes).toHaveLength(2);
  });

  it('drops an unfinished polygon when another tool is chosen or when cancelled', () => {
    const { drawing, fire, now } = setup();
    drawing.setTool('polygon');
    fire('click', 0, 0);
    fire('click', 3, 0);
    drawing.setTool('rectangle');
    expect(now().draft).toBeNull();
    drawing.setTool('polygon');
    fire('click', 0, 0);
    drawing.cancel();
    expect(now().draft).toBeNull();
  });

  it('clears everything in a way that can be undone', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('rectangle');
    drag([0, 0], [2, 1]);
    drag([4, 4], [6, 5]);
    drawing.clear();
    expect(now().shapes).toHaveLength(0);
    drawing.undo();
    expect(now().shapes).toHaveLength(2);
  });

  it('forgets what was undone when something new is drawn', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('rectangle');
    drag([0, 0], [2, 1]);
    drawing.undo();
    drag([4, 4], [6, 5]);
    expect(now().canRedo).toBe(false);
  });

  it('keeps the map from panning while a shape is dragged, and gives it back', () => {
    const { drawing, map } = setup();
    drawing.setTool('rectangle');
    expect(map.panning).toBe(false);
    expect(map.cursor).toBe('crosshair');
    drawing.setTool('polygon');
    expect(map.panning).toBe(true);
    expect(map.doubleClick).toBe(false);
    drawing.setTool('pan');
    expect(map.cursor).toBe('');
    expect(map.doubleClick).toBe(true);
  });

  it('lets go of the map when it is destroyed', () => {
    const { drawing, count, map } = setup();
    drawing.setTool('rectangle');
    expect(count()).toBeGreaterThan(0);
    const spy = vi.spyOn(map, 'setPanning');
    drawing.destroy();
    expect(count()).toBe(0);
    expect(spy).toHaveBeenCalledWith(true);
  });

  it('names every closed shape, never twice, and gives a line no name', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('rectangle');
    drag([0, 0], [2, 1]);
    drag([3, 0], [5, 1]);
    drawing.setTool('ruler');
    drag([0, 3], [2, 3]);
    expect(now().shapes.map((shape) => shape.id)).toEqual(['U1', 'U2', undefined]);
    drawing.remove('U2');
    drawing.setTool('rectangle');
    drag([6, 0], [8, 1]);
    expect(now().shapes.map((shape) => shape.id)).toEqual(['U1', undefined, 'U3']);
  });

  it('removes one area and leaves the others; undo brings it back', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('rectangle');
    drag([0, 0], [2, 1]);
    drag([3, 0], [5, 1]);
    drawing.remove('U1');
    expect(now().shapes.map((shape) => shape.id)).toEqual(['U2']);
    drawing.undo();
    expect(now().shapes.map((shape) => shape.id)).toEqual(['U1', 'U2']);
  });

  it('keeps the marks of the operator in the same history as the drawings', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('rectangle');
    drag([0, 0], [2, 1]);
    drawing.addMark('entry', [1, 5]);
    drawing.addMark('hot', [2, 5]);
    expect(now().shapes.map((shape) => shape.kind)).toEqual(['rectangle', 'entry', 'hot']);
    drawing.moveMark('M1', [3, 5]);
    expect(now().shapes[1]?.points).toEqual([[3, 5]]);
    drawing.undo();
    expect(now().shapes[1]?.points).toEqual([[1, 5]]);
    drawing.undo();
    drawing.undo();
    expect(now().shapes.map((shape) => shape.kind)).toEqual(['rectangle']);
    drawing.redo();
    expect(now().shapes.map((shape) => shape.kind)).toEqual(['rectangle', 'entry']);
  });

  it('takes off the marks of one kind, and puts a set of marks in place of the others', () => {
    const { drawing, now } = setup();
    drawing.addMark('entry', [1, 5]);
    drawing.addMark('hot', [2, 5]);
    drawing.clearMarks('entry');
    expect(now().shapes.map((shape) => shape.kind)).toEqual(['hot']);
    drawing.loadMarks([
      { kind: 'entry', position: [4, 4] },
      { kind: 'entry', position: [5, 4] },
    ]);
    expect(now().shapes.map((shape) => shape.kind)).toEqual(['entry', 'entry']);
    drawing.undo();
    expect(now().shapes.map((shape) => shape.kind)).toEqual(['hot']);
  });

  it('offers the button to ask only for the area just closed, until it is used or the drawing changes', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('rectangle');
    drag([0, 0], [2, 1]);
    expect(now().asking).toBe('U1');
    drag([3, 0], [5, 1]);
    expect(now().asking).toBe('U2');
    drawing.dismissAsk();
    expect(now().asking).toBeNull();
    drag([6, 0], [8, 1]);
    expect(now().asking).toBe('U3');
    drawing.undo();
    expect(now().asking).toBeNull();
    drawing.setTool('ruler');
    drag([0, 3], [2, 3]);
    expect(now().asking).toBeNull();
  });
});

describe('the tactical shapes of the plan', () => {
  it('draws a way to the fire by a drag, and a way out by two clicks', () => {
    const { drawing, drag, fire, now } = setup();
    drawing.setTool('approach');
    drag([0, 0], [3, 0]);
    expect(now().shapes.map((shape) => shape.kind)).toEqual(['approach']);
    expect(now().shapes[0]?.closed).toBe(false);
    drawing.setTool('escape');
    // a click without a drag only says where it starts: the line follows the pointer to the second click
    fire('mousedown', 0, 2);
    fire('mouseup', 0, 2);
    expect(now().shapes).toHaveLength(1);
    fire('mousemove', 2, 2);
    expect(now().draft?.points).toEqual([
      [0, 2],
      [2, 2],
    ]);
    fire('mousedown', 4, 2);
    fire('mouseup', 4, 2);
    expect(now().shapes.map((shape) => shape.kind)).toEqual(['approach', 'escape']);
    expect(now().shapes[1]?.points).toEqual([
      [0, 2],
      [4, 2],
    ]);
    expect(now().draft).toBeNull();
  });

  it('lets go of the first click of a way on Escape, and when the tool is changed', () => {
    const { drawing, fire, now } = setup();
    drawing.setTool('approach');
    fire('mousedown', 0, 2);
    fire('mouseup', 0, 2);
    fire('mousemove', 2, 2);
    drawing.cancel();
    expect(now().draft).toBeNull();
    fire('mousemove', 3, 3);
    expect(now().draft).toBeNull();
  });

  it('draws a safe zone as an area with a name, which can be asked about', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('safe');
    drag([0, 0], [2, 1]);
    expect(now().shapes[0]).toMatchObject({ kind: 'safe', id: 'U1', closed: true });
    expect(now().asking).toBe('U1');
  });
});

describe('the drawings of the assistant', () => {
  const zone = {
    id: 'A1',
    kind: 'polygon',
    label: 'Buffer',
    label_at: [1, 1],
    rings: [
      [
        [0, 0],
        [4, 0],
        [4, 4],
        [0, 0],
      ],
    ],
  } as unknown as DrawShape;
  const way = {
    id: 'A2',
    kind: 'line',
    role: 'path',
    label_at: [1, 1],
    points: [
      [0, 0],
      [0, 3],
    ],
  } as unknown as DrawShape;
  const spot = {
    id: 'A3',
    kind: 'point',
    label_at: [2, 2],
    position: [2, 2],
  } as unknown as DrawShape;

  it('go among the shapes, and undo takes them off as it takes the drawings of the person', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('rectangle');
    drag([0, 0], [2, 1]);
    drawing.loadAi([zone, way], false);
    expect(now().shapes.map((shape) => shape.id)).toEqual(['U1', 'A1', 'A2']);
    drawing.undo();
    expect(now().shapes.map((shape) => shape.id)).toEqual(['U1']);
    drawing.redo();
    expect(now().shapes.map((shape) => shape.id)).toEqual(['U1', 'A1', 'A2']);
  });

  it('are taken away by the eraser together with the rest, and come back with undo', () => {
    const { drawing, now } = setup();
    drawing.loadAi([zone], false);
    drawing.clear();
    expect(now().shapes).toHaveLength(0);
    drawing.undo();
    expect(now().shapes.map((shape) => shape.id)).toEqual(['A1']);
  });

  it('are the only thing dropped when the chat is another: the person drawings stay, and undo cannot bring them back', () => {
    const { drawing, drag, now } = setup();
    drawing.setTool('rectangle');
    drag([0, 0], [2, 1]);
    drawing.loadAi([zone], false);
    drawing.dropAi();
    expect(now().shapes.map((shape) => shape.id)).toEqual(['U1']);
    drawing.undo();
    drawing.redo();
    drawing.redo();
    expect(now().shapes.map((shape) => shape.id)).toEqual(['U1']);
  });

  it('keep what they mean in the copy: a safe zone stays a safe zone, a way out a way out', () => {
    const { drawing, now } = setup();
    drawing.loadAi(
      [
        { ...zone, id: 'A1', role: 'safe_zone' },
        { ...way, id: 'A2', role: 'escape' },
      ] as unknown as DrawShape[],
      false,
    );
    expect(drawing.adopt('A1')).toBe('U1');
    drawing.adopt('A2');
    expect(now().shapes.map((shape) => shape.kind)).toEqual(['polygon', 'line', 'safe', 'escape']);
    expect(now().shapes.at(-1)?.source).toBeUndefined();
  });

  it('can be made the own area of the person: a copy that is black, named and drawn by every tool', () => {
    const { drawing, now } = setup();
    drawing.loadAi([zone, way, spot], false);
    expect(drawing.adopt('A1')).toBe('U1');
    // a point has no copy; a way is copied as a line of the pencil, which has no name
    expect(drawing.adopt('A3')).toBeNull();
    expect(now().shapes).toHaveLength(4);
    expect(drawing.adopt('A2')).toBeNull();
    expect(now().shapes.at(-1)).toMatchObject({ kind: 'pencil', closed: false });
    expect(now().shapes.at(-1)?.source).toBeUndefined();
    const copy = now().shapes.find((shape) => shape.id === 'U1');
    expect(copy).toMatchObject({ kind: 'polygon', closed: true });
    expect(copy?.source).toBeUndefined();
    expect(now().shapes.filter((shape) => shape.source === 'ai')).toHaveLength(3);
    drawing.remove('U1');
    expect(now().shapes.map((shape) => shape.id)).toEqual(['A1', 'A2', 'A3', undefined]);
  });
});
