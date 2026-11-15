import { describe, expect, it } from 'vitest';
import {
  centroid,
  circleAround,
  circleRing,
  distanceM,
  rectangleRing,
  thin,
  toLength,
  type LngLat,
} from './geometry';

const BUENOS_AIRES: LngLat = [-58.3816, -34.6037];
const CORDOBA: LngLat = [-64.1888, -31.4201];

describe('distanceM', () => {
  it('is the distance on the globe between two cities', () => {
    expect(distanceM(BUENOS_AIRES, CORDOBA) / 1000).toBeCloseTo(646, -1);
  });

  it('is zero from a point to itself and the same both ways', () => {
    expect(distanceM(CORDOBA, CORDOBA)).toBe(0);
    expect(distanceM(BUENOS_AIRES, CORDOBA)).toBeCloseTo(distanceM(CORDOBA, BUENOS_AIRES), 6);
  });
});

describe('circleRing', () => {
  it('is closed and every point is as far from the centre as the edge point', () => {
    const ring = circleRing(BUENOS_AIRES, CORDOBA);
    const radius = distanceM(BUENOS_AIRES, CORDOBA);
    expect(ring).toHaveLength(65);
    expect(ring[0]?.[0]).toBeCloseTo(ring[64]?.[0] ?? 0, 9);
    for (const point of ring) {
      expect(distanceM(BUENOS_AIRES, point) / radius).toBeCloseTo(1, 3);
    }
  });
});

describe('rectangleRing', () => {
  it('walks the four corners and comes back', () => {
    expect(rectangleRing([0, 0], [2, 3])).toEqual([
      [0, 0],
      [2, 0],
      [2, 3],
      [0, 3],
      [0, 0],
    ]);
  });
});

describe('toLength', () => {
  it.each([
    [42.4, 42, 'm'],
    [999.6, 1000, 'm'],
    [1000, 1, 'km'],
    [1260, 1.3, 'km'],
    [12_400, 12, 'km'],
  ])('%f m is %f %s', (metres, value, unit) => {
    expect(toLength(metres)).toEqual({ value, unit });
  });
});

describe('thin', () => {
  const ring = (count: number): [number, number][] =>
    Array.from({ length: count }, (_, index) => [index, index * 2]);

  it('leaves a short ring as it is', () => {
    expect(thin(ring(5))).toEqual(ring(5));
  });

  it('keeps at most the limit and both ends of a long one', () => {
    const long = ring(1000);
    const result = thin(long, 200);
    expect(result).toHaveLength(200);
    expect(result[0]).toEqual(long[0]);
    expect(result.at(-1)).toEqual(long.at(-1));
  });
});

describe('centroid', () => {
  it('is the middle of a box drawn as a closed ring, which names its first corner twice', () => {
    expect(centroid(rectangleRing([0, 0], [4, 2]))).toEqual([2, 1]);
  });

  it('is the middle of a circle, however many points it has', () => {
    const [x, y] = centroid(circleAround([-60, -30], 5));
    expect(x).toBeCloseTo(-60, 4);
    expect(y).toBeCloseTo(-30, 4);
  });

  it('weighs the surface, not the corners: a long side with many points does not pull it', () => {
    const ring: LngLat[] = [
      [0, 0],
      [1, 0],
      [2, 0],
      [3, 0],
      [4, 0],
      [4, 2],
      [0, 2],
    ];
    const [x, y] = centroid(ring);
    expect(x).toBeCloseTo(2, 5);
    expect(y).toBeCloseTo(1, 5);
  });

  it('is the mean of the corners for a ring with no surface', () => {
    expect(
      centroid([
        [0, 0],
        [2, 0],
      ]),
    ).toEqual([1, 0]);
  });
});
