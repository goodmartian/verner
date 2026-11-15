import type { FireDetail, FireSummary, PlanIssue } from '../../api/types';
import type { I18n } from '../../i18n/context';
import type { MessageKey } from '../../i18n/en';
import { LOCALES, type Lang } from '../../i18n/lang';
import { formatCount } from '../calendar/text';
import { nearestHour, seriesIndex } from '../weather/time';
import { formatLocalTime } from '../../lib/time';

export const compass = (index: number) => ((Math.round(index) % 8) + 8) % 8;

/** "≈ 13,608 ha": an estimate, shown to the hectare. */
export function areaText(t: I18n['t'], lang: Lang, hectares: number): string {
  return t('fire.ha', { n: `≈ ${formatCount(lang, hectares)}` });
}

/** The days a list covers: "17 to 19 February 2022", with only the parts that differ at the start. */
export function periodText(t: I18n['t'], lang: Lang, first: string, last: string): string {
  const a = new Date(`${first}T00:00:00Z`);
  const b = new Date(`${last}T00:00:00Z`);
  const part = (date: Date, options: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat(LOCALES[lang], { ...options, timeZone: 'UTC' }).format(date);
  const sameYear = a.getUTCFullYear() === b.getUTCFullYear();
  const sameMonth = sameYear && a.getUTCMonth() === b.getUTCMonth();
  return t('fires.period', {
    a: part(
      a,
      sameMonth
        ? { day: 'numeric' }
        : sameYear
          ? { day: 'numeric', month: 'long' }
          : { day: 'numeric', month: 'long', year: 'numeric' },
    ),
    b: part(b, { day: 'numeric', month: 'long', year: 'numeric' }).replace(/\s?г\.$/, ''),
  });
}

/** "21 km west": how far the nearest place is and in which direction the fire lies from it. */
export function whereText(t: I18n['t'], lang: Lang, place: FireSummary['nearest_place']): string {
  const km = new Intl.NumberFormat(LOCALES[lang], { maximumFractionDigits: 0 }).format(
    place.distance_km,
  );
  return t('fires.where', { km, dir: t(`dir.${String(compass(place.direction))}` as MessageKey) });
}

/** "from the southwest" for a wind that blows from `degrees`. */
export function windFrom(t: I18n['t'], degrees: number): string {
  return t(`dirFrom.${String(compass(degrees / 45))}` as MessageKey);
}

/** The speed of the head of a fire and what it is called: under 1 km/h in metres an hour, else km/h with a decimal; from the weather says so. */
export function frontSpeed(
  t: I18n['t'],
  lang: Lang,
  spread: FireDetail['spread'],
): { value: string; label: string } {
  const metres = spread?.rate_m_per_h ?? 0;
  const value =
    metres > 0 && metres < 1000
      ? t('fire.mh', {
          n: new Intl.NumberFormat(lang, { maximumFractionDigits: 0 }).format(metres),
        })
      : t('wx.speed', {
          speed: new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(metres / 1000),
        });
  return { value, label: t(spread?.rate_source === 'weather' ? 'fire.rosWeather' : 'fire.ros') };
}

/** "18 Feb, 16:44" */
export function formatPass(lang: Lang, iso: string, zone: string | null): string {
  return formatLocalTime(LOCALES[lang], iso, zone, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatClock(lang: Lang, iso: string, zone: string | null): string {
  return formatLocalTime(LOCALES[lang], iso, zone, {
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** "18 Feb" */
export function formatDayShort(lang: Lang, day: string): string {
  return new Intl.DateTimeFormat(LOCALES[lang], {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(new Date(`${day}T00:00:00Z`));
}

/** The weather at the fire centre in an hour (the one of the pass when none is given); null when the series does not reach it. */
export function weatherAt(detail: FireDetail, hour?: string) {
  const { weather } = detail;
  if (!weather) return null;
  const index = seriesIndex(
    weather.start,
    weather.wind_speed_kmh.length,
    hour ?? nearestHour(Date.parse(detail.pass_time)),
  );
  if (index === null) return null;
  const speed = weather.wind_speed_kmh[index];
  const from = weather.wind_from_deg[index];
  const temperature = weather.temperature_c[index];
  const humidity = weather.humidity_pct[index];
  if (
    speed === undefined ||
    from === undefined ||
    temperature === undefined ||
    humidity === undefined
  ) {
    return null;
  }
  return { speed, from, temperature, humidity };
}

/** The numbers of the fire as of the pass on screen. */
export function factsAt(summary: FireSummary, pass: number) {
  const point = summary.growth.find((item) => item.pass_index === pass);
  return {
    areaHa: point?.area_ha ?? summary.area_ha,
    detections: point?.detections ?? summary.detection_count,
    powerMw: point?.frp_mw ?? 0,
  };
}

/** What an issue of a plan says, from its code and numbers. */
export function issueText(t: I18n['t'], issue: PlanIssue, suggestedFrom: number): string {
  const number = (value: number | null | undefined) =>
    new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value ?? 0);
  const from = windFromIndex(t, suggestedFrom);
  switch (issue.kind) {
    case 'in':
      return t('issue.in', { mark: issue.mark ?? 0, from });
    case 'fc':
      return t('issue.fc', { mark: issue.mark ?? 0, hours: number(issue.hours), from });
    case 'wind':
      return t('issue.wind', { speed: number(issue.speed_kmh) });
    case 'head':
      return t('issue.head', {
        hot: issue.mark ?? 0,
        until: issue.until_min ?? 0,
        walk: issue.walk_min ?? 0,
        crew: issue.crew ?? 0,
      });
    case 'nozone':
      return t('issue.nozone', { crew: issue.crew ?? 0, m: issue.distance_m ?? 0 });
    case 'escfire':
      return t('issue.escfire', { crew: issue.crew ?? 0, hours: number(issue.hours) });
    case 'stale':
      return t('issue.stale');
    case 'outside':
      return t('issue.outside', { count: issue.count ?? 0 });
    case 'nopath':
      return t('issue.nopath', { hot: issue.hot_spot ?? 0, crew: issue.crew ?? 0 });
    case 'long':
      return t('issue.long', { crew: issue.crew ?? 0, minutes: number(issue.walk_min) });
    case 'share':
      return t('issue.share', { hot_spots: issue.hot_spots ?? 0, crews: issue.crews ?? 0 });
    case 'noland':
      return t('issue.noland');
  }
}

/** "from the southwest" for a compass point, 0 north to 7 northwest. */
export function windFromIndex(t: I18n['t'], index: number): string {
  return t(`dirFrom.${String(compass(index))}` as MessageKey);
}
