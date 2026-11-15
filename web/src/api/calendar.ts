import { api, ApiError, call, reply } from './client';
import type { components } from './schema';
import type { AreaRef } from '../config/types';
import type { MonthRange } from '../features/calendar/months';

/** The answer of `POST /api/calendar`: everything the board shows of an area. */
export type Calendar = components['schemas']['Calendar'];
/** The answer of `GET /api/meta`: the satellites, the archive, the known seasons. */
export type Meta = components['schemas']['Meta'];
export type AreaGeometry = components['schemas']['Polygon'] | components['schemas']['MultiPolygon'];

export function wireGeometry(
  geometry: Extract<AreaRef, { polygon: unknown }>['polygon'],
): AreaGeometry {
  const ring = (points: number[][]): [number, number][] =>
    points.map(([x, y]) => {
      if (x === undefined || y === undefined || !Number.isFinite(x) || !Number.isFinite(y))
        throw new ApiError(422, 'validation_error', 'Invalid coordinates');
      return [x, y];
    });
  return geometry.type === 'Polygon'
    ? { type: geometry.type, coordinates: geometry.coordinates.map(ring) }
    : { type: geometry.type, coordinates: geometry.coordinates.map((part) => part.map(ring)) };
}

export function areaSelector(area: AreaRef): components['schemas']['AreaSelector'] {
  return 'polygon' in area ? { polygon: wireGeometry(area.polygon) } : area;
}

export const calendar = (area: AreaRef, range: MonthRange | null, signal?: AbortSignal) =>
  call(api.POST('/api/calendar', { body: { area: areaSelector(area), ...range }, signal }));

export const meta = (signal?: AbortSignal) => call(api.GET('/api/meta', { signal }));

/** A CSV the server prepared, with the name it gave the file (`verner.csv` when it gave none). */
export interface CsvFile {
  blob: Blob;
  name: string;
}

/** `months`: the table of the calendar, a row a month. `hotspots`: every detection of the period. */
export type ExportKind = 'months' | 'hotspots';

/** The table of the calendar for the period as a CSV file: small, so it is read here and saved from the page. */
export async function exportMonths(area: AreaRef, range: MonthRange | null): Promise<CsvFile> {
  const { data, response } = await reply(
    api.POST('/api/export/months', {
      body: { area: areaSelector(area), ...range },
      parseAs: 'text',
    }),
  );
  const name = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1];
  return {
    blob: new Blob([data ?? ''], { type: 'text/csv;charset=utf-8' }),
    name: name ?? 'verner.csv',
  };
}

/** The answer of `POST /api/export/ticket`: the one-time address of the file, its rows and its name. */
export type ExportTicket = components['schemas']['ExportTicket'];

/**
 * Every detection of the period: the server counts the rows and hands a one-time address of the file, which the
 * browser then downloads by itself, so a file of hundreds of megabytes never passes through the page.
 */
export const exportTicket = (area: AreaRef, range: MonthRange | null) =>
  call(api.POST('/api/export/ticket', { body: { area: areaSelector(area), ...range } }));
