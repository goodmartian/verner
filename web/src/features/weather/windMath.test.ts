import { describe, expect, it } from 'vitest';
import {
  adapt,
  boxPixels,
  FPS_HIGH,
  FPS_LOW,
  MAX_PARTICLES,
  MIN_PARTICLES,
  MIN_SHARE,
  particleCount,
  viewOnField,
} from './windMath';

const FIELD = [-75.125, -57.125, -51.875, -19.875] as const;

describe('viewOnField', () => {
  it('is the whole field when the view holds it', () => {
    expect(viewOnField([-80, -60, -50, -10], FIELD)).toEqual([0, 0, 1, 1]);
  });

  it('is the part in view, with the north-west corner as the origin', () => {
    const [x0, y0, x1, y1] = viewOnField([-63.5, -38.5, -51.875, -19.875], FIELD) ?? [];
    expect(x0).toBeCloseTo(0.5, 5);
    expect(x1).toBe(1);
    expect(y0).toBe(0);
    expect(y1).toBeCloseTo(0.5, 5);
  });

  it('is nothing when the view is off the field', () => {
    expect(viewOnField([-30, -40, -20, -30], FIELD)).toBeNull();
    expect(viewOnField([-80, -10, -70, 0], FIELD)).toBeNull();
  });
});

describe('boxPixels', () => {
  it('is four times the area for a zoom one deeper', () => {
    const box = [-70, -40, -60, -30] as const;
    expect(boxPixels(box, 6) / boxPixels(box, 5)).toBeCloseTo(4, 5);
  });
});

describe('particleCount', () => {
  it('grows with the pixels of the field in view, within its limits', () => {
    expect(particleCount(0)).toBe(MIN_PARTICLES);
    expect(particleCount(700_000)).toBeGreaterThan(particleCount(300_000));
    expect(particleCount(1e9)).toBe(MAX_PARTICLES);
  });
});

describe('adapt', () => {
  it('draws fewer particles when the frames are slow, never fewer than a quarter', () => {
    expect(adapt(1, FPS_LOW - 1)).toBeCloseTo(0.8, 5);
    let share = 1;
    for (let i = 0; i < 40; i += 1) share = adapt(share, 10);
    expect(share).toBe(MIN_SHARE);
  });

  it('brings them back when the frames are quick, never more than all', () => {
    expect(adapt(0.5, FPS_HIGH + 1)).toBeGreaterThan(0.5);
    expect(adapt(1, 60)).toBe(1);
  });

  it('leaves them while the frames are about as quick as wanted', () => {
    expect(adapt(0.7, 50)).toBe(0.7);
  });
});
