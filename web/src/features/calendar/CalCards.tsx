import { useState, type CSSProperties, type ReactNode } from 'react';
import type { Calendar } from '../../api/calendar';
import type { components } from '../../api/schema';
import { areaId } from '../../config/context';
import { useI18n, type I18n } from '../../i18n/context';
import { LOCALES, localName, type Lang } from '../../i18n/lang';
import { Ph } from '../../ui/Ph';
import { useAskPop } from '../../ui/AskPop';
import { useAskers } from './askInfo';
import { Hint } from './Hint';
import { useBoard } from '../board/context';
import { ChartTip, tipLeft } from '../../ui/ChartTip';
import { daysByDate, wholeDays } from '../climate/days';
import { useDaysArea, useMonthDays } from '../climate/queries';
import { useFiresState } from '../fires/context';
import { RangeChart } from './CalChart';
import { Provinces } from './Provinces';
import { WORLD } from './areas';
import { useCalendar, useCountryArea, useMeta, usePicked, useRange } from './queries';
import {
  dateText,
  dayFigures,
  formatChange,
  formatCount,
  formatNice,
  longMonth,
  longMonthYear,
} from './text';
import styles from './CalDash.module.css';

/** A row of a card: what it is on the left, the figure on the right, a hairline between rows. */
function Row({
  label,
  value,
  hint,
  warn,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: string;
  warn?: boolean;
}) {
  const range = useRange().range;
  const period = range ? `${range.from}..${range.to}` : '';
  const pop = useAskPop();
  const askers = useAskers();
  const info =
    typeof label === 'string' && typeof value === 'string'
      ? askers?.fact(label, value, period, { note: hint })
      : null;
  return (
    <>
      <div
        className={styles.metric}
        data-ask={info ? 'on' : undefined}
        {...(info ? pop.bind(info) : {})}
      >
        <dt>
          {label}
          {hint ? (
            <span data-no-ask="">
              <Hint text={hint} />
            </span>
          ) : null}
        </dt>
        <dd className={warn ? styles.warn : undefined}>
          {info ? (
            <button type="button" className={styles.askValue} aria-haspopup="dialog">
              {value}
            </button>
          ) : (
            value
          )}
        </dd>
      </div>
      {pop.card}
    </>
  );
}

function Card({
  id,
  title,
  note,
  lead,
  children,
}: {
  id: 'season' | 'accuracy' | 'outlook' | 'days' | 'known';
  title: string;
  note: string;
  lead?: string;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const folded = useFold(id);
  return (
    <div className={styles.card}>
      <header className={styles.cardHead}>
        <div className={styles.cardTitle}>
          <div className={styles.titleLine}>
            <h2>{title}</h2>
            <Hint text={t(`dash.hint.${id}` as const)} />
          </div>
          <p className={styles.note}>{note}</p>
        </div>
        <FoldButton folded={folded.value} onClick={folded.toggle} />
      </header>
      {folded.value ? null : (
        <>
          {lead ? <p className={styles.sentence}>{lead}</p> : null}
          {children}
        </>
      )}
    </div>
  );
}

type Season = components['schemas']['Season'];

const FOLDS = 'senda-cal-folds';

/** The cards folded to their head, kept in one key for the whole board. */
function readFolds(): Record<string, boolean> {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(FOLDS) ?? '{}');
    return stored && typeof stored === 'object' ? (stored as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

/** A card folds to its head; the choice is remembered. */
export function useFold(id: string) {
  const [value, setValue] = useState(() => readFolds()[id] === true);
  return {
    value,
    toggle: () => {
      const next = !value;
      setValue(next);
      try {
        localStorage.setItem(FOLDS, JSON.stringify({ ...readFolds(), [id]: next }));
      } catch {
        // storage can be closed: the card still folds for this visit
      }
    },
  };
}

export function FoldButton({ folded, onClick }: { folded: boolean; onClick: () => void }) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      className={styles.fold}
      aria-expanded={!folded}
      aria-label={folded ? t('dash.unfold') : t('dash.fold')}
      onClick={onClick}
    >
      <Ph name={folded ? 'caret-down' : 'caret-up'} />
    </button>
  );
}

const monthName = (lang: Lang, month: number) =>
  longMonth(lang, `2000-${String(month).padStart(2, '0')}`);

/** The name of a month as it stands after a preposition ("с августа" in Russian): the month part of a date with a day. */
const monthAfter = (lang: Lang, month: number) =>
  new Intl.DateTimeFormat(LOCALES[lang], { day: 'numeric', month: 'long', timeZone: 'UTC' })
    .formatToParts(new Date(Date.UTC(2000, month - 1, 15)))
    .find((part) => part.type === 'month')?.value ?? monthName(lang, month);

/** The months of the season as the sentence says them: the first to the last. */
function seasonSentence(t: I18n['t'], lang: Lang, season: Season): string | null {
  const first = season.season_months[0];
  const last = season.season_months.at(-1);
  if (first === undefined || last === undefined) return null;
  const p = String(Math.round((season.season_share ?? 0) * 100));
  return first === last
    ? t('dash.season.leadOne', { a: monthName(lang, first), p })
    : t('dash.season.lead', { a: monthAfter(lang, first), b: monthAfter(lang, last), p });
}

/** What the archive says of the year of this area: the strongest and the quietest, the season, the year so far. */
export function SeasonCard({ season }: { season: Season }) {
  const { t, lang } = useI18n();
  const count = (n: number) => formatCount(lang, n);
  return (
    <Card
      id="season"
      title={t('dash.s.season')}
      note={t('dash.note.season')}
      lead={seasonSentence(t, lang, season) ?? undefined}
    >
      <dl className={styles.metrics}>
        <Row
          label={t('dash.season.record', { y: season.record_year.year })}
          value={count(season.record_year.count)}
        />
        <Row
          label={t('dash.season.quiet', { y: season.quiet_year.year })}
          value={count(season.quiet_year.count)}
        />
        <Row
          label={t('dash.season.peak', { m: monthName(lang, season.peak_month.month) })}
          value={count(season.peak_month.median ?? 0)}
        />
        <Row
          label={t('dash.season.quietMonth', { m: monthName(lang, season.quiet_month.month) })}
          value={count(season.quiet_month.median ?? 0)}
        />
        <Row label={t('dash.season.average')} value={count(season.average_year)} />
        {season.ytd ? (
          <>
            <Row
              label={t('dash.season.ytd', {
                m: longMonthYear(lang, season.ytd.through),
              })}
              value={count(season.ytd.count)}
            />
            <Row
              label={t('dash.season.lastYear')}
              value={`${count(season.ytd.last_year)}, ${formatChange(lang, season.ytd.ratio)}`}
            />
          </>
        ) : null}
        <Row label={t('dash.season.unusual')} value={count(season.unusual_months.count)} />
        <Row
          label={t('dash.season.strength')}
          value={new Intl.NumberFormat(LOCALES[lang], { maximumFractionDigits: 1 }).format(
            season.season_strength,
          )}
        />
      </dl>
    </Card>
  );
}

/** Which method gave the months ahead, as a short value: the model, the model first and then the median, or the median alone. */
function methodValue(t: I18n['t'], model: number, months: number) {
  if (model <= 0) return t('dash.method.median');
  return model >= months ? t('dash.method.model') : t('dash.method.mixed', { k: model });
}

type Seam = NonNullable<Calendar['quality']['seam']>;

/** The figures of the check of the join, one decimal: the gap with its sign, the usual gap without a change; null where the check has none. */
function seamFigures(lang: Lang, seam: Seam) {
  const one = (signDisplay: 'exceptZero' | 'auto') =>
    new Intl.NumberFormat(LOCALES[lang], {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
      signDisplay,
    });
  return {
    // the minus of the other figures of the board (`formatChange`)
    gap: seam.gap_pct === null ? null : one('exceptZero').format(seam.gap_pct).replace('-', '−'),
    threshold: seam.threshold_pct === null ? null : one('auto').format(seam.threshold_pct),
  };
}

/** The check of the join of the sensors in 2012: the verdict and how far our series is from the reference there. */
function SeamRow({ seam }: { seam: Seam }) {
  const { t, lang } = useI18n();
  const { gap } = seamFigures(lang, seam);
  const year = seam.seam.slice(0, 4);
  const value =
    gap === null || seam.status === 'insufficient'
      ? t('dash.seam.insufficient')
      : t(`dash.seam.${seam.status}` as const, { g: gap });
  const hint = [
    t('dash.seam.hint', { y: year }),
    seam.kind === 'zone' ? t('dash.seam.zone') : '',
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <Row
      label={t('dash.seam.label', { y: year })}
      hint={hint}
      value={value}
      warn={seam.status === 'fail'}
    />
  );
}

/** How far the series can be trusted: the error of the area and the check of the join of the sensors; the notes only when there is something to say. */
export function AccuracyCard({ data }: { data: Calendar }) {
  const { t, lang } = useI18n();
  const { quality } = data;
  const percent = new Intl.NumberFormat(LOCALES[lang], {
    style: 'percent',
    maximumFractionDigits: 1,
  });
  const notes = [
    data.area.approximate ? t('area.approximate') : '',
    quality.expected_error === null ? t('area.qualityUnknown') : '',
    quality.confidence === 'low' ? t('area.confidence.low') : '',
    quality.unharmonized_share >= 0.01
      ? t('area.unharmonized', {
          p: new Intl.NumberFormat(lang, { style: 'percent', maximumSignificantDigits: 2 }).format(
            quality.unharmonized_share,
          ),
        })
      : '',
  ].filter(Boolean);
  // how the older satellite is brought to the scale of the newer one and what the two figures above mean, seen without the hints
  const seam = quality.seam ?? null;
  const figures = seam ? seamFigures(lang, seam) : null;
  const how = [
    t('dash.acc.how'),
    quality.expected_error === null
      ? ''
      : t('dash.acc.howError', { e: percent.format(quality.expected_error) }),
    seam && figures?.gap != null && figures.threshold != null && seam.status !== 'insufficient'
      ? t('dash.acc.howSeam', { y: seam.seam.slice(0, 4), g: figures.gap, th: figures.threshold })
      : '',
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <Card id="accuracy" title={t('dash.s.accuracy')} note={t('dash.note.accuracy')}>
      <dl className={styles.metrics}>
        {quality.expected_error !== null ? (
          <Row
            label={t('dash.acc.error')}
            hint={t('dash.acc.errorHint')}
            value={`±${percent.format(quality.expected_error)}`}
          />
        ) : null}
        {seam ? <SeamRow seam={seam} /> : null}
      </dl>
      <p className={styles.sentence}>{how}</p>
      {notes.length > 0 ? (
        <div className={styles.source}>
          <b>{t('dash.source')}</b>
          <p className="note">{notes.join(' · ')}</p>
        </div>
      ) : null}
    </Card>
  );
}

/** The months ahead from the forecast of the area, with how wrong such a forecast has been. */
export function OutlookCard({
  data,
  picked,
  onPick,
}: {
  data: Calendar;
  picked: string | null;
  onPick: (m: string) => void;
}) {
  const { t, lang } = useI18n();
  const ahead = data.series.filter((item) => item.forecast);
  const error = data.forecast?.accuracy?.year_error;
  const first = ahead[0]?.forecast?.err_pct ?? null;
  const monthError = (data.forecast?.model_months ?? 0) > 0 ? first : null;
  if (ahead.length === 0) return null;
  const sum = (pick: 'median' | 'low' | 'high') =>
    ahead.reduce((total, item) => total + (item.forecast?.[pick] ?? 0), 0);
  return (
    <Card
      id="outlook"
      title={t('dash.s.outlook')}
      note={t('dash.note.outlook')}
      lead={t('dash.outlook.lead', { k: ahead.length, n: formatNice(lang, sum('median')) })}
    >
      <RangeChart months={ahead} picked={picked} onPick={onPick} title={t('dash.s.outlook')} />
      <dl className={styles.metrics}>
        <Row
          label={t('dash.outlook.likely')}
          value={t('dash.between', {
            a: formatNice(lang, sum('low')),
            b: formatNice(lang, sum('high')),
          })}
        />
        <Row
          label={t('dash.method.label')}
          hint={t('dash.method.hint')}
          value={methodValue(t, data.forecast?.model_months ?? 0, ahead.length)}
        />
        {monthError !== null ? (
          <Row
            label={t('dash.method.error')}
            hint={t('dash.method.errorHint')}
            value={`±${new Intl.NumberFormat(LOCALES[lang], { style: 'percent', maximumFractionDigits: 0 }).format(monthError / 100)}`}
          />
        ) : error === undefined ? null : (
          <Row
            label={t('dash.acc.forecast')}
            hint={t('dash.acc.forecastHint')}
            value={`±${new Intl.NumberFormat(LOCALES[lang], { style: 'percent', maximumFractionDigits: 0 }).format(error)}`}
          />
        )}
      </dl>
    </Card>
  );
}

/** The days of the month on the board: a bar for each, a click opens the day on the map and its player. */
export function DaysCard({ onPick }: { onPick: (month: string) => void }) {
  const { t, lang } = useI18n();
  const board = useBoard();
  const fires = useFiresState();
  const month = usePicked();
  const pop = useAskPop();
  const askers = useAskers();
  // the server gives the days of the whole world as well, though the climate layers do not cover it
  const covered = useDaysArea(board.area);
  const days = useMonthDays(month, areaId(board.area) === WORLD ? board.area : covered).data;
  const series = useCalendar().data?.series;
  const monthCount = series?.find((item) => item.month === month)?.count;
  // the months of the board's period that have days to show: the arrows step through them
  const stops = (series ?? [])
    .filter((item) => item.kind !== 'forecast' && (item.count ?? 0) > 0)
    .map((item) => item.month);
  const at = month ? stops.indexOf(month) : -1;
  const before = at > 0 ? stops[at - 1] : undefined;
  const after = at >= 0 ? stops[at + 1] : undefined;
  // the day under the pointer or the keyboard, and where its card stands
  const [tip, setTip] = useState<{ date: string; left: number; box: number } | null>(null);
  // the bars are whole numbers that add up to the figure of the month
  const rows = wholeDays(days, monthCount);
  if (!month || !days || rows.size === 0) return null;
  const [year, mon] = month.split('-').map(Number);
  if (!year || !mon) return null;
  const length = new Date(Date.UTC(year, mon, 0)).getUTCDate();
  const max = Math.max(1, ...rows.values());
  const fireCounts = daysByDate(days);
  // a day as the card says it: the date in words, then the figures the bar is drawn from
  const lines = (date: string) => {
    const value = rows.get(date);
    return value === undefined
      ? []
      : [dateText(lang, date), ...dayFigures(t, lang, value, fireCounts.get(date)?.clusters)];
  };
  const tipped = tip ? lines(tip.date) : [];
  const picked = board.day ? lines(board.day) : [];
  return (
    <Card id="days" title={t('dash.s.days')} note={t('dash.note.days')}>
      <div className={styles.days} role="group" aria-label={t('dash.s.days')}>
        {Array.from({ length }, (_, index) => {
          const date = `${month}-${String(index + 1).padStart(2, '0')}`;
          const value = rows.get(date);
          const said = `${String(index + 1)} ${longMonth(lang, month)}: ${value === undefined ? '—' : formatCount(lang, value)}`;
          const show = (bar: HTMLElement) => {
            setTip({
              date,
              left: bar.offsetLeft + bar.offsetWidth / 2,
              box: bar.parentElement?.clientWidth ?? 0,
            });
          };
          const bound = pop.bind(
            value === undefined
              ? null
              : askers?.fact(
                  `${String(index + 1)} ${longMonth(lang, month)}`,
                  formatCount(lang, value),
                  date,
                ),
            {
              onPick: () => {
                // the pill of the press stands where the card was
                setTip(null);
                board.setDay(date);
                fires.setPlayer(true);
              },
            },
          );
          return (
            <button
              key={date}
              type="button"
              className={styles.day}
              style={
                {
                  '--h': `${String(Math.round(((value ?? 0) / max) * 100))}%`,
                } as CSSProperties
              }
              aria-pressed={board.day === date}
              disabled={value === undefined}
              aria-label={said}
              // a touch has no hover: its press picks the day, and the caption names it
              onPointerEnter={(event) => {
                if (event.pointerType !== 'touch' && value !== undefined) show(event.currentTarget);
              }}
              onPointerLeave={() => {
                setTip(null);
              }}
              onFocus={(event) => {
                if (event.currentTarget.matches(':focus-visible')) show(event.currentTarget);
              }}
              onBlur={() => {
                setTip(null);
              }}
              {...bound}
            >
              <i />
            </button>
          );
        })}
        {tip && tipped.length > 0 ? (
          <ChartTip left={tipLeft(tip.left, tip.box)} lines={tipped} />
        ) : null}
      </div>
      {pop.card}
      <div className={styles.axis}>
        <span>1</span>
        <span className={styles.dayNav}>
          <button
            type="button"
            className="icon-btn"
            aria-label={t('period.prev')}
            disabled={!before}
            onClick={() => {
              if (before) onPick(before);
            }}
          >
            <Ph name="caret-left" />
          </button>
          <span>{longMonthYear(lang, month)}</span>
          <button
            type="button"
            className="icon-btn"
            aria-label={t('period.next')}
            disabled={!after}
            onClick={() => {
              if (after) onPick(after);
            }}
          >
            <Ph name="caret-right" />
          </button>
        </span>
        <span>{length}</span>
      </div>
      {/* the picked day in words, for a touch and after a press, so the player is not the only place it is written;
          no day picked, no line: an empty one left a blank band under the axis */}
      {picked.length > 0 ? (
        <p className={styles.caption} aria-live="polite">
          {`${picked[0] ?? ''}: ${picked.slice(1).join(' · ')}`}
        </p>
      ) : null}
    </Card>
  );
}

const KNOWN = 4;

/** The seasons of fire the archive is checked against: four at first, all of them on a click; a click opens the place and the month. */
export function SeasonsCard() {
  const { t, lang } = useI18n();
  const board = useBoard();
  const [all, setAll] = useState(false);
  const pop = useAskPop();
  const askers = useAskers();
  const examples = (useMeta().data?.examples ?? []).filter((item) => item.found);
  if (examples.length === 0) return null;
  const shown = all ? examples : examples.slice(0, KNOWN);
  return (
    <Card id="known" title={t('dash.s.known')} note={t('dash.note.known')}>
      <ul className={styles.known}>
        {shown.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className={styles.knownOpen}
              {...pop.bind(
                askers?.fact(
                  `${localName(item.names, lang)}, ${longMonthYear(lang, item.month)}`,
                  formatCount(lang, item.count),
                  item.month,
                  {
                    area: '',
                    show: {
                      label: t('known.show'),
                      run: () => {
                        board.setArea(item.region_id);
                        board.setPick(item.month);
                      },
                    },
                  },
                ),
              )}
            >
              <span className={styles.knownName}>{localName(item.names, lang)}</span>
              <span className={styles.knownMonth}>{longMonthYear(lang, item.month)}</span>
              <span className={styles.knownCount}>{formatCount(lang, item.count)}</span>
            </button>
          </li>
        ))}
      </ul>
      {pop.card}
      {examples.length > KNOWN ? (
        <button
          type="button"
          className={styles.expand}
          aria-expanded={all}
          onClick={() => {
            setAll((now) => !now);
          }}
        >
          {all ? t('dash.fewer') : t('dash.all', { n: examples.length })}
        </button>
      ) : null}
    </Card>
  );
}

/** The cards that need the answer of the archive and those of the calendar's own routes, in the order of the bar. */
export function MoreCards({
  data,
  picked,
  onPick,
}: {
  data: Calendar;
  picked: string | null;
  onPick: (m: string) => void;
}) {
  const country = useCountryArea();
  return (
    <>
      {/* the days of the month follow the months and the years: with them they are the trend of the bar */}
      <section className={styles.block} data-section="days">
        <DaysCard onPick={onPick} />
      </section>
      {data.season ? (
        <section className={styles.block} data-section="season">
          <SeasonCard season={data.season} />
        </section>
      ) : null}
      <section className={styles.block} data-section="outlook">
        <OutlookCard data={data} picked={picked} onPick={onPick} />
      </section>
      {country !== null ? (
        <section className={styles.block} data-section="provinces">
          <Provinces />
        </section>
      ) : null}
      {/* how far to trust the figures: the check on the known seasons, then the error and the seam */}
      <section className={styles.block} data-section="accuracy">
        <SeasonsCard />
        <AccuracyCard data={data} />
      </section>
    </>
  );
}
