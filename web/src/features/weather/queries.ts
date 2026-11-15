import { useQuery } from '@tanstack/react-query';
import { api, ApiError, call } from '../../api/client';
import type { WeatherAt } from '../../api/types';

const TEN_MINUTES = 10 * 60_000;

/** The bands, units and credits of the weather layers, and the hours the data covers. */
export const useWeatherLegend = (enabled = true) =>
  useQuery({
    enabled,
    queryKey: ['weather', 'legend'],
    queryFn: () => call(api.GET('/api/weather/legend')),
    staleTime: TEN_MINUTES,
  });

/** Which fires the weather is asked for: those of a region, those with these ids, or all when neither is given. */
export interface FireWeatherFilter {
  region?: string | null;
  ids?: readonly string[];
}

/** The weather at every live fire, hour by hour. */
export const useFireWeather = (enabled: boolean, only: FireWeatherFilter = {}) =>
  useQuery({
    enabled,
    queryKey: ['weather', 'fires', only.region ?? null, only.ids ?? null],
    queryFn: ({ signal }) =>
      call(
        api.GET('/api/weather/fires', {
          signal,
          // the server narrows the answer to a region or to fires by id; every fire of the world is megabytes
          // (the generated schema does not list the two parameters yet)
          params: {
            query: {
              ...(only.region ? { region: only.region } : {}),
              ...(only.ids ? { ids: only.ids.join(',') } : {}),
            },
          } as never,
        }),
      ),
    staleTime: TEN_MINUTES,
    refetchInterval: 30 * 60_000,
  });

/** The corners of the pictures of the layers. */
export const useGridBounds = (enabled: boolean) =>
  useQuery({
    enabled,
    queryKey: ['weather', 'bounds'],
    queryFn: () => call(api.GET('/api/weather/grid/bounds')),
    staleTime: TEN_MINUTES,
  });

/** The wind arrows over the map at an hour; the server thins them out by the whole zoom. */
export const useWindPoints = (hour: string, zoom: number, enabled: boolean) =>
  useQuery({
    enabled,
    queryKey: ['weather', 'wind', hour, zoom],
    queryFn: ({ signal }) =>
      call(api.GET('/api/weather/wind', { params: { query: { time: hour, zoom } }, signal })),
    staleTime: TEN_MINUTES,
    // the arrows of the last zoom stay until the next ones come
    placeholderData: (previous) => previous,
  });

/** The weather under the pointer; null outside the country. A newer ask cancels the older one through `signal`. */
export async function fetchWeatherAt(
  lon: number,
  lat: number,
  hour: string,
  signal: AbortSignal,
): Promise<WeatherAt | null> {
  try {
    return await call(
      api.GET('/api/weather/at', { params: { query: { lon, lat, time: hour } }, signal }),
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
