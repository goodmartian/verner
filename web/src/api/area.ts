import { ApiError, api } from './client';
import type { AreaRef } from '../config/types';
import { areaId } from '../config/context';
import type { Attachment } from '../features/chat/attachments';
import { areaSelector } from './calendar';

/** The catalog id of an area, for the endpoints that take one. No polygon or saved area becomes a country. */
export function catalogId(ref: AreaRef | null): string {
  const id = areaId(ref);
  if (!id) throw new ApiError(0, 'unavailable', 'This endpoint needs a catalog area');
  return id;
}

/** The requests a drawn area can make too, by POST with its outline; the rest need a catalog id. */
const DRAWN = new Set<AreaRequest>(['month', 'map', 'days']);

export const supportsArea = (ref: AreaRef | null, request: AreaRequest): boolean =>
  areaId(ref) !== null || (ref !== null && 'polygon' in ref && DRAWN.has(request));

/** A drawn area goes by POST with its outline (made on each ask); a catalog area by GET, kept on the server. */
function byArea<A, B>(
  ref: AreaRef | null,
  drawn: (area: ReturnType<typeof areaSelector>) => Promise<A>,
  catalog: (id: string) => Promise<B>,
): Promise<A | B> {
  return ref && 'polygon' in ref ? drawn(areaSelector(ref)) : catalog(catalogId(ref));
}

/** All wire shapes of the area requests live here; hooks keep AreaRef throughout. */
export const areaRequests = {
  month: (ref: AreaRef | null, month: string) =>
    byArea(
      ref,
      (area) => api.POST('/api/calendar/month', { body: { area, month } }),
      (id) => api.GET('/api/calendar/month', { params: { query: { area: id, month } } }),
    ),
  map: (ref: AreaRef | null, month: string) =>
    byArea(
      ref,
      (area) => api.POST('/api/calendar/map', { body: { area, month } }),
      (id) => api.GET('/api/calendar/map', { params: { query: { area: id, month } } }),
    ),
  days: (ref: AreaRef | null, month: string) =>
    byArea(
      ref,
      (area) => api.POST('/api/calendar/days', { body: { area, month } }),
      (id) => api.GET('/api/calendar/days', { params: { query: { area: id, month } } }),
    ),
  firesOfDay: (ref: AreaRef | null, date: string) =>
    api.GET('/api/calendar/fires', { params: { query: { area: catalogId(ref), date } } }),
  fires: (ref: AreaRef | null, demo: boolean) =>
    api.GET('/api/fires', { params: { query: { region: catalogId(ref), demo } } }),
};

export type AreaRequest = keyof typeof areaRequests;

export function monthAttachment(item: Extract<Attachment, { kind: 'month' }>) {
  return {
    kind: 'month' as const,
    area: catalogId(typeof item.area === 'string' ? { id: item.area } : item.area),
    month: item.month,
  };
}
