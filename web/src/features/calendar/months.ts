/** A month as `YYYY-MM`, the form the API uses. */
export type Month = string;

export interface MonthRange {
  from: Month;
  to: Month;
}

/** Months counted from year 0, so that a later month is a bigger number. */
export function monthIndex(month: Month): number {
  const [year = '0', number = '1'] = month.split('-');
  return Number(year) * 12 + Number(number) - 1;
}

export function monthAt(index: number): Month {
  return `${String(Math.floor(index / 12)).padStart(4, '0')}-${String((index % 12) + 1).padStart(2, '0')}`;
}

export const yearOf = (month: Month): number => Math.floor(monthIndex(month) / 12);

export const monthsIn = (range: MonthRange): number =>
  monthIndex(range.to) - monthIndex(range.from) + 1;

export const sameRange = (a: MonthRange, b: MonthRange): boolean =>
  a.from === b.from && a.to === b.to;

/** The range of the same length right before (-1) or right after (1) this one, or null past the ends. */
export function step(range: MonthRange, direction: -1 | 1, limits: MonthRange): MonthRange | null {
  const length = monthsIn(range);
  const from = monthIndex(range.from) + direction * length;
  const first = monthIndex(limits.from);
  const last = monthIndex(limits.to);
  if (from > last || from + length - 1 < first) return null;
  const start = Math.max(from, first);
  return { from: monthAt(start), to: monthAt(Math.min(from + length - 1, last)) };
}
