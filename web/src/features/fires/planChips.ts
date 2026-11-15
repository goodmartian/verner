import { placeZone } from '../../config/usePlaceZone';
import type { FireDetail, FirePlan } from '../../api/types';
import type { I18n } from '../../i18n/context';
import type { Lang } from '../../i18n/lang';
import type { PhName } from '../../ui/Ph';
import { planClock } from './planText';

export interface PlanChip {
  key: string;
  at: [number, number];
  anchor: 'center' | 'top' | 'bottom';
  /** The classes of the chip in the stylesheet: `in`, `hot`, `crew`, `crew blk`, `back`, `fc`, `rej`, `safe`. */
  tone: string;
  icon?: PhName;
  text: string;
  /** Pixels the chip is moved from its point, to stand clear of a neighbour. */
  offset?: [number, number];
}

type Position = readonly number[];

const at = (position: Position): [number, number] => [position[0] ?? 0, position[1] ?? 0];

/** Metres between two points, near enough for chips that must not sit on one another. */
const metres = (a: Position, b: Position) =>
  Math.hypot(
    ((a[0] ?? 0) - (b[0] ?? 0)) * Math.cos(((a[1] ?? 0) * Math.PI) / 180),
    (a[1] ?? 0) - (b[1] ?? 0),
  ) * 111_000;

/** The labels the plan puts on the map: where the crews enter, work, retreat, and how far the fire may go. */
export function planChips(
  t: I18n['t'],
  lang: Lang,
  plan: FirePlan,
  detail: FireDetail,
  zone: string | null,
): PlanChip[] {
  const chips: PlanChip[] = [];
  // many crews: numbers only, so twenty labels still read on the map
  const dense = plan.crews.length > 6;
  const planner = plan.crews.some((crew) => crew.entry_source === 'planner');
  if (planner) {
    chips.push({
      key: 'entry',
      at: at(plan.entry.position),
      anchor: 'bottom',
      tone: 'in',
      text: t('pl.chEntry'),
    });
  }
  for (const spot of plan.hot_marks) {
    chips.push({
      key: `hot-${String(spot.number)}`,
      at: at(spot.position),
      anchor: 'center',
      tone: 'hot',
      icon: 'target',
      text: dense ? String(spot.number) : t('pl.hot', { n: spot.number }),
    });
  }
  const middles: Position[] = [];
  for (const crew of plan.crews) {
    const middle = crew.route[Math.floor(crew.route.length / 2)];
    if (!middle) continue;
    middles.push(middle);
    chips.push({
      key: `crew-${String(crew.number)}`,
      at: at(middle),
      anchor: 'center',
      tone: crew.status === 'block' ? 'crew blk' : 'crew',
      text: dense ? String(crew.number) : t('pl.crewN', { n: crew.number }),
    });
  }
  // a short way out sits under the safety zone label; only a long one gets its own
  if (!dense) {
    for (const crew of plan.crews) {
      if (crew.status === 'block' || crew.safe_distance_m <= 1000) continue;
      const point = crew.escape[Math.floor(crew.escape.length * 0.7)];
      if (!point || middles.some((m) => metres(m, point) < 400)) continue;
      chips.push({
        key: `back-${String(crew.number)}`,
        at: at(point),
        anchor: 'center',
        tone: 'back',
        text: t('pl.chBack'),
      });
    }
  }
  chips.push({
    key: 'now',
    at: at(detail.summary.center),
    anchor: 'center',
    tone: 'fc',
    text: planClock(lang, plan, 0, placeZone(detail, zone)),
  });
  for (const item of plan.rejected_entries) {
    chips.push({
      key: `rej-${String(item.mark)}`,
      at: at(item.position),
      anchor: 'top',
      tone: 'rej',
      icon: 'prohibit',
      text: t('plan.entryMark', { n: item.mark }),
    });
  }
  chips.push({
    key: 'safe',
    at: at(plan.safe_zone.position),
    anchor: 'center',
    tone: 'safe',
    icon: 'shield',
    text: t('pl.chSafe'),
  });
  // the end of each front, where the wind drives it
  {
    const heading = ((plan.wind.from_deg + 180) * Math.PI) / 180;
    const wind: [number, number] = [Math.sin(heading), Math.cos(heading)];
    for (const contour of plan.contours) {
      // the outer rings of all the parts of the front
      const outline = contour.polygons.flatMap((part) => part[0] ?? []);
      const lat = outline.reduce((sum, p) => sum + (p[1] ?? 0), 0) / Math.max(1, outline.length);
      const scale = Math.cos((lat * Math.PI) / 180);
      const reach = (p: Position) => (p[0] ?? 0) * scale * wind[0] + (p[1] ?? 0) * wind[1];
      const tip = outline.reduce<Position | null>(
        (best, p) => (best === null || reach(p) > reach(best) ? p : best),
        null,
      );
      if (tip) {
        chips.push({
          key: `fc-${String(contour.hours)}`,
          at: at(tip),
          anchor: 'center',
          tone: 'fc',
          text: t('pl.chFc', { h: contour.hours }),
        });
      }
    }
  }
  return spread(chips);
}

/** The height of a chip with its gap, in pixels. */
const STEP = 22;

/** How far apart two chips of the same kind must be, in metres, to read as two. */
const APART = 700;

/**
 * Chips that fall on one another are moved off: of the forecast ends that are close, the first stays on its
 * point and the next ones stack below it, and a way back that lands near any other label is left to the line.
 */
function spread(chips: PlanChip[]): PlanChip[] {
  const kept = chips.filter(
    (chip) =>
      chip.tone !== 'back' ||
      !chips.some(
        (other) =>
          other.tone !== 'back' && other.tone !== 'in' && metres(other.at, chip.at) < APART,
      ),
  );
  const placed: PlanChip[] = [];
  return kept.map((chip) => {
    if (chip.tone !== 'fc') return chip;
    const near = placed.filter((other) => metres(other.at, chip.at) < APART).length;
    const moved: PlanChip = near === 0 ? chip : { ...chip, offset: [0, near * STEP] };
    placed.push(moved);
    return moved;
  });
}
