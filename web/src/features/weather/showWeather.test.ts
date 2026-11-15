import { describe, expect, it } from 'vitest';
import { weatherView } from './showWeather';

describe('weatherView', () => {
  it('opens the fire, switches the layers on and puts the player at the hour', () => {
    expect(
      weatherView({
        type: 'show_weather',
        fire_id: '20261028-1',
        layers: ['rain', 'dryness'],
        hour: '2026-10-30T14:00:00',
      }),
    ).toEqual({
      fireId: '20261028-1',
      layers: ['rain', 'dryness'],
      wind: false,
      clock: '2026-10-30T14:00:00Z',
    });
  });

  it('takes the wind as the arrows over the map, not as a picture', () => {
    expect(
      weatherView({ type: 'show_weather', fire_id: null, layers: ['wind', 'rain'], hour: null }),
    ).toEqual({
      fireId: null,
      layers: ['rain'],
      wind: true,
      clock: null,
    });
  });

  it('leaves alone what it is not asked to change, and keeps a Z that is there', () => {
    expect(weatherView({ type: 'show_weather', fire_id: null, layers: null, hour: null })).toEqual({
      fireId: null,
      layers: [],
      wind: false,
      clock: null,
    });
    expect(
      weatherView({
        type: 'show_weather',
        fire_id: null,
        layers: null,
        hour: '2026-10-30T14:00:00Z',
      }).clock,
    ).toBe('2026-10-30T14:00:00Z');
  });
});
