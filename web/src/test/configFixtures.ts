import type { AppConfig } from '../config/types';
import type { components } from '../api/schema';

/** Fictional places; real IANA zones exercise integer, fractional and daylight-saving offsets. */
export const INTEGER_ZONE = 'America/Denver';
export const FRACTIONAL_ZONE = 'America/St_Johns';
export const QUARTER_ZONE = 'Asia/Kathmandu';
export const ZONE_OFFSETS = {
  integerWinter: 'UTC−7',
  integerSummer: 'UTC−6',
  fractional: 'UTC−3:30',
  quarter: 'UTC+5:45',
};
export const COUNTRY_ID = 'XZ';
export const REGION_ID = 'XZ-N';
export const OTHER_COUNTRY_ID = 'XY';
export const THIRD_COUNTRY_ID = 'XW';
export const BROWSER_LANGUAGES = ['fr-FR', 'ru-RU'];
export const CONFIG_BBOX: [number, number, number, number] = [-110, 40, -50, 55];

export function makeConfig(overrides: Partial<AppConfig> = {}): AppConfig {
  const country = {
    id: COUNTRY_ID,
    kind: 'country',
    covered: true,
    bbox: CONFIG_BBOX,
    timezone: INTEGER_ZONE,
    names: { en: 'Northland', fr: 'Terre du Nord', es: 'Tierra del Norte', ru: 'Северная земля' },
  };
  return {
    countries: [country],
    areas: [
      country,
      {
        ...country,
        id: REGION_ID,
        kind: 'region',
        country_id: COUNTRY_ID,
        timezone: FRACTIONAL_ZONE,
      },
    ],
    languages: [
      { code: 'en', locale: 'en-GB', name: 'English' },
      { code: 'fr', locale: 'fr-CA', name: 'Français' },
      { code: 'es', locale: 'es', name: 'Español' },
      { code: 'ru', locale: 'ru', name: 'Русский' },
    ],
    archive_years: [2024, 2025, 2026],
    default_area: { id: COUNTRY_ID },
    ...overrides,
  };
}

/** The OpenAPI wire shape of the config, kept separate from the normalized frontend config. */
export function configResponse(config: AppConfig = makeConfig()): components['schemas']['Config'] {
  return {
    covered_countries: config.countries.flatMap((country) =>
      country.bbox
        ? [
            {
              id: country.id,
              names: Object.fromEntries(
                Object.entries(country.names).filter(
                  (entry): entry is [string, string] => typeof entry[1] === 'string',
                ),
              ),
              bbox: country.bbox,
            },
          ]
        : [],
    ),
    languages: config.languages.map((item) => item.code),
    archive_years: config.archive_years,
    default_area: config.default_area && 'id' in config.default_area ? config.default_area.id : '',
  };
}
