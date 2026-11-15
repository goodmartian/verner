import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import type { Calendar } from '../../api/calendar';
import { useI18n } from '../../i18n/context';
import { LOCALES, type Lang } from '../../i18n/lang';
import { useMediaQuery } from '../../lib/useMediaQuery';
import { useWidth } from '../../lib/useWidth';
import { useAskPop, type AskInfo } from '../../ui/AskPop';
import { Ph } from '../../ui/Ph';
import { LayerKey } from '../weather/LayerKey';
import { useWidgetActions } from '../chat/actions';
import { monthFacts, useAskers } from './askInfo';
import { ChartTip, tipLeft } from '../../ui/ChartTip';
import { Hint } from './Hint';
import { Segments } from '../../ui/Segments';
import { MonthsChart } from './MonthsChart';
import { cellText, scaleOf } from './cells';
import { activeSection, glide } from './sections';
import { FoldButton, MoreCards, useFold } from './CalCards';
import { useMeta, useRecord } from './queries';
import {
  dateText,
  formatChange,
  formatCount,
  formatNice,
  longMonth,
  longMonthYear,
  monthVerdict,
  shortMonths,
} from './text';
import styles from './CalDash.module.css';
import { Tiles as TileGrid } from '../../ui/Tiles';

type Point = Calendar['series'][number];
type SensorId = keyof Point['raw'];

type Section =
  | 'overview'
  | 'calendar'
  | 'trend'
  | 'years'
  | 'season'
  | 'accuracy'
  | 'outlook'
  | 'days'
  | 'known'
  | 'provinces';
// The bar names these, few enough to take in at a glance. A card between two of them belongs to the one before it
// (the years and the days of the month to the trend), so every card lights a name.
const NAMED: readonly Section[] = [
  'overview',
  'calendar',
  'trend',
  'season',
  'outlook',
  'provinces',
  'accuracy',
];

// the grid shows this many last years on a phone, the rest opens on a click
const PHONE_YEARS = 8;
/** The first year of the usual (medians, place among the years); the service does not send it.
 * The years before it come from the morning satellite and are shown, but not compared. */
const BASE_FIRST_YEAR = 2003;
/** The card of a cell stands over it when the cell is this far from the top of the grid, and this far from the cell. */
const TIP_ROOM = 96;
const TIP_GAP = 4;
/** Below this width of the grid (px) a month has one letter over its cell; below the next, the usual row and totals go. */
const NARROW_GRID = 384;
const TIGHT_GRID = 264;
/** The widths the grid is told apart by: anything on the screen, then the two thresholds. */
const GRID_STEPS = [1, TIGHT_GRID, NARROW_GRID] as const;

/** The step of the grid colour a month falls in, from how it stands against the usual one. */
function levelOf(ratio: number | null | undefined): 0 | 1 | 2 | 3 | 4 | null {
  if (ratio == null) return null;
  if (ratio < 0.8) return 0;
  if (ratio < 1.25) return 1;
  if (ratio < 2) return 2;
  if (ratio < 4) return 3;
  return 4;
}

/** The share of a month that has data, from the day it is complete through. */
function shareOf(point: Point): number | null {
  if (!point.partial || !point.complete_through) return null;
  const [year, month, day] = point.complete_through.split('-').map(Number);
  if (!year || !month || !day) return null;
  return Math.min(1, day / new Date(Date.UTC(year, month, 0)).getUTCDate());
}

interface CalDashProps {
  data: Calendar;
  picked: string | null;
  onPick: (month: string) => void;
}

/** What the calendar tab shows of an area: the chosen month in four figures, the burning calendar and the months over time. */
export function CalDash({
  data,
  picked,
  onPick,
  tools,
  notice,
}: CalDashProps & {
  /** The period of the board and its file: they stay in view with the bar of sections while the board scrolls. */
  tools?: ReactNode;
  /** A word over the figures when they have nothing to tell, and the way to an area that has. */
  notice?: ReactNode;
}) {
  const { t } = useI18n();
  // the cards with periods of their own, and a month picked outside the period of the board, read the whole record
  const record = useRecord().data ?? data;
  const point =
    data.series.find((item) => item.month === picked) ??
    record.series.find((item) => item.month === picked);
  const firstYear = data.yearly[0]?.year;
  const lastYear = data.yearly[data.yearly.length - 1]?.year;
  const yearsPart =
    firstYear !== undefined && lastYear !== undefined && data.yearly.length < record.yearly.length
      ? record.yearly.filter((item) => item.year >= firstYear - 3 && item.year <= lastYear + 3)
      : null;
  const [current, setCurrent] = useState<Section>('overview');
  const [present, setPresent] = useState<readonly Section[]>(['overview', 'calendar', 'trend']);
  const root = useRef<HTMLDivElement>(null);
  const pinned = useRef(false);
  // ends the glide to a section that is going on
  const stopGlide = useRef<() => void>(() => undefined);
  useEffect(
    () => () => {
      stopGlide.current();
    },
    [],
  );
  const [more, setMore] = useState(false);
  // where the board scrolls in its own box, the cue that there is more below stands over the box, not in it
  const [host, setHost] = useState<HTMLElement | null>(null);
  const meta = useMeta().data;
  // months ahead have no count: the forecast of the model stands in the tiles and, dashed, in the calendar
  const coming = point?.count === null ? point.forecast : null;
  const ahead: Ahead | null = coming
    ? {
        value: coming.median,
        low: coming.low,
        high: coming.high,
        error: data.forecast?.accuracy?.year_error ?? null,
      }
    : null;

  // the board scrolls in its own box: the bar of sections lights the one in view, and the foot fades while there is more below
  useEffect(() => {
    const element = root.current;
    if (!element) return;
    const measure = () => {
      // the box is looked up each time: the layout changes it between the wide screen and the phone
      const scroller = scrollerOf(element);
      if (!scroller) return;
      const atEnd = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 8;
      setMore(!atEnd);
      const body = element.closest<HTMLElement>('.cal-body');
      setHost(body && getComputedStyle(body).display !== 'contents' ? body.parentElement : null);
      // tops are counted from the bottom of the sticky bar; a jump to a section stops under it, however tall it is
      const box = element.querySelector<HTMLElement>('[data-bar]')?.getBoundingClientRect();
      const bar = box?.bottom ?? 0;
      if (box) element.style.setProperty('--bar', `${String(Math.round(box.height))}px`);
      const places: { id: Section; top: number }[] = [];
      for (const id of NAMED) {
        const block = element.querySelector<HTMLElement>(`[data-section="${id}"]`);
        if (block && block.childElementCount > 0)
          places.push({ id, top: block.getBoundingClientRect().top - bar });
      }
      const here = places.map((place) => place.id);
      setPresent((was) => (was.join() === here.join() ? was : here));
      // a click on the bar lights its section at once and holds it while the scroll arrives
      if (pinned.current) return;
      setCurrent(
        activeSection(places, scroller.scrollTop, scroller.clientHeight, scroller.scrollHeight) ??
          'overview',
      );
    };
    measure();
    // scroll does not bubble: catch it on the way down, whichever box scrolls
    document.addEventListener('scroll', measure, { capture: true, passive: true });
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      document.removeEventListener('scroll', measure, { capture: true });
      observer.disconnect();
    };
  }, []);
  useEffect(() => {
    const scroller = root.current?.closest<HTMLElement>('.cal-body');
    if (scroller) scroller.dataset.more = more ? 'on' : 'off';
  }, [more]);

  const go = (id: Section) => {
    // a card without a name in the bar lights the one it belongs to
    setCurrent(NAMED.includes(id) ? id : id === 'known' ? 'accuracy' : 'trend');
    const element = root.current;
    const block = element?.querySelector<HTMLElement>(`[data-section="${id}"]`);
    const scroller = element ? scrollerOf(element) : null;
    if (!element || !block || !scroller) return;
    // the section stays lit while the board glides to it: the sections passed on the way do not light up
    pinned.current = true;
    stopGlide.current();
    const bar = element.querySelector<HTMLElement>('[data-bar]');
    stopGlide.current = glide(
      scroller,
      // the first section is the very top; any other stops with its head under the sticky bar
      () =>
        id === NAMED[0]
          ? 0
          : scroller.scrollTop +
            block.getBoundingClientRect().top -
            scroller.getBoundingClientRect().top -
            (bar?.offsetHeight ?? 0),
      () => {
        pinned.current = false;
      },
    );
  };
  const label: Record<Section, string> = {
    overview: t('dash.s.overview'),
    calendar: t('dash.s.calendar'),
    trend: t('dash.s.trend'),
    years: t('dash.s.years'),
    season: t('dash.s.season'),
    accuracy: t('dash.s.accuracy'),
    outlook: t('dash.s.outlook'),
    days: t('dash.s.days'),
    known: t('dash.s.known'),
    provinces: t('dash.s.regions'),
  };
  // on a narrow bar the names scroll sideways: the lit one is brought into view (the bar alone moves, not the page)
  useEffect(() => {
    const nav = root.current?.querySelector<HTMLElement>('nav');
    const lit = nav?.querySelector<HTMLElement>('[aria-current="true"]');
    if (!nav || !lit) return;
    const left = lit.getBoundingClientRect().left - nav.getBoundingClientRect().left + nav.scrollLeft;
    const right = left + lit.offsetWidth;
    if (left < nav.scrollLeft) nav.scrollLeft = left;
    else if (right > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = right - nav.clientWidth;
  }, [current]);

  const scrollOn = () => {
    const scroller = root.current ? scrollerOf(root.current) : null;
    scroller?.scrollBy({ top: scroller.clientHeight * 0.8, behavior: 'smooth' });
  };

  return (
    <>
      <div className={styles.dash} ref={root}>
        <div className={styles.sticky} data-bar>
          {tools ? <div className={styles.tools}>{tools}</div> : null}
          <nav className={styles.nav} aria-label={t('dash.sections')}>
            {NAMED.filter((id) => present.includes(id)).map((id) => (
              <button
                key={id}
                type="button"
                aria-current={current === id ? 'true' : undefined}
                onClick={() => {
                  go(id);
                }}
              >
                {label[id]}
              </button>
            ))}
          </nav>
        </div>
        <section className={styles.block} data-section="overview" aria-label={label.overview}>
          {notice}
          {point ? (
            <Tiles
              point={point}
              ahead={ahead}
              normals={data.normals}
              hasSeason={data.season !== null}
              show={(id) => ({
                label: label[id],
                run: () => {
                  go(id);
                },
              })}
            />
          ) : null}
        </section>
        <section className={styles.block} data-section="calendar" aria-label={label.calendar}>
          <CalendarCard
            picked={picked}
            point={point}
            record={record}
            onPick={onPick}
            change={meta ? changeMonth(meta.sensors) : null}
          />
        </section>
        <section className={styles.block} data-section="trend" aria-label={label.trend}>
          <TrendCard data={record} board={data} picked={picked} onPick={onPick} />
        </section>
        <section className={styles.block} data-section="years" aria-label={label.years}>
          {/* a period that is a part of the record shows its years, whole, and three more on each side */}
          <YearsCard
            data={yearsPart ? { ...record, yearly: yearsPart, trend: null } : record}
            part={yearsPart !== null}
            picked={picked}
          />
        </section>
        <MoreCards data={data} picked={picked} onPick={onPick} />
      </div>
      {host && more
        ? createPortal(
            <button type="button" className="cal-more" onClick={scrollOn}>
              {t('dash.more')}
              <Ph name="arrow-down" />
            </button>,
            host,
          )
        : null}
    </>
  );
}

/** The steps of the cell colour as the key of a map layer shows them: from how the month stands against the usual one. */
const SCALE = {
  id: 'cal',
  title: '',
  unit: '',
  bands: [
    { id: 0, low: 0, color: 'var(--c-subtle)' },
    { id: 1, low: 0.8, color: 'color-mix(in oklab, var(--fire-4) 22%, transparent)' },
    { id: 2, low: 1.25, color: 'color-mix(in oklab, var(--fire-4) 45%, transparent)' },
    { id: 3, low: 2, color: 'color-mix(in oklab, var(--fire-4) 72%, transparent)' },
    { id: 4, low: 4, color: 'var(--fire-5)' },
  ],
};

const RANGES = [
  ['2', 24],
  ['5', 60],
  ['10', 120],
  ['all', Infinity],
] as const;

type RangeId = (typeof RANGES)[number][0] | 'period';

/** The months over time: the value of the picked month in the head, the period and the satellites as segments, the line below. */
function TrendCard({
  data,
  board,
  picked,
  onPick,
}: CalDashProps & {
  /** The calendar of the period of the board: when it is a part of the record, the line opens on it. */
  board: Calendar;
}) {
  const { t, lang } = useI18n();
  const [chosen, setChosen] = useState<{ key: string; id: RangeId } | null>(null);
  const [each, setEach] = useState(false);
  const meta = useMeta().data;
  // the line is what was counted; the months ahead are in the calendar and the outlook
  const counted = data.series.filter((item) => item.kind !== 'forecast');
  const inBoard = board.series.filter((item) => item.kind !== 'forecast');
  const first = inBoard[0]?.month;
  const last = inBoard[inBoard.length - 1]?.month;
  const ofBoard =
    first && last ? counted.filter((item) => item.month >= first && item.month <= last) : [];
  const narrowed = ofBoard.length > 1 && ofBoard.length < counted.length;
  // a range chosen by hand holds while the period of the board stays the same
  const key = narrowed ? `${first}:${last}` : '';
  const range: RangeId = chosen?.key === key ? chosen.id : narrowed ? 'period' : '5';
  const size = RANGES.find(([id]) => id === range)?.[1] ?? 60;
  const months =
    range === 'period' ? ofBoard : Number.isFinite(size) ? counted.slice(-size) : counted;
  const shown =
    data.series.find((item) => item.month === picked) ??
    months.findLast((item) => item.count !== null);
  const satellites = each
    ? (meta?.sensors ?? [])
        .filter((sensor) =>
          data.series.some((month) => (month.raw[sensor.id as SensorId] ?? 0) > 0),
        )
        .map((sensor) => ({
          id: sensor.id,
          name: `${sensor.name}, ${(sensor.first ?? '').slice(0, 4)}–${(sensor.retired_at ?? sensor.last ?? '').slice(0, 4)}`,
          values: months.map((month) => month.raw[sensor.id as SensorId] ?? null),
        }))
    : undefined;
  const askers = useAskers();
  const folded = useFold('trend');
  const hasBand = !each && months.some((item) => item.converted);
  // a month ahead has no count: the figure of the forecast stands in its place
  const ahead = shown?.forecast?.median ?? null;

  return (
    <div className={styles.card}>
      <header className={styles.cardHead}>
        <div className={styles.cardTitle}>
          <div className={styles.titleLine}>
            <h2>{t('calendar.chart')}</h2>
            <Hint
              text={
                hasBand
                  ? `${t('dash.hint.trend')} ${t('dash.hint.converted')}`
                  : t('dash.hint.trend')
              }
            />
          </div>
          <p className={styles.note}>{t('dash.note.trend')}</p>
        </div>
        <div className={styles.cardFigure}>
          <b>
            {shown?.count != null
              ? formatCount(lang, shown.count)
              : ahead != null
                ? formatCount(lang, ahead, true)
                : '—'}
          </b>
          {shown ? <small>{longMonthYear(lang, shown.month)}</small> : null}
        </div>
        <FoldButton folded={folded.value} onClick={folded.toggle} />
      </header>
      {folded.value ? null : (
        <>
          <div className={styles.cardTools}>
            <Segments
              label={t('dash.range.label')}
              items={[
                ...(narrowed ? [['period', t('dash.range.period')] as const] : []),
                ...RANGES.map(([id]) => [id, t(`dash.range.${id}`)] as const),
              ]}
              value={range}
              onChange={(id: RangeId) => {
                setChosen({ key, id });
              }}
            />
            {meta ? (
              <div className={styles.titleLine}>
                <Hint text={t('dash.trend.hint')} />
                <Segments
                  label={t('calendar.chart')}
                  items={[
                    [false, t('dash.trend.harm')],
                    [true, t('dash.trend.each')],
                  ]}
                  value={each}
                  onChange={setEach}
                />
              </div>
            ) : null}
          </div>
          <MonthsChart
            months={months}
            picked={picked}
            onPick={onPick}
            satellites={satellites}
            ask={
              each
                ? undefined
                : (month) => {
                    const point = data.series.find((item) => item.month === month);
                    return point ? askers?.month(point) : null;
                  }
            }
          />
        </>
      )}
    </div>
  );
}

/** The box the board scrolls in: the wide layout scrolls `.cal-body`, the phone layout the view around it. */
function scrollerOf(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node; node = node.parentElement) {
    const { overflowY } = getComputedStyle(node);
    if ((overflowY === 'auto' || overflowY === 'scroll') && node.clientHeight > 0) return node;
  }
  return null;
}

/** The first full month of the second family of satellites: where the series changes its instrument. */
function changeMonth(sensors: readonly { id: string; first: string | null }[]): string | null {
  const first = sensors
    .filter((sensor) => sensor.id.startsWith('viirs'))
    .map((sensor) => sensor.first ?? '')
    .sort()
    .find(Boolean);
  if (!first) return null;
  const [year, month, day] = first.split('-').map(Number);
  if (!year || !month || !day) return null;
  const next = day === 1 ? [year, month] : month === 12 ? [year + 1, 1] : [year, month + 1];
  return `${String(next[0])}-${String(next[1]).padStart(2, '0')}`;
}

/** The forecast of a month ahead: the figure of the model, the range it is likely in, the error of such a forecast. */
interface Ahead {
  value: number;
  low: number | null;
  high: number | null;
  error: number | null;
}

function Tiles({
  point,
  ahead,
  normals,
  hasSeason,
  show,
}: {
  point: Point;
  ahead: Ahead | null;
  normals: Calendar['normals'];
  /** The area has a card of its season: the usual figure is explained there, else by the calendar. */
  hasSeason: boolean;
  /** The second segment of a tile's pill: it glides the board to the card that explains the figure. */
  show: (id: Section) => NonNullable<AskInfo['show']>;
}) {
  const { t, lang } = useI18n();
  const askers = useAskers();
  const actions = useWidgetActions();
  const count = (value: number | null) => (value === null ? '—' : formatCount(lang, value));
  const level = levelOf(point.ratio);
  const month = longMonth(lang, point.month);
  const kind = monthVerdict(point);
  const few = kind === 'few';
  // no fires against no usual fires: a percent, a place among the years — there is nothing to say
  const none = kind === 'none';
  const verdict = ahead
    ? t('dash.verdict.outlook', { m: longMonthYear(lang, point.month) })
    : kind === null
      ? null
      : t(
          kind === 'few' || kind === 'none'
            ? (`dash.verdict.${kind}` as const)
            : (`dash.verdict.${kind}${point.partial ? 'SoFar' : ''}` as const),
          { m: month, n: count(point.count), u: count(point.median) },
        );
  const anomaly = point.count === null || point.median === null ? null : point.count - point.median;
  const signed =
    anomaly === null
      ? '—'
      : `${anomaly > 0 ? '+' : anomaly < 0 ? '−' : ''}${formatCount(lang, Math.abs(anomaly))}`;
  const ratio = ahead && point.median ? ahead.value / point.median : null;
  const percent = new Intl.NumberFormat(LOCALES[lang], {
    style: 'percent',
    maximumFractionDigits: 0,
  });
  // a month still running is read against the same dates; the usual of the whole month is a line of small print
  const whole = normals.find((normal) => normal.month === Number(point.month.slice(5)))?.median;
  const wholeMonth = point.partial && whole != null ? whole : null;
  const forecastTiles = ahead
    ? [
        {
          key: 'count',
          label: t('dash.s.outlook'),
          big: formatCount(lang, ahead.value, true),
          sub:
            ahead.low !== null && ahead.high !== null
              ? t('dash.between', {
                  a: formatNice(lang, ahead.low),
                  b: formatNice(lang, ahead.high),
                })
              : longMonthYear(lang, point.month),
        },
        {
          key: 'usual',
          label: t('dash.cal.usual'),
          big: count(point.median),
          sub: t('area.median'),
        },
        {
          key: 'against',
          label: t('dash.tile.against'),
          big: ratio === null ? '—' : formatChange(lang, ratio),
          sub: '',
          tone: ratio !== null && ratio > 1.25 ? ('more' as const) : undefined,
        },
        {
          key: 'rank',
          label: t('dash.acc.forecast'),
          big: ahead.error === null ? '—' : `±${percent.format(ahead.error)}`,
          sub: '',
        },
      ]
    : null;
  const tiles: { key: string; label: string; big: string; sub: string; tone?: 'more' }[] =
    forecastTiles ?? [
      {
        key: 'count',
        label: t('regions.detections'),
        big: count(point.count),
        sub: point.partial
          ? point.complete_through
            ? t('dash.tile.sub.through', { date: dateText(lang, point.complete_through) })
            : t('area.partial')
          : longMonthYear(lang, point.month),
      },
      {
        key: 'usual',
        // a month still running is read against the same dates; a whole month, against its usual
        label: point.partial ? t('dash.tile.usual') : t('dash.cal.usual'),
        big: count(point.median),
        sub:
          wholeMonth === null
            ? t('area.median')
            : t('dash.tile.sub.whole', { n: formatCount(lang, wholeMonth) }),
      },
      {
        key: 'against',
        label: t('dash.tile.against'),
        // a handful of fires is told by the difference: "+100 %" of one fire says nothing
        big: none
          ? '—'
          : few
            ? signed
            : point.ratio === null
              ? '—'
              : formatChange(lang, point.ratio),
        sub: few || none ? '' : signed,
        tone: level !== null && level > 1 ? 'more' : undefined,
      },
      {
        key: 'rank',
        label: t('kpi.rank'),
        big: none || point.rank === null ? '—' : `#${String(point.rank)}`,
        sub: none ? '' : t('dash.tile.ofYears', { n: point.of ?? 0 }),
      },
    ];
  // the card each figure is explained by; a month ahead and the error of its forecast are told by the outlook
  const usual: Section = hasSeason ? 'season' : 'calendar';
  const cardOf: Record<string, Section> = ahead
    ? { count: 'outlook', usual, against: 'calendar', rank: 'outlook' }
    : { count: 'trend', usual, against: 'calendar', rank: 'years' };
  // the first tile is the month itself, the others are figures of it
  const asking = tiles.map((tile) => {
    const target = cardOf[tile.key];
    const to = target ? show(target) : undefined;
    const month = tile.key === 'count' ? askers?.month(point) : undefined;
    return {
      ...tile,
      ask:
        tile.key === 'count'
          ? month && { ...month, show: to }
          : askers?.fact(tile.label, tile.big, point.month, {
              note: tile.sub || undefined,
              show: to,
            }),
    };
  });
  return (
    <>
      <div className={styles.lead}>
        <h2>{verdict ?? longMonthYear(lang, point.month)}</h2>
        {askers ? (
          <button
            type="button"
            className={`btn btn-secondary ${styles.leadAsk}`}
            onClick={() => {
              actions?.addMonth(point.month);
            }}
          >
            <Ph name="sparkle" />
            <span>{t('chat.askAi')}</span>
          </button>
        ) : null}
      </div>
      <TileGrid items={asking} />
    </>
  );
}

function CalendarCard({
  picked,
  record,
  point,
  onPick,
  change,
}: {
  /** The whole record, whatever the period of the board: the grid is the map of it. */
  record: Calendar;
  picked: string | null;
  point: Point | undefined;
  onPick: (month: string) => void;
  /** The month the satellites of the series change in. */
  change: string | null;
}) {
  const { t, lang } = useI18n();
  const phone = useMediaQuery('(max-width: 60rem)');
  // on a narrow phone three letters do not fit over a cell: one letter stands, the full name is its label
  // the same goes for a narrow board on a wide window (the chat open): the width of the grid decides, not the window
  const { ref: gridRef, width: gridWidth } = useWidth(GRID_STEPS);
  const narrow = useMediaQuery('(max-width: 30rem)') || (gridWidth > 0 && gridWidth < NARROW_GRID);
  // a grid narrower still gives up the usual row and the totals, so the cells stay wide enough to press
  const tight = gridWidth > 0 && gridWidth < TIGHT_GRID;
  const [all, setAll] = useState(false);
  // the month under the pointer and where its cell stands in the box of the grid
  const [tip, setTip] = useState<{ month: string; left: number; top: number; above: boolean } | null>(
    null,
  );
  // where the card of the colour scale stands under it, while the pointer is on the scale
  const [scaleTip, setScaleTip] = useState<number | null>(null);
  const askers = useAskers();
  const ask = useAskPop();
  const months = shortMonths(lang);
  const points = new Map(record.series.map((item) => [item.month, item]));
  const showTip = (month: string, cell: HTMLElement) => {
    const box = cell.offsetParent?.clientWidth ?? 0;
    // over the cell, or under it in the first rows, where there is no room above
    const above = cell.offsetTop >= TIP_ROOM;
    setTip({
      month,
      left: tipLeft(cell.offsetLeft + cell.offsetWidth / 2, box),
      top: above ? cell.offsetTop - TIP_GAP : cell.offsetTop + cell.offsetHeight + TIP_GAP,
      above,
    });
  };
  const tipLines = (item: Point): string[] => {
    const name = longMonthYear(lang, item.month);
    const ahead = item.count === null ? item.forecast : null;
    if (ahead)
      return [
        name,
        `${t('dash.s.outlook')} ${formatCount(lang, ahead.median, true)}`,
        t('dash.between', { a: formatCount(lang, ahead.low), b: formatCount(lang, ahead.high) }),
        item.median === null ? '' : t('pop.norm', { n: formatCount(lang, item.median) }),
      ].filter(Boolean);
    const facts = monthFacts(t, lang, item);
    return [
      name,
      facts?.value ?? '',
      facts?.note ?? '',
      item.partial && item.complete_through
        ? t('dash.cal.through', { date: dateText(lang, item.complete_through) })
        : '',
    ].filter(Boolean);
  };
  const shown = tip ? points.get(tip.month) : undefined;
  // the grid is the map of the whole record, whatever the period: the month is picked on it
  const every = [...new Set(record.series.map((item) => item.month.slice(0, 4)))];
  const years = phone && !all ? every.slice(-PHONE_YEARS) : every;
  const scale = scaleOf(
    Math.max(
      0,
      ...record.series.map((item) => item.count ?? 0),
      ...record.normals.map((normal) => normal.median ?? 0),
    ),
  );
  const compact = { format: (value: number) => cellText(lang, value, scale) };
  const normals = new Map(record.normals.map((normal) => [normal.month, normal]));
  const usualTotal = record.normals.reduce((sum, normal) => sum + (normal.median ?? 0), 0);
  // a year with nothing counted yet, the one ahead, has no total
  const total = (year: string) => {
    const seen = record.series.filter((item) => item.month.startsWith(year) && item.count !== null);
    return seen.length === 0 ? null : seen.reduce((sum, item) => sum + (item.count ?? 0), 0);
  };
  // the first year with nothing counted and a forecast in it: its row is the forecast alone, set apart by a line
  const forecastYear = every.find(
    (year) =>
      total(year) === null &&
      record.series.some((item) => item.month.startsWith(year) && item.forecast != null),
  );
  const caption = point
    ? [
        longMonthYear(lang, point.month),
        point.count === null
          ? point.forecast
            ? `${t('dash.s.outlook').toLocaleLowerCase(LOCALES[lang])} ${formatCount(lang, point.forecast.median, true)}`
            : '—'
          : `${formatCount(lang, point.count)} ${t('regions.detections').toLocaleLowerCase(LOCALES[lang])}`,
        point.partial && point.complete_through
          ? t('dash.cal.through', { date: dateText(lang, point.complete_through) })
          : '',
      ]
        .filter(Boolean)
        .join(', ')
    : '';
  return (
    <div className={styles.card}>
      <header className={styles.cardHead}>
        <div className={styles.cardTitle}>
          <div className={styles.titleLine}>
            <h2>{t('dash.cal.title')}</h2>
            <Hint text={t('dash.hint.calendar')} />
          </div>
        </div>
        {/* the key of the grid stands by its title: on the right, or under it where the card is narrow;
            it is the strip alone, and its name shows under the pointer */}
        <div
          className={styles.scale}
          onPointerEnter={(event) => {
            if (event.pointerType !== 'touch') setScaleTip(event.currentTarget.offsetHeight + TIP_GAP);
          }}
          onPointerLeave={() => {
            setScaleTip(null);
          }}
        >
          {scaleTip === null ? null : (
            <ChartTip
              left={0}
              top={scaleTip}
              lines={[`${t('dash.tile.against')}, %`, t('dash.scale.tip')]}
            />
          )}
          <LayerKey
            rows={[
              {
                ...SCALE,
                title: t('dash.tile.against'),
                // the cells say the same: the change in percent, without the sign of percent in each
                unit: '%',
                format: (value) => formatChange(lang, value).replace(' %', ''),
              },
            ]}
          />
        </div>
      </header>
      {/* a cell carries its count; its colour says how the count stands against the usual one */}
      <p className={styles.sentence}>{t(`dash.unit.${scale}`)}</p>
      <div className={styles.gridBox} ref={gridRef}>
        <div
          className={tight ? `${styles.grid} ${styles.tight}` : styles.grid}
          role="group"
          aria-label={t('years.grid')}
        >
          <span />
          {months.map((month) => (
            <span key={month} className={styles.head} title={narrow ? month : undefined}>
              {narrow ? month.slice(0, 1) : month}
            </span>
          ))}
          {tight ? null : (
            <>
              <span className={styles.head}>{t('dash.cal.total')}</span>
              <span className={styles.label}>{t('dash.cal.usual')}</span>
              {months.map((month, index) => {
                const value = normals.get(index + 1)?.median;
                return (
                  <span key={month} className={styles.usual}>
                    {narrow ? null : value == null ? '—' : compact.format(value)}
                  </span>
                );
              })}
              <span className={styles.sum}>{compact.format(usualTotal)}</span>
            </>
          )}
          {years.map((year, position) => (
            <Fragment key={year}>
              {/* the line heads the years before the usual, the first rows of the grid */}
              {position === 0 && Number(year) < BASE_FIRST_YEAR ? (
                <div className={styles.change}>
                  <span>{t('dash.cal.early')}</span>
                </div>
              ) : null}
              {change && position > 0 && year === change.slice(0, 4) ? (
                <div className={styles.change}>
                  <span>{t('dash.cal.change', { m: longMonthYear(lang, change) })}</span>
                </div>
              ) : null}
              {year === forecastYear ? (
                <div className={styles.change}>
                  <span>{t('dash.cal.forecast')}</span>
                </div>
              ) : null}
              <div className={styles.row}>
                <span
                  className={styles.label}
                  data-forecast={year === forecastYear ? 'on' : undefined}
                >
                  {year}
                </span>
                {months.map((_, index) => {
                  const month = `${year}-${String(index + 1).padStart(2, '0')}`;
                  const item = points.get(month);
                  const level = levelOf(item?.ratio);
                  const share = item ? shareOf(item) : null;
                  const ahead = item?.count == null ? item?.forecast?.median : undefined;
                  const text =
                    item?.count == null
                      ? ahead == null
                        ? ''
                        : compact.format(ahead)
                      : compact.format(item.count);
                  return (
                    <button
                      key={month}
                      type="button"
                      className={styles.cell}
                      // nothing seen is the palest step, whatever the ratio: the service gives 0 against a usual 0 the ratio 1, «near usual»
                      data-level={
                        item?.count == null ? 'none' : item.count === 0 ? '0' : String(level ?? 1)
                      }
                      data-forecast={ahead == null ? undefined : 'on'}
                      data-unusual={level !== null && level >= 3 ? 'on' : undefined}
                      data-partial={share === null ? undefined : 'on'}
                      style={
                        share === null
                          ? undefined
                          : ({ '--share': `${String(Math.round(share * 100))}%` } as CSSProperties)
                      }
                      disabled={!item}
                      aria-pressed={picked === month}
                      // a touch has no hover: its press picks the month, and the caption under the grid names it
                      onPointerEnter={(event) => {
                        if (event.pointerType !== 'touch') showTip(month, event.currentTarget);
                      }}
                      onPointerLeave={() => {
                        setTip(null);
                      }}
                      onFocus={(event) => {
                        if (event.currentTarget.matches(':focus-visible'))
                          showTip(month, event.currentTarget);
                      }}
                      onBlur={() => {
                        setTip(null);
                      }}
                      {...ask.bind(item ? askers?.month(item) : null, {
                        onPick: () => {
                          setTip(null); // the pill of the press stands where the card was
                          onPick(month);
                        },
                      })}
                    >
                      {text}
                      {/* the name starts with what is seen in the cell, then says the month and the count */}
                      <span className="visually-hidden">
                        {` ${longMonthYear(lang, month)}: ${
                          item?.count == null
                            ? ahead == null
                              ? '—'
                              : `${t('dash.cal.forecast')} ${formatCount(lang, ahead, true)}`
                            : formatCount(lang, item.count)
                        }`}
                      </span>
                    </button>
                  );
                })}
                {tight ? null : (
                  <span className={styles.sum}>
                    {total(year) === null ? '' : compact.format(total(year) ?? 0)}
                  </span>
                )}
              </div>
            </Fragment>
          ))}
        </div>
        {tip && shown ? (
          <ChartTip left={tip.left} top={tip.top} above={tip.above} lines={tipLines(shown)} />
        ) : null}
      </div>
      {phone && every.length > PHONE_YEARS ? (
        <button
          type="button"
          className={styles.expand}
          aria-expanded={all}
          onClick={() => {
            setAll((now) => !now);
          }}
        >
          {all
            ? t('dash.cal.fewer', { n: PHONE_YEARS })
            : t('dash.cal.allYears', { n: every.length })}
        </button>
      ) : null}
      <p className={styles.caption} aria-live="polite">
        {caption}
      </p>
      {ask.card}
    </div>
  );
}

/** A bar of a year: the card names the year and its total; its button puts them into the question. */
function YearBar({
  year,
  total,
  current,
  partial,
  converted,
  height,
  ask,
  onTip,
}: {
  year: string;
  total: string;
  current: boolean;
  partial: boolean;
  converted: boolean;
  height: number;
  ask: ReturnType<typeof useAskPop>;
  /** The pointer or the keyboard is on the bar (the element), or left it (null). */
  onTip: (bar: HTMLElement | null) => void;
}) {
  const { t } = useI18n();
  const askers = useAskers();
  const text = `${year}: ${total}`;
  return (
    <button
      type="button"
      className={styles.bar}
      data-current={current ? 'on' : undefined}
      data-partial={partial ? 'on' : undefined}
      data-converted={converted ? 'on' : undefined}
      style={{ '--h': `${String(height)}%` } as CSSProperties}
      aria-label={text}
      // a touch has no hover: its press opens the pill
      onPointerEnter={(event) => {
        if (event.pointerType !== 'touch') onTip(event.currentTarget);
      }}
      onPointerLeave={() => {
        onTip(null);
      }}
      onFocus={(event) => {
        if (event.currentTarget.matches(':focus-visible')) onTip(event.currentTarget);
      }}
      onBlur={() => {
        onTip(null);
      }}
      {...ask.bind(askers?.fact(t('dash.s.years'), total, year, { note: year }))}
    />
  );
}

/** The years side by side: the total of each, the strongest marked in the heading. */
function YearsCard({
  data,
  picked,
  part = false,
}: {
  data: Calendar;
  picked: string | null;
  /** Only some years of the record are shown: the record year of all of them is not named. */
  part?: boolean;
}) {
  const { t, lang } = useI18n();
  const ask = useAskPop();
  const years = data.yearly.map((item) => ({
    year: String(item.year),
    total: item.count,
    partial: !item.complete,
    converted: item.converted,
  }));
  const anyConverted = years.some((item) => item.converted);
  const [tip, setTip] = useState<{ year: string; left: number; box: number } | null>(null);
  const trend = data.trend;
  const shown = tip ? years.find((item) => item.year === tip.year) : undefined;
  const top = years.reduce<(typeof years)[number] | undefined>(
    (best, item) => (best && best.total >= item.total ? best : item),
    undefined,
  );
  const max = Math.max(1, top?.total ?? 1);
  return (
    <div className={styles.card}>
      <header className={styles.cardHead}>
        <div className={styles.cardTitle}>
          <div className={styles.titleLine}>
            <h2>{t('dash.s.years')}</h2>
            {trend ? (
              <small>{t('dash.years.trend', { p: trendText(trend.percent_per_year, lang) })}</small>
            ) : null}
            <Hint
              text={
                anyConverted
                  ? `${t('dash.hint.years')} ${t('dash.hint.converted')}`
                  : t('dash.hint.years')
              }
            />
          </div>
        </div>
        {top && !part ? <small>{t('dash.years.record', { year: top.year })}</small> : null}
      </header>
      <div className={styles.bars} role="group" aria-label={t('dash.s.years')}>
        {years.map((item) => (
          <YearBar
            key={item.year}
            year={item.year}
            total={formatCount(lang, item.total)}
            current={picked?.startsWith(item.year) ?? false}
            partial={item.partial}
            converted={item.converted}
            height={Math.round((item.total / max) * 100)}
            ask={ask}
            onTip={(bar) => {
              setTip(
                bar
                  ? {
                      year: item.year,
                      left: bar.offsetLeft + bar.offsetWidth / 2,
                      box: bar.parentElement?.clientWidth ?? 0,
                    }
                  : null,
              );
            }}
          />
        ))}
        {shown ? (
          <ChartTip
            left={tipLeft(tip?.left ?? 0, tip?.box ?? 0)}
            lines={[
              shown.year,
              formatCount(lang, shown.total),
              shown.partial
                ? t('dash.tile.sub.through', { date: dateText(lang, data.last_complete_date) })
                : '',
              shown.converted ? t('dash.legend.converted') : '',
            ].filter(Boolean)}
          />
        ) : null}
      </div>
      {ask.card}
      <div className={styles.axis}>
        <span>{years[0]?.year}</span>
        <span>{years.at(-1)?.year}</span>
      </div>
      {anyConverted ? <p className={styles.bandKey}>{t('dash.legend.converted')}</p> : null}
    </div>
  );
}

/** The change of a year, as the heading of the card tells it: a sign, the number, a percent. */
function trendText(percent: number, lang: Lang): string {
  if (percent === 0) return '0 %';
  const number = new Intl.NumberFormat(LOCALES[lang]).format(Math.abs(percent));
  return `${percent > 0 ? '+' : '−'}${number} %`;
}
