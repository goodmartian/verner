import { localDay } from '../../lib/time';
import { placeZone } from '../../config/usePlaceZone';
import type { FireDetail, FirePlan, PlanCrew, PlanIssue } from '../../api/types';
import type { I18n } from '../../i18n/context';
import type { MessageKey } from '../../i18n/en';
import { LOCALES, type Lang } from '../../i18n/lang';
import { detectionsWord, formatCount } from '../calendar/text';
import {
  compass,
  formatClock,
  formatPass,
  issueText,
  weatherAt,
  windFrom,
  windFromIndex,
} from './text';

const key = (name: string) => name as MessageKey;

const addHours = (iso: string, hours: number) =>
  new Date(Date.parse(iso) + hours * 3_600_000).toISOString();

/** The clock time `hours` after the pass the plan is made at; with the day when it is not the day of the pass. */
export function planClock(lang: Lang, plan: FirePlan, hours: number, zone: string | null): string {
  const at = addHours(plan.pass_time, hours);
  const local = placeZone(plan, zone);
  if (!local) return '';
  return localDay(Date.parse(at), local) === localDay(Date.parse(plan.pass_time), local)
    ? formatClock(lang, at, local)
    : formatPass(lang, at, local);
}

const decimal = (lang: Lang, n: number, digits = 1) =>
  new Intl.NumberFormat(LOCALES[lang], { maximumFractionDigits: digits }).format(n);

/** "2 crews", "5 бригад"; `of` is the form after "for": "для 2 бригад". */
export function crewsText(t: I18n['t'], lang: Lang, n: number, of = false): string {
  const form = new Intl.PluralRules(LOCALES[lang]).select(n);
  return `${decimal(lang, n, 0)} ${t(key(`pl.crews${of ? 'Of' : ''}.${form}`))}`;
}

const list = (lang: Lang, items: readonly (string | number)[]) =>
  new Intl.ListFormat(LOCALES[lang], { type: 'conjunction' }).format(items.map(String));

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** The crews that go: every one the planner did not leave out. */
export const goingCrews = (plan: FirePlan) => plan.crews.filter((crew) => crew.status !== 'block');

/** The temperature and the humidity of the plan: those the server worked out for the moment of its wind, else the series of the card at the pass. */
function planAir(detail: FireDetail) {
  const wind = detail.spread?.wind;
  return wind
    ? { temperature: wind.temperature_c, humidity: wind.humidity_pct }
    : weatherAt(detail);
}

/** The wind of the plan as a phrase: "Wind from the southwest 22 km/h". */
function windPhrase(t: I18n['t'], lang: Lang, plan: FirePlan): string {
  return `${capital(t('wx.windFrom', { dir: windFrom(t, plan.wind.from_deg) }))} ${t('wx.speed', {
    speed: decimal(lang, plan.wind.speed_kmh, 0),
  })}`;
}

/** Where the head runs: the wind blows from `from`, so the front goes the other way. */
const headDirection = (t: I18n['t'], plan: FirePlan): string =>
  t(key(`pl.to.${String(compass((plan.wind.from_deg + 180) / 45))}`));

/** Metres along a way. */
export function routeLength(route: readonly (readonly number[])[]): number {
  let total = 0;
  for (let i = 1; i < route.length; i += 1) {
    const [x0 = 0, y0 = 0] = route[i - 1] ?? [];
    const [x1 = 0, y1 = 0] = route[i] ?? [];
    total += Math.hypot((x1 - x0) * Math.cos((y1 * Math.PI) / 180), y1 - y0) * 111_000;
  }
  return total;
}

/** The compass point (0 north, 1 north-east, ...) a place lies at from the centre of the fire. */
export function pointFrom(center: readonly number[], place: readonly number[]): number {
  const [x0 = 0, y0 = 0] = center;
  const [x1 = 0, y1 = 0] = place;
  const bearing = (Math.atan2((x1 - x0) * Math.cos((y1 * Math.PI) / 180), y1 - y0) * 180) / Math.PI;
  return compass(bearing / 45);
}

export interface PlanReport {
  situation: string;
  task: string;
  safety: string;
}

/** The plan as a crew leader reads it: the situation, the task and the safety, every number from the plan. */
export function planReport(
  t: I18n['t'],
  lang: Lang,
  plan: FirePlan,
  detail: FireDetail,
  zone: string | null,
): PlanReport {
  zone = placeZone(detail, zone);
  const { report } = plan;
  // the air of the plan is that of the moment of its wind: the one the server worked out for the pass
  const weather = planAir(detail);
  const situation = t('pl.repSit', {
    ha: formatCount(lang, report.area_ha),
    n: `${decimal(lang, report.detections_last_pass, 0)} ${detectionsWord(t, lang, report.detections_last_pass)}`,
    at: formatPass(lang, plan.pass_time, zone),
    wind: windPhrase(t, lang, plan),
    tc: decimal(lang, weather?.temperature ?? 0, 0),
    rh: decimal(lang, weather?.humidity ?? 0, 0),
    dir: headDirection(t, plan),
    kmh: decimal(lang, report.spread_km_per_h),
    h: plan.hours,
    grow: formatCount(lang, Math.round(report.growth_ha / 10) * 10),
  });
  const who = crewsText(t, lang, plan.crews.length);
  const end = planClock(lang, plan, plan.hours, zone);
  const hots = plan.report.hot_spots;
  const task =
    hots.length > 0
      ? t(hots.length > 1 ? 'pl.taskMany' : 'pl.taskOne', {
          c: capital(who),
          h: plan.hours,
          end,
          list: list(lang, hots),
          n: hots.length,
        })
      : t('pl.taskFlank', { c: capital(who), h: plan.hours, end });
  const low = Math.max(50, Math.round(report.safe_min_m / 50) * 50);
  const high = Math.max(low, Math.round(report.safe_max_m / 50) * 50);
  const range = low === high ? String(low) : t('pl.range', { a: low, b: high });
  const safety = [
    report.leave_in_h === null
      ? t('pl.safeNoLeave')
      : t('pl.safeLeave', { tm: planClock(lang, plan, report.leave_in_h, zone) }),
    t(plan.report.all_on_burned_ground ? 'pl.safeBurned' : 'pl.safeBehind', { range }),
  ].join(' ');
  return { situation, task, safety };
}

/** What a crew is sent to do: a hotspot, the one of the operator or the one the planner chose. */
export function crewTask(t: I18n['t'], crew: PlanCrew): string {
  return t('pl.hot', { n: crew.target.hot_spot });
}

/** "Entry 1 from the north": the crew's way in. */
export function crewEntry(
  t: I18n['t'],
  plan: FirePlan,
  crew: PlanCrew,
  center: readonly number[],
): string {
  const name =
    crew.entry_source === 'op' ? t('plan.entryMark', { n: crew.entry_mark ?? 0 }) : t('pl.entry');
  const from =
    crew.entry_source === 'op' ? pointFrom(center, crew.entry) : plan.entry.from_direction;
  return `${name} ${windFromIndex(t, from)}`;
}

/** The issues that touch one crew, the entry ones left to the review. */
export const crewIssues = (plan: FirePlan, crew: PlanCrew) =>
  plan.issues.filter(
    (issue) => issue.crew === crew.number && issue.kind !== 'in' && issue.kind !== 'fc',
  );

/** What to send as `overrides` to include or leave out this crew. */
export function crewKeys(plan: FirePlan, crew: PlanCrew): string[] {
  const keys = crewIssues(plan, crew).flatMap((issue) =>
    issue.level === 'block' && issue.key ? [issue.key] : [],
  );
  const wind = plan.issues.find((issue) => issue.kind === 'wind' && issue.key);
  if (crew.held.includes('wind') && wind?.key && !keys.includes(wind.key)) keys.push(wind.key);
  return keys;
}

/** One line of the plan's check: a reason, however many crews it touches. */
export interface ReviewRow {
  level: 'block' | 'risk' | 'info' | 'forced';
  icon: 'prohibit' | 'warning' | 'info' | 'user-check' | 'clock-counter-clockwise';
  title: string;
  sub: string;
  /** What to send as `overrides` to overrule this row, and whether the operator has. */
  keys: readonly string[];
  forced: boolean;
  /** The plan is older than the pass on screen: it can be made again. */
  rebuild?: boolean;
}

const ICON = { block: 'prohibit', risk: 'warning', info: 'info' } as const;

/** The check of the plan, one row per reason. */
export function reviewRows(
  t: I18n['t'],
  lang: Lang,
  plan: FirePlan,
  shownPassTime: string | null,
  zone: string | null,
): ReviewRow[] {
  const rows: ReviewRow[] = [];
  if (shownPassTime !== null && shownPassTime !== plan.pass_time) {
    rows.push({
      level: 'info',
      icon: 'clock-counter-clockwise',
      title: t('pl.outdated', { tm: planClock(lang, plan, 0, zone) }),
      sub: '',
      keys: [],
      forced: false,
      rebuild: true,
    });
  }
  const groups = new Map<PlanIssue['kind'], PlanIssue[]>();
  for (const issue of plan.issues)
    groups.set(issue.kind, [...(groups.get(issue.kind) ?? []), issue]);
  for (const [kind, issues] of groups) {
    const first = issues[0];
    if (!first) continue;
    const numbers = issues.flatMap((issue) => {
      const n = kind === 'in' || kind === 'fc' ? issue.mark : issue.crew;
      return n === null ? [] : [n];
    });
    const keys = issues.flatMap((issue) => (issue.key ? [issue.key] : []));
    const forced = keys.length > 0 && issues.every((issue) => issue.forced);
    const { level: own } = first;
    const level = forced ? 'forced' : own;
    const icon = forced ? 'user-check' : ICON[own];
    if (kind === 'in' || kind === 'fc') {
      rows.push({
        level,
        icon,
        title: t(key(`pl.k_${kind}`)),
        sub: `${t(numbers.length === 1 ? 'pl.entryOne' : 'pl.entryMany', { l: list(lang, numbers) })}. ${forced ? t('pl.forced') : t('pl.entryAlt', { f: windFromIndex(t, plan.entry.from_direction) })}`,
        keys,
        forced,
      });
    } else if (kind === 'wind') {
      rows.push({
        level,
        icon,
        title: `${t('pl.k_wind')}, ${decimal(lang, first.speed_kmh ?? 0, 0)} ${t('pl.kmh')}`,
        sub: forced ? t('pl.forced') : t('pl.windAll'),
        keys,
        forced,
      });
    } else if (numbers.length > 0 && own !== 'info') {
      rows.push({
        level,
        icon,
        title: t(key(`pl.k_${kind}`)),
        sub:
          t(numbers.length === 1 ? 'pl.crewOne' : 'pl.crewMany', { l: list(lang, numbers) }) +
          (keys.length > 0 ? ` ${forced ? t('pl.included') : t('pl.excluded')}` : ''),
        keys,
        forced,
      });
    } else {
      rows.push({
        level: own,
        icon: ICON[own],
        title: issueText(t, first, plan.entry.from_direction),
        sub: '',
        keys: [],
        forced: false,
      });
    }
  }
  return rows;
}

/** The plan as plain text, to paste where the crews read it. */
export function planCopy(
  t: I18n['t'],
  lang: Lang,
  plan: FirePlan,
  detail: FireDetail,
  zone: string | null,
): string {
  const report = planReport(t, lang, plan, detail, zone);
  const crews = plan.crews.map((crew) => {
    const [lng = 0, lat = 0] = crew.entry;
    const target = t('pl.tgtHot', { n: crew.target.hot_spot });
    const until =
      crew.leave_in_h === null
        ? ''
        : t('pl.copyUntil', { u: planClock(lang, plan, crew.leave_in_h, zone) });
    const from =
      crew.entry_source === 'op'
        ? pointFrom(detail.summary.center, crew.entry)
        : plan.entry.from_direction;
    return `${t('pl.copyCrew', { n: crew.number, f: windFromIndex(t, from), tg: target, u: until })} ${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  });
  return [
    t('pl.artTitle', { n: detail.summary.nearest_place.name }),
    report.situation,
    report.task,
    report.safety,
    ...crews,
  ].join('\n');
}

export interface AgentStep {
  label: string;
  result: string;
}

/** What the plan was made from, step by step: the figures behind it, as the plan used them. */
export function planSteps(
  t: I18n['t'],
  lang: Lang,
  plan: FirePlan,
  detail: FireDetail,
  marks: { entries: number; hots: number },
  zone: string | null,
): AgentStep[] {
  const weather = planAir(detail);
  const contour = plan.contours.find((item) => item.hours === plan.hours);
  const trails = plan.crews.filter((crew) => crew.on_trail);
  const km = Math.max(0, ...trails.map((crew) => crew.length_m)) / 1000;
  const wet = trails.some((crew) => crew.crosses_wet_ground);
  return [
    {
      label: t('pl.stDet'),
      result: t('pl.stDetR', {
        n: `${decimal(lang, plan.report.detections_last_pass, 0)} ${detectionsWord(t, lang, plan.report.detections_last_pass)}`,
        tm: planClock(lang, plan, 0, zone),
      }),
    },
    {
      label: t('pl.stWx'),
      result: t('pl.stWxR', {
        w: windPhrase(t, lang, plan).toLowerCase(),
        tc: decimal(lang, weather?.temperature ?? 0, 0),
        rh: decimal(lang, weather?.humidity ?? 0, 0),
      }),
    },
    {
      label: t('pl.stFc', { h: plan.hours }),
      result: t('pl.stFcR', {
        ha: formatCount(lang, contour?.area_ha ?? plan.report.area_ha, true),
        d: headDirection(t, plan),
      }),
    },
    {
      label: t('pl.stEntry'),
      result:
        marks.entries > 0
          ? t('pl.stEntryR', {
              ok: marks.entries - plan.rejected_entries.length,
              n: marks.entries,
            })
          : t('pl.stEntryNone'),
    },
    {
      label: t('pl.stTrail'),
      result:
        trails.length > 0
          ? t(wet ? 'pl.stTrailWet' : 'pl.stTrailDry', { km: decimal(lang, km) })
          : t('pl.stTrailNone'),
    },
    {
      label: t('pl.stRoute', { c: crewsText(t, lang, plan.crews.length) }),
      result: t('pl.stRouteR'),
    },
  ];
}

/** A distance as a crew reads it: metres to the nearest fifty, kilometres from a thousand. */
export function distanceText(t: I18n['t'], lang: Lang, metres: number): string {
  return metres < 1000
    ? `${decimal(lang, Math.max(50, Math.round(metres / 50) * 50), 0)} ${t('pl.m')}`
    : `${decimal(lang, metres / 1000)} ${t('pl.km')}`;
}
