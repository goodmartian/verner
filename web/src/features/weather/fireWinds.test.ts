import { describe, expect, it } from 'vitest';
import type { FireWeather, WeatherLegend } from '../../api/types';
import { contrast, legibleOn, MAP_GROUND } from './contrast';
import { fireWinds, windCollection } from './fireWinds';

const legend = {
  layers: [
    {
      layer: 'wind',
      bands: [
        { id: 0, color: '#d9f0fb' },
        { id: 1, color: '#8fd0ef' },
      ],
    },
  ],
} as unknown as WeatherLegend;

const weather = {
  available: true,
  start: '2026-10-27T00:00:00Z',
  hours: 3,
  fires: [
    {
      fire_id: '20261028-1',
      position: [-56.09, -28.46],
      speed_kmh: [3, 12, 14],
      from_deg: [10, 128, 300],
      wind_category: [0, 1, 1],
    },
  ],
} as unknown as FireWeather;

const listed = new Set(['20261028-1']);

describe('fireWinds', () => {
  it('turns the arrow to where the wind blows and colours it by its band', () => {
    expect(fireWinds(weather, legend, '2026-10-27T01:00:00Z', listed)).toEqual([
      { id: '20261028-1', at: [-56.09, -28.46], to: 308, speed: 12, color: legibleOn('#8fd0ef') },
    ]);
  });

  it('wraps the direction past north', () => {
    expect(fireWinds(weather, legend, '2026-10-27T02:00:00Z', listed)[0]?.to).toBe(120);
  });

  it('has no mark for an hour the series does not reach', () => {
    expect(fireWinds(weather, legend, '2026-10-27T03:00:00Z', listed)).toEqual([]);
  });

  it('leaves out fires that are not in the list', () => {
    expect(fireWinds(weather, legend, '2026-10-27T01:00:00Z', new Set())).toEqual([]);
  });

  it('has nothing before the data is there', () => {
    expect(fireWinds(undefined, legend, '2026-10-27T01:00:00Z', listed)).toEqual([]);
    expect(
      fireWinds({ ...weather, available: false }, legend, '2026-10-27T01:00:00Z', listed),
    ).toEqual([]);
  });
});

describe('the colour of a mark', () => {
  it('stands out from the map by three to one, however pale the band of the legend is', () => {
    const [mark] = fireWinds(weather, legend, '2026-10-27T00:00:00Z', listed);
    expect(contrast(mark?.color ?? '#ffffff', MAP_GROUND)).toBeGreaterThanOrEqual(3);
  });
});

describe('windCollection', () => {
  it('writes each mark as a point with its turn, colour and the speed as text', () => {
    const winds = fireWinds(weather, legend, '2026-10-27T01:00:00Z', listed);
    expect(windCollection(winds, (speed) => `${String(speed)} km/h`).features).toEqual([
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [-56.09, -28.46] },
        properties: {
          id: '20261028-1',
          to: 308,
          speed: 12,
          color: legibleOn('#8fd0ef'),
          label: '12 km/h',
        },
      },
    ]);
  });
});
