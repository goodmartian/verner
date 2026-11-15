import { useQuery } from '@tanstack/react-query';
import { api, ApiError, call } from '../../api/client';
import type { AreaRef } from '../../config/types';
import { areaId } from '../../config/context';
import { useAreaFlags } from '../calendar/areas';
import { areaRequests, catalogId, supportsArea } from '../../api/area';

type Reply<T> = Parameters<typeof call<T>>[0];

/** The answer, or null when the server says the data is not there yet (404); the weather artifacts arrive one after the other. */
export async function orAbsent<T>(request: Reply<T>): Promise<T | null> {
  try {
    return await call(request);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

const TEN_MINUTES = 10 * 60_000;

/** The climate endpoints accept catalog IDs only. */
export function useClimateArea(area: AreaRef | null): AreaRef | null {
  return useAreaFlags().covered === true && areaId(area) !== null ? area : null;
}

/** The area whose days of a month are asked for: a covered catalog area, or a drawn one. */
export function useDaysArea(area: AreaRef | null): AreaRef | null {
  const covered = useClimateArea(area);
  return areaId(area) === null && supportsArea(area, 'days') ? area : covered;
}

/** What there is of the weather of months, its layers, bands and credits; null while nothing is published. */
export const useClimateLegend = (enabled = true) =>
  useQuery({
    enabled,
    queryKey: ['climate', 'legend'],
    queryFn: () => orAbsent(api.GET('/api/climate/legend')),
    staleTime: TEN_MINUTES,
  });

/** The weather of a month in an area; null when the server has none for it (404). `kind: none` is an answer too. */
export const useClimateMonth = (month: string | null, area: AreaRef | null) =>
  useQuery({
    enabled: month !== null && area !== null,
    queryKey: ['climate', 'month', area, month],
    // the line of the month before stays until the next comes: the strip keeps its height
    placeholderData: (previous, query) =>
      query && JSON.stringify(query.queryKey[2]) === JSON.stringify(area) ? previous : undefined,
    queryFn: () => {
      if (!month || !area) throw new Error('no month yet');
      return orAbsent(
        api.GET('/api/climate/month', { params: { query: { area: catalogId(area), month } } }),
      );
    },
    staleTime: TEN_MINUTES,
  });

/** The days of a month that had fires. */
export const useMonthDays = (month: string | null, area: AreaRef | null) =>
  useQuery({
    enabled: month !== null && area !== null,
    queryKey: ['calendar', 'days', area, month],
    // the days of the month before stay until the next come: the card keeps its height; only another area starts from nothing
    placeholderData: (previous, query) =>
      query && JSON.stringify(query.queryKey[2]) === JSON.stringify(area) ? previous : undefined,
    queryFn: () => {
      if (!month || !area) throw new Error('no month yet');
      return orAbsent(areaRequests.days(area, month));
    },
    staleTime: TEN_MINUTES,
  });

/** The clusters of fires of a day, the biggest first. */
export const useDayFires = (date: string | null, area: AreaRef | null) =>
  useQuery({
    enabled: date !== null && area !== null,
    queryKey: ['calendar', 'fires', area, date],
    queryFn: () => {
      if (!date || !area) throw new Error('no day yet');
      return orAbsent(areaRequests.firesOfDay(area, date));
    },
    staleTime: TEN_MINUTES,
  });

/** The corners of the picture of the layer of months. */
export const useClimateBounds = (enabled: boolean) =>
  useQuery({
    enabled,
    queryKey: ['climate', 'bounds'],
    queryFn: () => orAbsent(api.GET('/api/climate/grid/bounds')),
    staleTime: TEN_MINUTES,
  });
