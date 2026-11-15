import type { Polygon, MultiPolygon } from 'geojson';
import { useMemo } from 'react';
import { skipToken, useQuery } from '@tanstack/react-query';
import type { Region } from '../../api/types';
import { useI18n } from '../../i18n/context';
import { localName } from '../../i18n/lang';
import { areaFlags, areaId, polygonBbox, useConfig } from '../../config/context';
import { readBbox, readZone } from '../../config/load';
import type { AreaFlags } from '../../config/types';
import { useBoard } from '../board/context';
import { useFiresState } from '../fires/context';
import type { CountryItem } from '../region/RegionDialog';
import { useCalendar, useCountryRegions, useRegions } from './queries';
import { useRegionGeometry } from '../region/queries';

/** Area responses can supply metadata the config does not have, including for a polygon. */
export function useAreaFlags(): AreaFlags {
  const { area } = useBoard();
  const config = useConfig();
  const calendar = useCalendar();
  // the calendar of the area before, kept on the board until the new one comes, says nothing of this area
  const data = calendar.isPlaceholderData ? undefined : calendar.data;
  const geometry = useRegionGeometry(areaId(area)).data;
  return useMemo(() => {
    const base = areaFlags(config, area);
    const metadata: unknown = data?.area ?? geometry;
    if (!metadata || typeof metadata !== 'object') return base;
    return {
      bbox: 'bbox' in metadata ? (readBbox(metadata.bbox) ?? base.bbox) : base.bbox,
      timezone:
        'timezone' in metadata ? (readZone(metadata.timezone) ?? base.timezone) : base.timezone,
      covered:
        'covered' in metadata && typeof metadata.covered === 'boolean'
          ? metadata.covered
          : base.covered,
    };
  }, [config, area, data, geometry]);
}

export interface AreaShape {
  /** West, south, east, north. */
  bbox: [number, number, number, number];
  outline: Polygon | MultiPolygon | null;
}

/** The id the API gives the whole world. */
export const WORLD = 'WORLD';

/** The countries a person can pick, from the countries with full data and the whole world; the regions of a country come when it is opened. */
export function useCountryItems(): CountryItem[] {
  const { demo } = useFiresState();
  const { t, lang, locale } = useI18n();
  const config = useConfig();
  const regions = useRegions(demo).data?.regions;
  // the catalog holds hundreds of countries: the list is built once per catalog, not on every render of the page
  return useMemo(() => {
    const firesNow = new Map((regions ?? []).map((item) => [item.id, item.fires_now]));
    const covered: CountryItem[] = (config?.countries ?? []).map((country) => ({
      id: country.id,
      names: country.names,
      typeLabel: country.type_label,
      firesNow: firesNow.get(country.id),
      provinces: (config?.areas ?? [])
        .filter((item) => item.kind !== 'country' && item.country_id === country.id)
        .map((item) => ({
          id: item.id,
          names: item.names,
          typeLabel: item.type_label ?? undefined,
          firesNow: firesNow.get(item.id),
        })),
    }));
    // the whole world is one area of its own: the first line of the list, over the countries
    const world = t('region.world');
    return [
      { id: WORLD, names: { en: world, fr: world, es: world, ru: world } },
      ...covered,
      ...(regions ?? [])
        .filter((item) => item.kind === 'country')
        .filter(
          (item) =>
            !covered.some(
              (country) =>
                country.id === item.id ||
                Object.entries(item.names).some(
                  ([code, name]) =>
                    Boolean(name.trim()) &&
                    country.names[code as keyof typeof country.names] === name,
                ),
            ),
        )
        .map((item) => ({
          id: item.id,
          names: item.names,
          // a country of the archive opens a second step: its regions are asked for then
          provinces: [],
        }))
        .sort((a, b) => localName(a.names, lang).localeCompare(localName(b.names, lang), locale)),
    ];
  }, [config, regions, t, lang, locale]);
}

/** The country a province id (`AR-B`) belongs to; ids of other shapes say nothing of it. */
const countryOf = (id: string | null) => (id && /^[A-Z]{2}-/.test(id) ? id.slice(0, 2) : null);

/** The name of the area on the board, in the language of the interface; null until the catalog that holds it has come. */
export function useAreaName(): string | null {
  const { t, lang } = useI18n();
  const { area, drawn, polygon } = useBoard();
  const config = useConfig();
  const id = areaId(area);
  const region = config?.areas.find((item) => item.id === id);
  const own = region ? localName(region.names, lang) : '';
  // a province of the archive is found among the regions of its country, which are asked for only when nothing else names it
  const countries = useRegions().data?.regions;
  const regions = useCountryRegions(own ? null : countryOf(id)).data?.regions;
  const selected = useQuery<Pick<Region, 'id' | 'names'>>({
    queryKey: ['selected-region', id],
    queryFn: skipToken,
  }).data;
  if (area && 'polygon' in area) {
    // the same name with the number as the area has in the list of the question
    const index = drawn.findIndex((item) => item.points === polygon);
    return index < 0 ? t('map.drawn') : t('att.area', { n: index + 1 });
  }
  if (id === WORLD) return t('region.world');
  const catalog =
    selected ??
    countries?.find((item) => item.id === id) ??
    regions?.find((item) => item.id === id);
  return own || (catalog ? localName(catalog.names, lang) : '') || null;
}

/** Where the area is on the map: its frame and, when known, its outline. */
export function useAreaShape(): AreaShape | null {
  const { area } = useBoard();
  const flags = useAreaFlags();
  const id = areaId(area);
  const geometry = useRegionGeometry(id).data;
  return useMemo(() => {
    if (area && 'polygon' in area) {
      const bbox = polygonBbox(area);
      return bbox ? { bbox, outline: area.polygon } : null;
    }
    const region = geometry;
    if (region) {
      const bbox = readBbox(region.bbox);
      if (bbox) return { bbox, outline: region.geometry };
    }
    if (flags.bbox) return { bbox: flags.bbox, outline: null };
    return null;
  }, [area, flags.bbox, geometry]);
}
