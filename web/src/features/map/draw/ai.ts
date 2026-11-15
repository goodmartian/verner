import type { Feature, FeatureCollection, Point } from 'geojson';
import type { DrawShape } from '../../../api/types';
import { centroid, circleAround, type LngLat } from './geometry';
import { tacticOf, toFeature, type Shape } from './shapes';

const tacticalRole = (role: string | undefined): { role?: Shape['role'] } =>
  role === 'approach' || role === 'escape' || role === 'safe_zone' ? { role } : {};

const at = (p: readonly number[]): LngLat => [p[0] ?? 0, p[1] ?? 0];

/** A shape the server worked out, as a shape of the map; the assistant's own, with its name and caption. */
export function aiShape(shape: DrawShape): Shape {
  const common = {
    id: shape.id,
    source: 'ai' as const,
    labelAt: at(shape.label_at),
    ...(shape.label ? { label: shape.label } : {}),
    ...(shape.note ? { note: shape.note } : {}),
  };
  // the roles the server gives besides `path` and `line`: the tactical ones, on a way or on an area
  const tactical = tacticalRole((shape as { role?: string }).role);
  switch (shape.kind) {
    case 'polygon': {
      const [outer = [], ...holes] = shape.rings.map((ring) => ring.map(at));
      return { ...common, ...tactical, kind: 'polygon', points: outer, closed: true, holes };
    }
    case 'circle':
      return {
        ...common,
        ...tactical,
        kind: 'circle',
        points: circleAround(at(shape.center), shape.radius_km),
        closed: true,
      };
    case 'line':
      return {
        ...common,
        kind: 'line',
        points: shape.points.map(at),
        closed: false,
        role: 'role' in tactical ? tactical.role : shape.role,
      };
    case 'point':
      return { ...common, kind: 'point', points: [at(shape.position)], closed: false };
  }
}

/** The shapes of the map after the assistant drew `drawn`: the old ones of the assistant go first when it says so. */
export function withDrawn(
  shapes: readonly Shape[],
  drawn: readonly DrawShape[],
  replace: boolean,
): Shape[] {
  const fresh = drawn.map(aiShape);
  const ids = new Set(fresh.map((shape) => shape.id));
  // a shape drawn again under its name takes the place of the one before
  return [
    ...shapes.filter((shape) => !(shape.source === 'ai' && (replace || ids.has(shape.id)))),
    ...fresh,
  ];
}

/** The bearing, in degrees from the north, in which a line ends: where its arrowhead points. */
export function endBearing(points: readonly LngLat[]): number {
  const to = points.at(-1);
  const from = [...points].reverse().find((point) => point[0] !== to?.[0] || point[1] !== to[1]);
  if (!to || !from) return 0;
  const lat = (to[1] * Math.PI) / 180;
  return (Math.atan2((to[0] - from[0]) * Math.cos(lat), to[1] - from[1]) * 180) / Math.PI;
}

/** The corners of the box around a shape, as a closed ring: a stretch of at least `minKm` on a side, so that a line or a point can be asked about. */
export function boundsRing(points: readonly LngLat[], minKm = 1): LngLat[] {
  const lngs = points.map((point) => point[0]);
  const lats = points.map((point) => point[1]);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const padLat = minKm / 2 / 111.32;
  const padLng = padLat / Math.max(0.2, Math.cos((midLat * Math.PI) / 180));
  const west = Math.min(...lngs) - padLng;
  const east = Math.max(...lngs) + padLng;
  const south = Math.min(...lats) - padLat;
  const north = Math.max(...lats) + padLat;
  return [
    [west, south],
    [east, south],
    [east, north],
    [west, north],
    [west, south],
  ];
}

const collection = (features: Feature[]): FeatureCollection => ({
  type: 'FeatureCollection',
  features,
});

/** What the assistant's layers draw: the shapes, their captions, and the arrowheads of the ways, each in a source of its own. */
export function aiCollections(shapes: readonly Shape[]) {
  const mine = shapes.filter((shape) => shape.source === 'ai');
  // a caption stands beside its shape, not on it: over the outline of an area, at the start of a way, under a point
  const labelled = mine.flatMap((shape): Feature<Point>[] => {
    if (!shape.label) return [];
    const kind = shape.closed ? 'area' : shape.kind === 'line' ? 'line' : 'point';
    const at =
      kind === 'area'
        ? northEdge(shape.points)
        : kind === 'line'
          ? (shape.points[0] ?? shape.labelAt)
          : shape.labelAt;
    return at
      ? [
          {
            type: 'Feature',
            properties: { id: shape.id ?? '', label: shape.label, kind },
            geometry: { type: 'Point', coordinates: at },
          },
        ]
      : [];
  });
  const heads = mine.flatMap((shape): Feature<Point>[] => {
    const tip = shape.points.at(-1);
    return shape.kind === 'line' && shape.role === 'path' && tip
      ? [
          {
            type: 'Feature',
            properties: { id: shape.id ?? '', b: endBearing(shape.points) },
            geometry: { type: 'Point', coordinates: tip },
          },
        ]
      : [];
  });
  return {
    shapes: collection(mine.map(toFeature)),
    labels: collection(labelled),
    heads: collection(heads),
  };
}

/** The middle of the northern edge of the box around a ring: where the caption of an area is set. */
export const northEdge = (points: readonly LngLat[]): LngLat => [
  (Math.min(...points.map((p) => p[0])) + Math.max(...points.map((p) => p[0]))) / 2,
  Math.max(...points.map((p) => p[1])),
];

/**
 * The tactical shapes, whoever drew them, as the plan draws its own: the shapes, the arrowheads at the end of the ways, and the
 * mark of a place of safety. `zoneName` is the caption of a zone the person drew; the assistant's zones have their own.
 */
export function tacticCollections(shapes: readonly Shape[], zoneName: string) {
  const tactical = shapes.filter((shape) => tacticOf(shape) !== null);
  const heads = tactical.flatMap((shape): Feature<Point>[] => {
    const tactic = tacticOf(shape);
    const tip = shape.points.at(-1);
    return (tactic === 'approach' || tactic === 'escape') && tip && shape.points.length >= 2
      ? [
          {
            type: 'Feature',
            properties: {
              id: shape.id ?? '',
              tactic,
              ai: shape.source === 'ai',
              b: endBearing(shape.points),
            },
            geometry: { type: 'Point', coordinates: tip },
          },
        ]
      : [];
  });
  const zones = tactical.filter((shape) => tacticOf(shape) === 'safe' && shape.closed);
  // the shield stands in the middle of the zone, its name on the edge: the assistant's zones have their caption from its own layer
  const marks = zones.map((shape): Feature<Point> => ({
    type: 'Feature',
    properties: { id: shape.id ?? '', ai: shape.source === 'ai' },
    geometry: { type: 'Point', coordinates: shape.labelAt ?? centroid(shape.points) },
  }));
  const names = zones
    .filter((shape) => shape.source !== 'ai')
    .map((shape): Feature<Point> => ({
      type: 'Feature',
      properties: { id: shape.id ?? '', text: zoneName },
      geometry: { type: 'Point', coordinates: northEdge(shape.points) },
    }));
  return {
    shapes: collection(tactical.map(toFeature)),
    heads: collection(heads),
    marks: collection(marks),
    names: collection(names),
  };
}
