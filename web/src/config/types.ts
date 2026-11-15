import type { MultiPolygon, Polygon } from 'geojson';
import type { Lang } from '../i18n/lang';

export type AreaRef = { id: string } | { polygon: Polygon | MultiPolygon };
export type Bbox = [number, number, number, number];
export type Names = Partial<Record<Lang, string>>;
export type TypeLabel = Partial<Record<Lang, { one: string; other: string }>>;

export interface AreaFlags {
  covered: boolean | null;
  bbox: Bbox | null;
  timezone: string | null;
}

export interface ConfigArea extends AreaFlags {
  id: string;
  names: Names;
  kind: string;
  country_id?: string;
  type_label?: TypeLabel;
}

/** Normalized frontend config; config/load.ts adapts the OpenAPI wire response. */
export interface AppConfig {
  countries: ConfigArea[];
  languages: { code: Lang; locale: string; name: string }[];
  archive_years: number[];
  default_area: AreaRef | null;
  areas: ConfigArea[];
}
