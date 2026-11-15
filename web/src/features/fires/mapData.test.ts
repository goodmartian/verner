import { describe, expect, it } from 'vitest';
import { ACCESS_ROUTE, FIRE, FIRE_DETAIL, OTHER_FIRE, PLAN } from '../../test/fireFixtures';
import { fireCollections } from './mapData';

const base = {
  fires: [FIRE, OTHER_FIRE],
  selectedId: null,
  detail: null,
  plan: null,
  forecast: 0,
};

describe('fireCollections', () => {
  it('puts every fire on the map as a dot, the open one marked', () => {
    const { points } = fireCollections({ ...base, selectedId: FIRE.id });
    expect(points.features.map((f) => f.properties.selected)).toEqual([true, false]);
    expect(points.features[0]?.geometry).toEqual({ type: 'Point', coordinates: FIRE.center });
  });

  it('draws the way in as a road and a walk, with the start, only when the server gave the line', () => {
    expect(fireCollections(base).access.features).toHaveLength(0);
    const { access, accessStart } = fireCollections({ ...base, access: ACCESS_ROUTE });
    expect(access.features.map((f) => f.properties.kind)).toEqual(['road', 'walk']);
    expect(accessStart.features).toHaveLength(1);
    const noLine = fireCollections({ ...base, access: { ...ACCESS_ROUTE, road_path: null } });
    expect(noLine.access.features).toHaveLength(0);
    expect(noLine.accessStart.features).toHaveLength(0);
  });

  it('shows the forecast front only for the hours asked, and none by default', () => {
    expect(fireCollections({ ...base, detail: FIRE_DETAIL }).contours.features).toHaveLength(0);
    expect(
      fireCollections({ ...base, detail: FIRE_DETAIL, forecast: 3 }).contours.features,
    ).toHaveLength(0);
    expect(
      fireCollections({ ...base, detail: FIRE_DETAIL, forecast: 1 }).contours.features,
    ).toHaveLength(1);
  });

  it('draws every part of the forecast front, the holes of a part kept', () => {
    const square = (x: number, size: number) => [
      [x, 0],
      [x + size, 0],
      [x + size, size],
      [x, size],
      [x, 0],
    ];
    const detail = {
      ...FIRE_DETAIL,
      spread: FIRE_DETAIL.spread && {
        ...FIRE_DETAIL.spread,
        contours: [
          {
            hours: 3,
            polygons: [[square(0, 10), square(2, 2)], [square(20, 5)]],
            area_ha: 1,
            area_ha_low: 1,
            area_ha_high: 1,
          },
        ],
      },
    };
    const { contours } = fireCollections({ ...base, detail, forecast: 3 });
    expect(contours.features).toHaveLength(2);
    const [first, second] = contours.features.map((feature) => feature.geometry);
    if (first?.type !== 'Polygon' || second?.type !== 'Polygon')
      throw new Error('parts are polygons');
    expect(first.coordinates).toHaveLength(2);
    expect(second.coordinates).toHaveLength(1);
  });

  it('keeps the detections of the last two passes, the last one marked', () => {
    const detail = {
      ...FIRE_DETAIL,
      pass_index: 2,
      detections: [0, 1, 2, 2].map((pass) => ({
        position: [-56.1, -28.46],
        pass_index: pass,
        frp_mw: 10,
      })),
    };
    const { detections } = fireCollections({ ...base, detail });
    expect(detections.features.map((f) => f.properties.now)).toEqual([false, true, true]);
  });

  it('draws a plan: a way in and out for a crew that goes, only a way in for one left out, an arrowhead trail', () => {
    const { planLines, planPins, planHeads } = fireCollections({
      ...base,
      detail: FIRE_DETAIL,
      plan: PLAN,
    });
    expect(planLines.features.map((f) => f.properties.kind)).toEqual([
      'attack',
      'escape',
      'blocked',
    ]);
    // one dot for each place where crews enter
    expect(planPins.features.map((f) => f.properties.kind)).toEqual(['entry', 'entry']);
    // two arrowheads at least along every way of a crew that goes, none along a way that is left out
    expect(planHeads.features.length).toBeGreaterThanOrEqual(4);
    expect(planHeads.features.every((f) => f.properties.kind !== 'blocked')).toBe(true);
  });
});
