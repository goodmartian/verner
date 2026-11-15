import type { FetchResponse } from 'openapi-fetch';
import type { paths } from '../../api/schema';

type Answer<Path extends keyof paths> = paths[Path] extends { get: infer Operation }
  ? NonNullable<FetchResponse<Operation & object, object, 'application/json'>['data']>
  : never;

export type ClimateLegend = Answer<'/api/climate/legend'>;
export type ClimateLayer = ClimateLegend['month_layers'][number];
export type ClimateBounds = Answer<'/api/climate/grid/bounds'>;
export type ClimateMonth = Answer<'/api/climate/month'>;
