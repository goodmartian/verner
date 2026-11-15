import { api, call } from '../api/client';
import { language, isLang } from '../i18n/lang';
import type { AppConfig, AreaRef, Bbox, ConfigArea, Names, TypeLabel } from './types';

const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

export function readBbox(value: unknown): Bbox | null {
  return Array.isArray(value) &&
    value.length === 4 &&
    value.every((n) => typeof n === 'number' && Number.isFinite(n)) &&
    value[0] < value[2] &&
    value[1] < value[3]
    ? (value as Bbox)
    : null;
}

// building an Intl formatter costs about a tenth of a millisecond, and the catalog has thousands of regions on a few hundred zones
const zones = new Map<string, string | null>();

export function readZone(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const known = zones.get(value);
  if (known !== undefined) return known;
  let zone: string | null;
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: value }).format();
    zone = value;
  } catch {
    zone = null;
  }
  zones.set(value, zone);
  return zone;
}

function namesOf(value: unknown): Names {
  return Object.fromEntries(
    Object.entries(object(value)).filter(([key, name]) => isLang(key) && typeof name === 'string'),
  );
}

/** The labels of the region types by their key, as a catalog answer gives them. */
type TypeNames = Record<string, Record<string, { one: string; other: string }>>;

function readArea(value: unknown, covered: boolean | null, types?: TypeNames): ConfigArea | null {
  const row = object(value);
  if (typeof row.id !== 'string' || !row.id) return null;
  const type_label: TypeLabel = {};
  // a region names its type by a key of the dictionary of the answer; a row of the config carries its labels itself
  const labels = typeof row.type === 'string' ? types?.[row.type] : undefined;
  for (const [code, value] of Object.entries(object(row.type_label ?? labels))) {
    const label = object(value);
    if (isLang(code) && typeof label.one === 'string' && typeof label.other === 'string')
      type_label[code] = { one: label.one, other: label.other };
  }
  return {
    id: row.id,
    names: namesOf(row.names),
    kind: typeof row.kind === 'string' ? row.kind : '',
    covered: typeof row.covered === 'boolean' ? row.covered : covered,
    bbox: readBbox(row.bbox),
    timezone: readZone(row.timezone),
    ...(typeof row.country_id === 'string' ? { country_id: row.country_id } : {}),
    type_label,
  };
}

export function mergeRegions(
  config: AppConfig,
  values: readonly unknown[],
  types?: TypeNames,
): AppConfig {
  const supplied = values.flatMap((value) => {
    const area = readArea(value, null, types);
    return area ? [area] : [];
  });
  const areas = new Map(supplied.map((area) => [area.id, area]));
  for (const area of config.areas) {
    const supplied = areas.get(area.id);
    areas.set(area.id, {
      ...supplied,
      ...area,
      names: { ...supplied?.names, ...area.names },
      bbox: area.bbox ?? supplied?.bbox ?? null,
      timezone: area.timezone ?? supplied?.timezone ?? null,
      covered: area.covered ?? supplied?.covered ?? null,
    });
  }
  return { ...config, areas: [...areas.values()] };
}

function readRef(value: unknown): AreaRef | null {
  if (typeof value === 'string' && value) return { id: value };
  const row = object(value);
  if (typeof row.id === 'string' && row.id) return { id: row.id };
  const polygon = object(row.polygon);
  if (
    (polygon.type === 'Polygon' || polygon.type === 'MultiPolygon') &&
    Array.isArray(polygon.coordinates)
  )
    return { polygon: row.polygon as Extract<AreaRef, { polygon: unknown }>['polygon'] };
  return null;
}

/** Validate the single configuration source at the transport boundary. */
export function decodeConfig(value: unknown): AppConfig {
  const row = object(value);
  if (
    !Array.isArray(row.covered_countries) ||
    !Array.isArray(row.languages) ||
    !Array.isArray(row.archive_years)
  )
    throw new Error('Invalid config');
  const countries = row.covered_countries.flatMap((value) => {
    const area = readArea(value, true);
    return area ? [{ ...area, kind: 'country' }] : [];
  });
  const languages = row.languages.flatMap((value) => {
    if (isLang(value)) return [{ code: value, ...language(value) }];
    const item = object(value);
    if (!isLang(item.code) || typeof item.locale !== 'string') return [];
    try {
      new Intl.Locale(item.locale);
    } catch {
      return [];
    }
    return [{ code: item.code, locale: item.locale, name: language(item.code).name }];
  });
  if (!languages.length) throw new Error('No supported config languages');
  return {
    countries,
    languages,
    archive_years: row.archive_years.filter(
      (year): year is number => typeof year === 'number' && Number.isInteger(year),
    ),
    default_area: readRef(row.default_area),
    areas: [...new Map([...countries].map((area) => [area.id, area])).values()],
  };
}

export async function loadConfig(): Promise<AppConfig> {
  return decodeConfig(await call(api.GET('/api/config')));
}
