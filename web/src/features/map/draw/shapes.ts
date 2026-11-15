import type { Feature, LineString, Point, Polygon } from 'geojson';
import type { LngLat } from './geometry';

export type ShapeKind =
  'rectangle' | 'circle' | 'polygon' | 'ruler' | 'pencil' | 'approach' | 'escape' | 'safe';
/** What a tactical shape means, whoever drew it: the way to the fire, the way out of it, the place of safety. */
export type Tactic = 'approach' | 'escape' | 'safe';
/** A mark of the operator for the crews: where to enter, or what to put out. */
export type MarkKind = 'entry' | 'hot';

export interface Shape {
  /** `line` and `point` are only ever drawn by the assistant. */
  kind: ShapeKind | MarkKind | 'line' | 'point';
  /** The name of a shape that can be asked about: `U1`, `U2` of the person; `A1`, `A2` of the assistant; open lines of the person have none. */
  id?: string;
  /** The ring of a closed shape (its outer one), or the vertices of an open line. */
  points: LngLat[];
  closed: boolean;
  /** The holes of a closed shape. */
  holes?: LngLat[][];
  /** Drawn by the assistant, not by the person. */
  source?: 'ai';
  label?: string;
  note?: string;
  /** Where the assistant's caption goes. */
  labelAt?: LngLat;
  /** An assistant's line that is a way to go has an arrow at its end; the tactical ones are named too. */
  role?: 'path' | 'line' | 'approach' | 'escape' | 'safe_zone';
}

export const isMark = (shape: Shape): shape is Shape & { kind: MarkKind } =>
  shape.kind === 'entry' || shape.kind === 'hot';

/** The tactical meaning of a shape, which gives it the look of the plan whoever drew it; null for a plain drawing. */
export function tacticOf(shape: Shape): Tactic | null {
  if (shape.kind === 'approach' || shape.kind === 'escape' || shape.kind === 'safe')
    return shape.kind;
  if (shape.role === 'approach' || shape.role === 'escape') return shape.role;
  return shape.role === 'safe_zone' ? 'safe' : null;
}

export const isAi = (shape: Shape): boolean => shape.source === 'ai';

export function toFeature(shape: Shape): Feature<Polygon | LineString | Point> {
  const tactic = tacticOf(shape);
  const properties = {
    ...(shape.id ? { id: shape.id } : {}),
    ...(tactic ? { tactic } : {}),
    ai: shape.source === 'ai',
  };
  if (shape.kind === 'point') {
    return {
      type: 'Feature',
      properties,
      geometry: { type: 'Point', coordinates: shape.points[0] ?? [0, 0] },
    };
  }
  return {
    type: 'Feature',
    properties,
    geometry: shape.closed
      ? { type: 'Polygon', coordinates: [shape.points, ...(shape.holes ?? [])] }
      : { type: 'LineString', coordinates: shape.points },
  };
}
