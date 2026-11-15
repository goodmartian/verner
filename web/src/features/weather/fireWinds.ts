import type { FeatureCollection, Point } from 'geojson';
import type { FireWeather, WeatherLegend } from '../../api/types';
import type { LngLat } from '../map/draw/geometry';
import { legibleOn } from './contrast';
import { seriesIndex } from './time';

/** The wind at one fire: what its marker on the map says. */
export interface FireWind {
  id: string;
  at: LngLat;
  /** Where the wind blows to, degrees from north: the arrow's turn. */
  to: number;
  speed: number;
  color: string;
}

/** The marks for the fires in the list, at an hour; a fire whose series does not reach the hour has none. */
export function fireWinds(
  weather: FireWeather | undefined,
  legend: WeatherLegend | undefined,
  hour: string,
  listed: ReadonlySet<string>,
): FireWind[] {
  if (!weather?.available) return [];
  const bands = legend?.layers.find((layer) => layer.layer === 'wind')?.bands ?? [];
  return weather.fires.flatMap((series) => {
    const index = seriesIndex(weather.start, series.speed_kmh.length, hour);
    const [lng, lat] = series.position;
    const speed = index === null ? undefined : series.speed_kmh[index];
    const from = index === null ? undefined : series.from_deg[index];
    const category = index === null ? undefined : series.wind_category[index];
    const color = bands.find((band) => band.id === category)?.color;
    if (
      !listed.has(series.fire_id) ||
      speed === undefined ||
      from === undefined ||
      color === undefined ||
      lng === undefined ||
      lat === undefined
    ) {
      return [];
    }
    // a pale band is darkened until the arrow stands out from the map
    return [
      {
        id: series.fire_id,
        at: [lng, lat],
        to: (from + 180) % 360,
        speed,
        color: legibleOn(color),
      },
    ];
  });
}

/** The marks as points for a symbol layer: an arrow turned to `to`, in `color`, with the speed written as `label`. */
export function windCollection(
  winds: readonly FireWind[],
  label: (speed: number) => string,
): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: winds.map((wind) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [...wind.at] },
      properties: {
        id: wind.id,
        to: wind.to,
        speed: wind.speed,
        color: wind.color,
        label: label(wind.speed),
      },
    })),
  };
}
