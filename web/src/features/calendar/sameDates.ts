import type { Calendar } from '../../api/calendar';

/**
 * A month still running is set against the usual count of the same dates, never against a whole month:
 * its median, ratio and rank are those of `to_date`. The months that are over are left as they are.
 * The usual of the whole month stays in `normals`.
 */
export function sameDates(data: Calendar): Calendar {
  const now = data.current_month;
  if (!now.partial) return data;
  const { median, ratio, rank, of } = now.to_date;
  const like = <T extends { median: number | null; mean: number | null }>(month: T): T => ({
    ...month,
    median,
    // the server has no mean of the same dates, and the mean of the whole month is no match for them
    mean: null,
    ratio,
    rank,
    of,
  });
  return {
    ...data,
    current_month: like(now),
    series: data.series.map((month) => (month.month === now.month ? like(month) : month)),
  };
}
