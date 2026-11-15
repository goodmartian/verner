import { lazy, Suspense, useCallback, useState, type ComponentProps } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, call } from '../../api/client';
import { useApiErrorText } from '../../api/useApiErrorText';
import { useI18n } from '../../i18n/context';
import { WORLD } from '../calendar/areas';
import type { RegionDialog as RegionDialogType } from './RegionDialog';
import { useRegionSearch } from './queries';

// the dialog and its list come when it is first opened, not with the first screen
const RegionDialog = lazy(() =>
  import('./RegionDialog').then((module) => ({ default: module.RegionDialog })),
);

type Props = ComponentProps<typeof RegionDialogType>;

export function RegionPicker({ onPick, areas = [], ...props }: Props) {
  const { t } = useI18n();
  const [search, setSearch] = useState<{ q: string; country?: string }>({ q: '' });
  const onSearch = useCallback((q: string, country?: string) => {
    setSearch({ q, country });
  }, []);
  const world = t('region.world');
  const client = useQueryClient();
  const result = useRegionSearch(props.open, search.q, search.country, props.showFires);
  const errorText = useApiErrorText();
  const choose = useMutation({
    mutationFn: async (id: string) => {
      // the world has no outline of its own to fetch: the calendar frames it from its own answer
      if (id === WORLD || areas.some((item) => item.id === id)) {
        await onPick(id);
        return;
      }
      const region = result.data?.regions.find((item) => item.id === id);
      const geometry = await client.query({
        queryKey: ['region-geometry', id],
        queryFn: () =>
          call(
            api.GET('/api/regions/{region_id}/geometry', { params: { path: { region_id: id } } }),
          ),
        staleTime: Infinity,
      });
      if (region) client.setQueryData(['selected-region', id], { ...region, ...geometry });
      await onPick(id);
    },
  });
  if (!props.open) return null;
  return (
    <Suspense fallback={null}>
      <RegionDialog
        {...props}
        onSearch={onSearch}
        onPick={(id) => choose.mutateAsync(id)}
        results={
          result.data
            ? [
                // the first line is the whole world, over the countries, on both tabs: the region is the same

                ...(!search.country && world.toLowerCase().includes(search.q.trim().toLowerCase())
                  ? [{ id: WORLD, names: { en: world, fr: world, es: world, ru: world } }]
                  : []),
                ...result.data.regions
                  .filter((region) => !search.country || region.id !== search.country)
                  .map((region) => ({
                    id: region.id,
                    names: region.names,
                    kind: region.kind,
                    countryId: region.country_id ?? undefined,
                    typeLabel: result.data.types[region.type ?? ''],
                    firesNow: region.fires_now,
                  })),
              ]
            : undefined
        }
        searchNote={
          result.error || choose.error ? errorText(choose.error ?? result.error) : undefined
        }
        areas={areas}
      />
    </Suspense>
  );
}
