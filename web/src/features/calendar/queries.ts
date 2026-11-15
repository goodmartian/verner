import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api, call } from '../../api/client';
import { useBoard } from '../board/context';
import { areaRequests, supportsArea } from '../../api/area';
import { calendar, meta } from '../../api/calendar';
import { yearOf, type Month, type MonthRange } from './months';
import { sameDates } from './sameDates';
import { areaId, useConfig } from '../../config/context';

const FOREVER = { staleTime: Infinity } as const;

/** The countries of the catalog; `demo` counts the fires of the example in `fires_now`. The regions of a country come with `useCountryRegions`. */
export const useRegions = (demo = false) =>
  useQuery({
    queryKey: ['regions', demo],
    queryFn: () => call(api.GET('/api/regions', { params: { query: { demo } } })),
    retry: false,
    ...FOREVER,
  });

/** A country and its regions, once there is a country to ask about. */
export const useCountryRegions = (country: string | null, demo = false) =>
  useQuery({
    enabled: country !== null,
    queryKey: ['regions', demo, country],
    queryFn: () =>
      call(api.GET('/api/regions', { params: { query: { demo, country: country ?? undefined } } })),
    retry: false,
    ...FOREVER,
  });

const calendarOf = (area: ReturnType<typeof useBoard>['area'], range: MonthRange | null) => ({
  enabled: area !== null,
  queryKey: ['calendar', area, range] as const,
  select: sameDates,
  // the board of the period or area before stays until the next answer comes, so the board does not collapse and jump
  placeholderData: keepPreviousData,
  queryFn: ({ signal }: { signal: AbortSignal }) => {
    if (!area) throw new Error('No area');
    return calendar(area, range, signal);
  },
  retry: false,
  staleTime: 10 * 60 * 1000,
});

/** The calendar of the area on the board for the period chosen; without one the server gives the whole record and the forecast. */
export function useCalendar() {
  const { area, range } = useBoard();
  return useQuery(calendarOf(area, range));
}

/**
 * The whole record of the area, whatever the period: the cards that have periods of their own (the months over time,
 * the burning calendar) read it, so a period of one month does not leave them one point. With no period chosen it is
 * the very query of the board, so nothing is asked twice; it does not change with the period.
 */
export function useRecord() {
  const { area } = useBoard();
  return useQuery(calendarOf(area, null));
}

/** The satellites, the date the archive is complete through, the known seasons. */
export const useMeta = () =>
  useQuery({
    queryKey: ['meta'],
    queryFn: ({ signal }) => meta(signal),
    retry: false,
    staleTime: 24 * 60 * 60 * 1000,
  });

/** The period to show: the one chosen, or else the record from the first month to the current one. */
export function useRange(): {
  range: MonthRange | null;
  limits: MonthRange | null;
} {
  const { range } = useBoard();
  const config = useConfig();
  const data = useCalendar().data;
  const years = config?.archive_years ?? [];
  const archive = years.length
    ? { from: `${String(Math.min(...years))}-01`, to: `${String(Math.max(...years))}-12` }
    : data
      ? { from: data.first_month, to: data.current_month.month }
      : null;
  return {
    range: range ?? (data ? { from: data.first_month, to: data.current_month.month } : archive),
    limits: archive,
  };
}

/**
 * The month on the map: the one picked, or the last seen of the period. With years side by side it is
 * a month of one of them, the same month of the year first in line unless another was picked.
 */
export function usePicked(): Month | null {
  const { pick, years } = useBoard();
  const { range } = useRange();
  const series = useCalendar().data?.series;
  const [first] = years;
  if (years.length >= 2 && first !== undefined) {
    if (pick && years.includes(yearOf(pick))) return pick;
    return `${String(first)}-${(pick ?? range?.from ?? '0000-01').slice(5)}`;
  }
  if (pick) return pick;
  // nothing is picked before the calendar is there: the month is the last of the period that was seen, or the first one ahead
  if (!series) return null;
  const seen = series.filter((point) => point.count !== null).at(-1);
  return seen?.month ?? range?.from ?? null;
}

/** The id of the chosen area when it is a country of the catalog (the one whose regions the server lists), else null. */
export const useCountryArea = (): string | null => {
  const { area } = useBoard();
  const regions = useRegions().data?.regions;
  const id = areaId(area);
  return id !== null && regions?.some((item) => item.id === id && item.kind === 'country')
    ? id
    : null;
};

export const useProvinces = (sort: 'total' | 'ratio' | 'name') => {
  const { range } = useRange();
  const country = useCountryArea();
  return useQuery({
    enabled: range !== null && country !== null,
    queryKey: ['provinces', country, range, sort],
    // the table of the period before stays until the next comes, so the board does not jump
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === country ? previous : undefined,
    queryFn: () => {
      if (!range || !country) throw new Error('no period or country yet');
      return call(
        api.GET('/api/calendar/provinces', {
          params: { query: { area: country, from: range.from, to: range.to, sort } },
        }),
      );
    },
  });
};

export const useMonth = () => {
  const { area } = useBoard();
  const month = usePicked();
  return useQuery({
    enabled: month !== null && supportsArea(area, 'month'),
    queryKey: ['month', area, month],
    // the month before stays until the next comes: only another area starts from nothing
    placeholderData: (previous, query) =>
      query && JSON.stringify(query.queryKey[1]) === JSON.stringify(area) ? previous : undefined,
    queryFn: () => {
      if (!month) throw new Error('no month');
      return call(areaRequests.month(area, month));
    },
  });
};

export const useCellMap = (enabled: boolean) => {
  const { area } = useBoard();
  const month = usePicked();
  return useQuery({
    enabled: enabled && month !== null && supportsArea(area, 'map'),
    queryKey: ['cells', area, month],
    // the map of the month before stays on the screen until the next comes
    placeholderData: (previous, query) =>
      query && JSON.stringify(query.queryKey[1]) === JSON.stringify(area) ? previous : undefined,
    queryFn: () => {
      if (!month) throw new Error('no month');
      return call(areaRequests.map(area, month));
    },
  });
};
