import { useQuery } from '@tanstack/react-query';
import { api, call } from '../../api/client';
import { useI18n } from '../../i18n/context';

export function useRegionSearch(open: boolean, q: string, country?: string, demo = false) {
  const { lang } = useI18n();
  return useQuery({
    queryKey: ['region-search', q, lang, country, demo],
    enabled: open,
    queryFn: ({ signal }) =>
      call(
        api.GET('/api/regions', {
          params: { query: { q, lang, country, demo, limit: 500 } },
          signal,
        }),
      ),
    staleTime: 60_000,
    retry: false,
  });
}

export const useRegionGeometry = (id: string | null) =>
  useQuery({
    queryKey: ['region-geometry', id],
    // the whole world has no outline of its own: the server answers 404 and it would be asked again by every card that reads it
    enabled: id !== null && id !== 'WORLD',
    queryFn: ({ signal }) => {
      if (!id) throw new Error('No region');
      return call(
        api.GET('/api/regions/{region_id}/geometry', {
          params: { path: { region_id: id } },
          signal,
        }),
      );
    },
    staleTime: Infinity,
    retry: false,
  });
