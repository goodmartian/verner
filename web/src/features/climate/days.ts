import type { FeatureCollection, Point } from 'geojson';
import type { DayFires, MonthDays } from '../../api/types';

/** Every date of a month, `YYYY-MM-DD`. */
export function monthDates(month: string): string[] {
  const year = Number(month.slice(0, 4));
  const number = Number(month.slice(5, 7));
  const count = new Date(Date.UTC(year, number, 0)).getUTCDate();
  return Array.from(
    { length: count },
    (_, index) => `${month}-${String(index + 1).padStart(2, '0')}`,
  );
}

type DayRow = MonthDays['days'][number];

/** The days of the month that had fires, by date. */
export const daysByDate = (days: MonthDays | null | undefined): Map<string, DayRow> =>
  new Map((days?.days ?? []).map((day) => [day.date, day]));

/**
 * The detections of each day as whole numbers that add up to the figure of the month: the days come as fractions, so
 * each is rounded down and the units left over go to the days with the largest fractions. When the month's figure is
 * not about the sum of the days (it is another count), the days are only rounded.
 */
export function wholeDays(
  days: MonthDays | null | undefined,
  total: number | null | undefined,
): Map<string, number> {
  const rows = [...daysByDate(days)].map(([date, row]) => ({ date, value: row.detections }));
  const sum = rows.reduce((all, row) => all + row.value, 0);
  const target = total != null && Math.abs(sum - total) <= rows.length ? total : Math.round(sum);
  const floors = rows.map((row) => Math.floor(row.value));
  let left = target - floors.reduce((all, value) => all + value, 0);
  const order = rows
    .map((row, index) => ({ index, fraction: row.value - Math.floor(row.value) }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index);
  for (const { index } of order) {
    if (left <= 0) break;
    floors[index] = (floors[index] ?? 0) + 1;
    left -= 1;
  }
  return new Map(rows.map((row, index) => [row.date, floors[index] ?? 0]));
}

/** The clusters of a day as points for the map. */
export function clusterCollection(day: DayFires | null | undefined): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: (day?.fires ?? []).map((fire) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [fire.lon, fire.lat] },
      properties: { id: fire.id, detections: fire.detections, frp: fire.frp_mw },
    })),
  };
}

/** A date as a person writes it: `17 Oct 2025`, with the day of the week when asked for. */
export function formatDate(locale: string, date: string, weekday = false): string {
  return new Intl.DateTimeFormat(locale, {
    ...(weekday ? { weekday: 'short' as const } : {}),
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${date}T00:00:00Z`));
}
