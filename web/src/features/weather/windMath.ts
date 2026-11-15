/** West, south, east, north in degrees. */
export type Box = readonly [number, number, number, number];

/** The most particles the state texture holds: 128 by 128. */
export const MAX_PARTICLES = 128 * 128;
/** The zoom beyond which the steps of a particle are finer than its position can say, and the particles are not drawn. */
export const MAX_ZOOM = 9;

/** The part of the wind field in view, as a box over the field with (0, 0) at its north-west corner; null when none is in view. */
export function viewOnField(view: Box, field: Box): [number, number, number, number] | null {
  const [w, s, e, n] = field;
  const west = Math.max(view[0], w);
  const south = Math.max(view[1], s);
  const east = Math.min(view[2], e);
  const north = Math.min(view[3], n);
  if (west >= east || south >= north) return null;
  return [(west - w) / (e - w), (n - north) / (n - s), (east - w) / (e - w), (n - south) / (n - s)];
}

const mercatorY = (lat: number) =>
  0.5 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / (2 * Math.PI);

/** The area in pixels of a box of the map at a zoom (the world is `512 * 2 ** zoom` pixels wide). */
export function boxPixels(box: Box, zoom: number): number {
  const world = 512 * 2 ** zoom;
  return ((box[2] - box[0]) / 360) * world * (mercatorY(box[1]) - mercatorY(box[3])) * world;
}

/** One particle for each so many pixels of the field in view, kept within what is worth drawing. */
export const PIXELS_PER_PARTICLE = 185;
export const MIN_PARTICLES = 900;

export function particleCount(pixels: number): number {
  return Math.min(MAX_PARTICLES, Math.max(MIN_PARTICLES, Math.round(pixels / PIXELS_PER_PARTICLE)));
}

/** Frames a second the particles are meant to keep. */
export const FPS_LOW = 45;
export const FPS_HIGH = 58;
export const MIN_SHARE = 0.25;

/** The share of the particles to draw after a stretch of frames at `fps`: fewer when the frames are slow, back up when they are quick. */
export function adapt(share: number, fps: number): number {
  if (fps < FPS_LOW) return Math.max(MIN_SHARE, share * 0.8);
  if (fps > FPS_HIGH) return Math.min(1, share * 1.05);
  return share;
}

/** The picture of the wind field of an hour. */
export function fieldAddress(hour: string): string {
  const url = new URL('/api/weather/wind-field.png', window.location.origin);
  url.search = new URLSearchParams({ time: hour }).toString();
  return url.href;
}
