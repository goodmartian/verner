import { describe, expect, it } from 'vitest';
import { activeSection } from './sections';

// heads of four sections in the scrolled content, counted from the bottom of the sticky bar when the scroll is 0
const heads = [
  { id: 'overview', top: 0 },
  { id: 'calendar', top: 260 },
  { id: 'trend', top: 860 },
  { id: 'season', top: 1260 },
] as const;
const HEIGHT = 600;
const TOTAL = 2000;
const at = (scroll: number) =>
  activeSection(
    heads.map((h) => ({ ...h, top: h.top - scroll })),
    scroll,
    HEIGHT,
    TOTAL,
  );

describe('the section the bar lights', () => {
  it('is the first one at the top, even when the next head is already in view', () => {
    expect(at(0)).toBe('overview');
    expect(at(7)).toBe('overview');
  });
  it('is the last one at the foot, however short it is', () => {
    expect(at(TOTAL - HEIGHT)).toBe('season');
    expect(at(TOTAL - HEIGHT - 8)).toBe('season');
  });
  it('is the section that holds the point a third of the way down the box', () => {
    // the point is 200 below the bar: the calendar head (260) is lit once it has climbed above it
    expect(at(50)).toBe('overview');
    expect(at(60)).toBe('calendar');
    expect(at(600)).toBe('calendar');
    expect(at(660)).toBe('trend');
    expect(at(1060)).toBe('season');
  });
  it('lights a section just after its head passes the point', () => {
    expect(at(59)).toBe('overview');
    expect(at(60)).toBe('calendar');
  });
  it('has none when there are no sections', () => {
    expect(activeSection([], 0, HEIGHT, TOTAL)).toBeNull();
  });
});
