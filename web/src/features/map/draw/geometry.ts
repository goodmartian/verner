export type LngLat = [number, number];

const EARTH_RADIUS_M = 6_371_008.8;
const rad = (deg: number) => (deg * Math.PI) / 180;
const deg = (radians: number) => (radians * 180) / Math.PI;

/** The four corners of the box with opposite corners `a` and `b`, as a closed ring. */
export function rectangleRing(a: LngLat, b: LngLat): LngLat[] {
  return [a, [b[0], a[1]], b, [a[0], b[1]], a];
}

/** Straight-line distance on the globe, in metres. */
export function distanceM(a: LngLat, b: LngLat): number {
  const dLat = rad(b[1] - a[1]);
  const dLng = rad(b[0] - a[0]);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** A circle around `center` that passes through `edge`, as a closed ring of `steps` points. */
export function circleRing(center: LngLat, edge: LngLat, steps = 64): LngLat[] {
  return ringAround(center, distanceM(center, edge) / EARTH_RADIUS_M, steps);
}

/** A circle of `km` kilometres around `center`, as a closed ring. */
export const circleAround = (center: LngLat, km: number, steps = 64): LngLat[] =>
  ringAround(center, (km * 1000) / EARTH_RADIUS_M, steps);

function ringAround(center: LngLat, angular: number, steps: number): LngLat[] {
  const lat = rad(center[1]);
  const lng = rad(center[0]);
  const ring: LngLat[] = [];
  for (let i = 0; i <= steps; i++) {
    const bearing = (i / steps) * 2 * Math.PI;
    const toLat = Math.asin(
      Math.sin(lat) * Math.cos(angular) + Math.cos(lat) * Math.sin(angular) * Math.cos(bearing),
    );
    const toLng =
      lng +
      Math.atan2(
        Math.sin(bearing) * Math.sin(angular) * Math.cos(lat),
        Math.cos(angular) - Math.sin(lat) * Math.sin(toLat),
      );
    ring.push([deg(toLng), deg(toLat)]);
  }
  return ring;
}

/**
 * The centre of the surface a closed ring encloses (the closing point may be given or not). For a box or a circle it is
 * their middle; a ring with no surface falls back to the mean of its corners.
 */
export function centroid(ring: readonly LngLat[]): LngLat {
  const corners =
    ring.length > 1 && ring[0]?.[0] === ring.at(-1)?.[0] && ring[0]?.[1] === ring.at(-1)?.[1]
      ? ring.slice(0, -1)
      : ring;
  let area = 0;
  let x = 0;
  let y = 0;
  corners.forEach((a, index) => {
    const b = corners[(index + 1) % corners.length];
    if (!b) return;
    const cross = a[0] * b[1] - b[0] * a[1];
    area += cross;
    x += (a[0] + b[0]) * cross;
    y += (a[1] + b[1]) * cross;
  });
  if (Math.abs(area) < 1e-12) {
    const n = Math.max(1, corners.length);
    return [corners.reduce((s, p) => s + p[0], 0) / n, corners.reduce((s, p) => s + p[1], 0) / n];
  }
  return [x / (3 * area), y / (3 * area)];
}

export interface Length {
  value: number;
  unit: 'm' | 'km';
}

/** Metres below a kilometre, kilometres above it (one decimal under ten). */
export function toLength(metres: number): Length {
  if (metres < 1000) return { value: Math.round(metres), unit: 'm' };
  const km = metres / 1000;
  return { value: km < 10 ? Math.round(km * 10) / 10 : Math.round(km), unit: 'km' };
}

/** Rounds the corners of an open way, its two ends kept: a path as it is drawn, not as it was measured. */
export function smoothPath(path: readonly LngLat[], rounds = 3): LngLat[] {
  let points = [...path];
  for (let round = 0; round < rounds && points.length > 2; round++) {
    const last = points[points.length - 1];
    const first = points[0];
    if (!first || !last) break;
    points = [
      first,
      ...points.slice(0, -1).flatMap((a, index): LngLat[] => {
        const b = points[index + 1];
        return b
          ? [
              [0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]],
              [0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]],
            ]
          : [];
      }),
      last,
    ];
  }
  return points;
}

/** A straight way of two points bows a little, so that it reads as a path and not as a ruler line. */
export function bow(path: readonly LngLat[]): LngLat[] {
  const [a, b] = path;
  if (path.length !== 2 || !a || !b) return [...path];
  return [
    a,
    [(a[0] + b[0]) / 2 + (b[1] - a[1]) * 0.15, (a[1] + b[1]) / 2 - (b[0] - a[0]) * 0.15],
    b,
  ];
}

/** At most `max` points of a ring, evenly spread, the first and the last kept; the api takes no more than 200. */
export function thin(ring: readonly LngLat[], max = 200): [number, number][] {
  if (ring.length <= max) return ring.map(([lng, lat]) => [lng, lat]);
  const step = (ring.length - 1) / (max - 1);
  return Array.from({ length: max }, (_, index) => {
    const [lng, lat] = ring[Math.round(index * step)] ?? ring[0] ?? [0, 0];
    return [lng, lat];
  });
}
