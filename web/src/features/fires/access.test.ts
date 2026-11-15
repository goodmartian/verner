import { describe, expect, it } from 'vitest';
import { ACCESS_ROUTE } from '../../test/fireFixtures';
import { en } from '../../i18n/en';
import { accessText, joinCredits } from './access';

const t = (key: keyof typeof en, params?: Record<string, string | number>) =>
  Object.entries(params ?? {}).reduce(
    (text: string, [name, value]) => text.replace(`{${name}}`, String(value)),
    en[key],
  );

describe('accessText', () => {
  it('names a station as a station', () => {
    const text = accessText(t, 'en', {
      ...ACCESS_ROUTE,
      origin_kind: 'station',
      station_name: 'Bomberos',
    });
    expect(text).toBe('77 min by road, 31 km from fire station Bomberos, on foot 4.4 km');
  });

  it('does not call a place a station', () => {
    expect(accessText(t, 'en', ACCESS_ROUTE)).not.toContain('station');
  });

  it('leaves the walk out when there is none', () => {
    expect(accessText(t, 'en', { ...ACCESS_ROUTE, walk_km: 0 })).toBe(
      '77 min by road, 31 km from Villa Ocampo',
    );
  });
});

describe('joinCredits', () => {
  it('says a shared sentence once and skips what is missing', () => {
    expect(
      joinCredits([
        'Fire detections: NASA FIRMS. Places: GeoNames.',
        null,
        'Roads: OSM. Places: GeoNames.',
      ]),
    ).toBe('Fire detections: NASA FIRMS. Places: GeoNames. Roads: OSM.');
    expect(joinCredits([null, undefined])).toBeNull();
  });
});
