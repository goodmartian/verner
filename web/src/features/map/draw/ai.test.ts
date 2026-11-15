import type { Feature } from 'geojson';
import { describe, expect, it } from 'vitest';
import type { DrawShape } from '../../../api/types';
import { aiCollections, aiShape, boundsRing, endBearing, tacticCollections, withDrawn } from './ai';
import { rectangleRing } from './geometry';
import { tacticOf, toFeature } from './shapes';

const prop = (feature: Feature, key: string): unknown => feature.properties?.[key] as unknown;

const RING = [
  [0, 0],
  [4, 0],
  [4, 4],
  [0, 0],
];
const HOLE = [
  [1, 1],
  [2, 1],
  [2, 2],
  [1, 1],
];

const polygon = {
  id: 'A1',
  kind: 'polygon',
  label: 'Buffer',
  label_at: [2, 1],
  rings: [RING, HOLE],
} as unknown as DrawShape;
const circle = {
  id: 'A2',
  kind: 'circle',
  label_at: [-60, -30],
  center: [-60, -30],
  radius_km: 5,
} as unknown as DrawShape;
const path = {
  id: 'A3',
  kind: 'line',
  role: 'path',
  label_at: [1, 1],
  points: [
    [0, 0],
    [0, 2],
  ],
} as unknown as DrawShape;
const point = {
  id: 'A4',
  kind: 'point',
  label: 'Meeting point',
  label_at: [3, 3],
  position: [3, 3],
} as unknown as DrawShape;

describe('the shapes of the assistant', () => {
  it('keep their name, caption and the holes of an area', () => {
    const shape = aiShape(polygon);
    expect(shape).toMatchObject({ id: 'A1', source: 'ai', label: 'Buffer', closed: true });
    expect(shape.points).toEqual(RING);
    expect(shape.holes).toEqual([HOLE]);
    expect(toFeature(shape).geometry).toEqual({ type: 'Polygon', coordinates: [RING, HOLE] });
  });

  it('draw a circle as a ring of kilometres around its centre', () => {
    const shape = aiShape(circle);
    expect(shape.closed).toBe(true);
    const lngs = shape.points.map((p) => p[0]);
    // five kilometres is a twentieth of a degree of longitude, a little more at this latitude
    expect(Math.max(...lngs) - Math.min(...lngs)).toBeGreaterThan(0.09);
    expect(Math.max(...lngs) - Math.min(...lngs)).toBeLessThan(0.12);
  });

  it('give a point as a point and a way as an open line with its role', () => {
    expect(toFeature(aiShape(point)).geometry).toEqual({ type: 'Point', coordinates: [3, 3] });
    expect(aiShape(path)).toMatchObject({ kind: 'line', closed: false, role: 'path' });
  });

  it('take a tactical role the server gives, on an area or on a way', () => {
    const zone = aiShape({ ...polygon, role: 'safe_zone' } as unknown as DrawShape);
    expect(tacticOf(zone)).toBe('safe');
    const way = aiShape({ ...path, role: 'escape' } as unknown as DrawShape);
    expect(tacticOf(way)).toBe('escape');
    expect(tacticOf(aiShape(polygon))).toBeNull();
    expect(tacticOf(aiShape(path))).toBeNull();
  });
});

describe('what the assistant draws joins the map', () => {
  const mine = [aiShape(polygon), aiShape(circle)];
  const own = { kind: 'rectangle' as const, id: 'U1', points: [], closed: true };

  it('is added to what there is, and the person drawings stay', () => {
    const next = withDrawn([own, ...mine], [point], false);
    expect(next.map((shape) => shape.id)).toEqual(['U1', 'A1', 'A2', 'A4']);
  });

  it('takes the place of the old drawings of the assistant when it says replace', () => {
    const next = withDrawn([own, ...mine], [point], true);
    expect(next.map((shape) => shape.id)).toEqual(['U1', 'A4']);
  });

  it('puts a shape drawn again under its name in place of the one before', () => {
    const again = { ...polygon, label: 'Wider buffer' } as unknown as DrawShape;
    const next = withDrawn([own, ...mine], [again], false);
    expect(next.map((shape) => shape.id)).toEqual(['U1', 'A2', 'A1']);
    expect(next.at(-1)?.label).toBe('Wider buffer');
  });
});

describe('the pieces of the assistant layers', () => {
  it('end a way with the bearing of its last stretch', () => {
    expect(
      endBearing([
        [0, 0],
        [0, 2],
      ]),
    ).toBeCloseTo(0, 5);
    expect(
      endBearing([
        [0, 0],
        [2, 0],
      ]),
    ).toBeCloseTo(90, 0);
    expect(
      endBearing([
        [0, 0],
        [0, -1],
        [0, -1],
      ]),
    ).toBeCloseTo(180, 5);
  });

  it('box a line or a point so that it can be asked about', () => {
    const ring = boundsRing([[-60, -30]]);
    expect(ring).toHaveLength(5);
    expect(ring[0]).toEqual(ring[4]);
    const width = (ring[1]?.[0] ?? 0) - (ring[0]?.[0] ?? 0);
    expect(width).toBeGreaterThan(0.009);
    expect(width).toBeLessThan(0.012);
  });

  it('give a caption to a shape that has one, an arrowhead to a way, and nothing to the rest', () => {
    const shapes = [polygon, point, path, circle].map(aiShape);
    const { labels, heads, shapes: drawn } = aiCollections(shapes);
    expect(labels.features.map((feature) => prop(feature, 'label'))).toEqual([
      'Buffer',
      'Meeting point',
    ]);
    // beside the shape: an area on its northern edge, a point under itself
    expect(labels.features.map((feature) => prop(feature, 'kind'))).toEqual(['area', 'point']);
    expect(labels.features[0]?.geometry).toEqual({ type: 'Point', coordinates: [2, 4] });
    expect(heads.features).toHaveLength(1);
    expect(drawn.features).toHaveLength(4);
  });

  it('put the shield of a zone drawn by the person in the middle of it, not at the mean of its corners', () => {
    const zone = {
      kind: 'safe' as const,
      id: 'U1',
      points: rectangleRing([0, 0], [4, 2]),
      closed: true,
    };
    const { marks } = tacticCollections([zone], 'Safe zone');
    expect(marks.features[0]?.geometry).toEqual({ type: 'Point', coordinates: [2, 1] });
  });

  it('put the shield of a zone of the assistant where the server put its caption', () => {
    const zone = aiShape({ ...polygon, role: 'safe_zone' } as unknown as DrawShape);
    const { marks } = tacticCollections([zone], 'Safe zone');
    expect(marks.features[0]?.geometry).toEqual({ type: 'Point', coordinates: [2, 1] });
  });

  it('draw the tactical shapes of both authors in one place, the plan look, with an arrowhead and a shield', () => {
    const user = {
      kind: 'approach' as const,
      points: [
        [0, 0],
        [0, 3],
      ] as [number, number][],
      closed: false,
    };
    const zone = aiShape({ ...polygon, role: 'safe_zone' } as unknown as DrawShape);
    const mine = {
      kind: 'safe' as const,
      id: 'U2',
      points: RING as [number, number][],
      closed: true,
    };
    const plain = aiShape(path);
    const { shapes, heads, marks, names } = tacticCollections(
      [user, zone, mine, plain],
      'Safe zone',
    );
    expect(shapes.features).toHaveLength(3);
    expect(heads.features).toHaveLength(1);
    // a shield in each zone; the name only of the one the person drew, over its northern edge
    expect(marks.features).toHaveLength(2);
    expect(names.features.map((feature) => prop(feature, 'text'))).toEqual(['Safe zone']);
    expect(names.features[0]?.geometry).toEqual({ type: 'Point', coordinates: [2, 4] });
  });
});
