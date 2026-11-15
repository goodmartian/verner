import { createContext, useContext } from 'react';
import type { AppConfig, AreaFlags, AreaRef, Bbox } from './types';

export const ConfigContext = createContext<AppConfig | null>(null);
export const useConfig = () => useContext(ConfigContext);

export const areaId = (area: AreaRef | null): string | null =>
  area && 'id' in area ? area.id : null;

export function polygonBbox(area: AreaRef | null): Bbox | null {
  if (!area || !('polygon' in area)) return null;
  const points =
    area.polygon.type === 'Polygon'
      ? area.polygon.coordinates.flat()
      : area.polygon.coordinates.flat(2);
  if (!points.length) return null;
  const lng = points.map((point) => point[0] ?? 0);
  const lat = points.map((point) => point[1] ?? 0);
  return [Math.min(...lng), Math.min(...lat), Math.max(...lng), Math.max(...lat)];
}

export function areaFlags(config: AppConfig | null, area: AreaRef | null): AreaFlags {
  const known =
    config?.areas.find((item) => item.id === areaId(area)) ??
    config?.countries.find((item) => item.id === areaId(area));
  if (known) return known;
  // A bounding box cannot establish a polygon's coverage or its time zone.
  return { covered: null, bbox: polygonBbox(area), timezone: null };
}
