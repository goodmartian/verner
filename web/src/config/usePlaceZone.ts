import { useAreaFlags } from '../features/calendar/areas';
import { readZone } from './load';

export function placeZone(value: unknown, areaZone: string | null): string | null {
  if (value && typeof value === 'object') {
    if ('timezone' in value) {
      const zone = readZone(value.timezone);
      if (zone) return zone;
    }
    if ('summary' in value) return placeZone(value.summary, areaZone);
  }
  return areaZone;
}

export function usePlaceZone(value?: unknown): string | null {
  return placeZone(value, useAreaFlags().timezone);
}
