import { usePlaceZone } from '../../config/usePlaceZone';
import { useQueryClient } from '@tanstack/react-query';
import { localName, LOCALES, type Lang } from '../../i18n/lang';
import { numberFormat } from '../../lib/numberFormat';
import { regionLabel } from '../../i18n/regionLabel';
import { useId, useState, type ReactNode } from 'react';
import { ApiError } from '../../api/client';
import type {
  AreaStats,
  Check,
  CountryAnswer,
  FireDetail,
  FireSummary,
  MonthDetail,
  FirePlan,
  ProvinceTable,
  Summary,
  Widget,
} from '../../api/types';
import { useConfig } from '../../config/context';
import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import { monthIndex } from '../calendar/months';
import {
  dateSpanText,
  dateText,
  detectionsWord,
  formatChange,
  formatCount,
  formatNice,
  longMonthYear,
  shortMonths,
} from '../calendar/text';
import { crewsText, planClock, routeLength } from '../fires/planText';
import { areaText, whereText } from '../fires/text';
import { useWidgetActions } from './actions';
import type { Calendar } from '../../api/calendar';
import type { AreaRef } from '../../config/types';
import { MonthsChart } from '../calendar/MonthsChart';
import { sameDates } from '../calendar/sameDates';

/** The cards of one answer come in one after another, this far apart. */
const STAGGER_MS = 120;

/** What the assistant drew in an answer: a small live view, told apart by `type`. `order` is its place among the cards of the answer. */
export function WidgetView({ widget, order = 0 }: { widget: Widget; order?: number }) {
  const body = content(widget);
  // a kind of widget this page does not know draws nothing
  return body ? (
    <div className="widget" style={{ animationDelay: `${String(order * STAGGER_MS)}ms` }}>
      {body}
    </div>
  ) : null;
}

function Head({ children }: { children: ReactNode }) {
  return <div className="w-head">{children}</div>;
}

function Stat({ big, sub }: { big: string; sub: string }) {
  return (
    <div className="w-stat">
      <b>{big}</b>
      <span>{sub}</span>
    </div>
  );
}

/** Bars, one for each value, the later ones paler. */
function Bars({ values, later = [] }: { values: readonly number[]; later?: readonly boolean[] }) {
  const tallest = Math.max(1, ...values);
  return (
    <div className="w-bars">
      {values.map((value, index) => (
        <i
          key={index}
          className={later[index] ? 'later' : undefined}
          style={{ '--h': (value / tallest).toFixed(3) } as React.CSSProperties}
        />
      ))}
    </div>
  );
}

function content(widget: Widget): ReactNode {
  switch (widget.type) {
    case 'area_calendar':
      return <AreaCalendarWidget data={widget.data} />;
    case 'region_list':
      return <RegionListWidget regions={widget.data.regions} types={widget.data.types} />;
    case 'period_summary':
      return <PeriodWidget summary={widget.data} />;
    case 'province_table':
      return <ProvincesWidget table={widget.data} />;
    case 'month_detail':
      return <MonthWidget detail={widget.data} />;
    case 'forecast_check':
      return <CheckWidget check={widget.data} />;
    case 'countries':
      return <CountriesWidget countries={widget.data.countries} />;
    case 'area_stats':
      return widget.data.summary ? (
        <PeriodWidget summary={widget.data.summary} />
      ) : widget.data.world ? (
        <WorldWidget world={widget.data.world} />
      ) : null;
    case 'fire_list':
      return <FiresWidget fires={widget.data.fires} />;
    case 'fire_detail':
      return <FireWidget detail={widget.data} />;
    case 'work_plan':
      return <PlanWidget plan={widget.data} />;
    case 'file':
      return <FileCard file={widget.data} />;
    case 'month_weather':
      return <MonthWeatherWidget weather={widget.data} />;
    case 'window_stats':
      return <WindowWidget stats={widget.data} />;
    default:
      return null;
  }
}

type FileData = Extract<Widget, { type: 'file' }>['data'];

/** What each kind of file is, in plain words; a kind this page does not know is told by the name of the file. */
const FILE_KINDS = {
  monthly: { title: 'file.kind.monthly', count: 'file.count.monthly' },
  days: { title: 'file.kind.days', count: 'file.count.days' },
  fires: { title: 'fires.title', count: 'fires.count' },
  report: { title: 'file.kind.report', count: null },
} as const;

/** A file the assistant prepared: one button, what the file is and how much is in it; a press saves it. A file that has gone is told so. */
function FileCard({ file }: { file: FileData }) {
  const { t, lang } = useI18n();
  const actions = useWidgetActions();
  const [state, setState] = useState<'idle' | 'busy' | 'gone' | 'failed'>('idle');
  const save = () => {
    if (!actions?.downloadFile) return;
    setState('busy');
    actions
      .downloadFile({ id: file.id, name: file.name })
      .then(() => {
        setState('idle');
      })
      .catch((error: unknown) => {
        setState(error instanceof ApiError && error.status === 404 ? 'gone' : 'failed');
      });
  };
  const known = (FILE_KINDS as Record<string, (typeof FILE_KINDS)[keyof typeof FILE_KINDS]>)[
    file.kind
  ];
  const title = known ? t(known.title) : file.name;
  // the format is the ending of the name
  const format =
    file.kind === 'report' ? 'Markdown' : (file.name.split('.').at(-1) ?? '').toUpperCase();
  const amount =
    known?.count && file.rows !== null ? t(known.count, { n: formatCount(lang, file.rows) }) : null;
  const gone = state === 'gone';
  const sub = gone
    ? t('file.gone')
    : state === 'failed'
      ? t('file.failed')
      : [format, amount].filter(Boolean).join(' · ');
  const body = (
    <>
      <Ph name={file.kind === 'report' ? 'file-text' : 'file-csv'} />
      <span className="w-file-text">
        <b>{title}</b>
        <span role={state === 'failed' ? 'alert' : undefined}>{sub}</span>
      </span>
    </>
  );
  // a file that has gone is no button: it only says so
  return gone ? (
    <div className="w-file" data-gone title={file.name}>
      {body}
    </div>
  ) : (
    <button
      type="button"
      className="w-file"
      title={file.name}
      aria-label={`${t('file.download')}: ${title}`}
      aria-busy={state === 'busy' || undefined}
      disabled={state === 'busy' || !actions?.downloadFile}
      onClick={save}
    >
      {body}
      <Ph
        name={state === 'busy' ? 'circle-notch' : 'download-simple'}
        className={state === 'busy' ? 'spin' : undefined}
      />
    </button>
  );
}

type Polygon = Extract<AreaRef, { polygon: unknown }>['polygon'];

/** A card of the chat is narrow: a record longer than this many months is drawn there as years, not as months. */
const WIDGET_MONTHS = 36;

function AreaCalendarWidget({ data: answer }: { data: Calendar }) {
  const data = sameDates(answer);
  const { t, lang } = useI18n();
  const config = useConfig();
  const actions = useWidgetActions();
  const [picked, setPicked] = useState<string | null>(null);
  const current = data.current_month;
  const count = (value: number | null) => (value === null ? '—' : formatCount(lang, value));
  const first = data.series[0]?.month ?? data.first_month;
  const last = data.series.at(-1)?.month ?? current.month;
  // the name of the place in the language of the page; an area with no id is one the person drew
  const known = [...(config?.countries ?? []), ...(config?.areas ?? [])].find(
    (item) => item.id === data.area.id,
  );
  const name = known
    ? localName(known.names, lang)
    : data.area.id
      ? data.area.name
      : t('map.drawn');
  const years = data.yearly;
  const long = data.series.length > WIDGET_MONTHS && years.length > 1;
  // The assistant asked for a period (a year, some months): the card is about that period, not about the month
  // that is running. Asked for nothing, it is the whole record, and the card says how the running month stands.
  const seen = data.series.filter((point) => point.count !== null);
  const asked = first > data.first_month || last < current.month;
  const running = seen.some((point) => point.month === current.month && current.partial);
  const lastDay = current.complete_through ?? current.to_date.through;
  const through =
    (asked ? running : current.partial) && lastDay
      ? t('dash.cal.through', { date: dateText(lang, lastDay) })
      : null;
  // the count of the period and the usual one of the same months: sums of what the service counted
  const total = seen.reduce((sum, point) => sum + (point.count ?? 0), 0);
  const usual = seen.every((point) => point.median !== null)
    ? seen.reduce((sum, point) => sum + (point.median ?? 0), 0)
    : null;
  // a whole calendar year that is over has its place among the other years
  const year = first.slice(0, 4);
  const wholeYear = first === `${year}-01` && last === `${year}-12`;
  const full = years.filter((item) => item.complete);
  const own = wholeYear ? full.find((item) => String(item.year) === year) : undefined;
  // the answer for a period may hold only the years of that period: a place among fewer than three years is none
  const place =
    own && full.length >= 3 ? full.filter((item) => item.count > own.count).length + 1 : null;
  // a whole year stands against the average year of the service, as the assistant says it in its words;
  // any other period against the usual counts of its own months
  const average = wholeYear && own ? (data.season?.average_year ?? null) : null;
  const periodCount = average === null ? total : (own?.count ?? total);
  const periodUsual = average ?? usual;
  const stats = asked
    ? {
        title: wholeYear
          ? year
          : first === last
            ? longMonthYear(lang, first)
            : `${longMonthYear(lang, first)} – ${longMonthYear(lang, last)}`,
        count: seen.length > 0 ? formatCount(lang, periodCount) : '—',
        usual: periodUsual === null || seen.length === 0 ? '—' : formatCount(lang, periodUsual),
        usualLabel:
          average !== null
            ? t('dash.note.season')
            : running
              ? t('dash.tile.usual')
              : t('dash.cal.usual'),
        against:
          periodUsual === null || periodUsual <= 0 || seen.length === 0
            ? '—'
            : formatChange(lang, periodCount / periodUsual),
        rank: place === null ? null : `#${String(place)}`,
      }
    : {
        title: longMonthYear(lang, current.month),
        count: count(current.count),
        usual: count(current.median),
        usualLabel: current.partial ? t('dash.tile.usual') : t('dash.cal.usual'),
        against: current.ratio === null ? '—' : formatChange(lang, current.ratio),
        rank: current.rank === null ? '—' : `#${String(current.rank)}`,
      };
  return (
    <>
      <Head>{name}</Head>
      {data.area.approximate ? <p className="note">{t('area.approximate')}</p> : null}
      {/* the figures first, in the words of the board: what they are about, the count, the usual one, how it stands */}
      <p className="w-title">
        {stats.title}
        {through ? <small>{through}</small> : null}
      </p>
      <div className="w-stats w-stats-2">
        <Stat big={stats.count} sub={t('regions.detections')} />
        <Stat big={stats.usual} sub={stats.usualLabel} />
        <Stat big={stats.against} sub={t('dash.tile.against')} />
        {stats.rank === null ? null : <Stat big={stats.rank} sub={t('kpi.rank')} />}
      </div>
      {long ? (
        <>
          <Head>{t('dash.s.years')}</Head>
          <Bars
            values={years.map((year) => year.count)}
            later={years.map((year) => !year.complete)}
          />
          <div className="w-legend w-ends">
            <span>{years[0]?.year}</span>
            <span>{years.at(-1)?.year}</span>
          </div>
        </>
      ) : (
        <>
          {/* the period is named over the figures when the card is about it; else it names the chart */}
          {asked ? null : (
            <Head>
              {longMonthYear(lang, first)} – {longMonthYear(lang, last)}
            </Head>
          )}
          {data.series.length > 1 ? (
            <MonthsChart months={data.series} picked={picked} onPick={setPicked} />
          ) : null}
        </>
      )}
      {actions ? (
        <ShowButton
          label={t('w.moreShow')}
          icon="calendar-blank"
          onClick={() => {
            actions.showPeriod({ polygon: data.area.geometry as Polygon }, first, last);
          }}
        />
      ) : null}
    </>
  );
}

function RegionListWidget({
  regions,
  types,
}: {
  regions: Extract<Widget, { type: 'region_list' }>['data']['regions'];
  types: Extract<Widget, { type: 'region_list' }>['data']['types'];
}) {
  const { t, lang } = useI18n();
  const actions = useWidgetActions();
  const client = useQueryClient();
  return (
    <>
      <Head>{t('w.wRegions')}</Head>
      <div className="w-rows">
        {regions.map((region) => (
          <button
            type="button"
            className="w-row"
            key={region.id}
            disabled={!actions}
            onClick={() => {
              client.setQueryData(['selected-region', region.id], region);
              actions?.showArea(region.id);
            }}
          >
            <span>{localName(region.names, lang)}</span>{' '}
            <small>{types[region.type ?? '']?.[lang]?.one ?? ''}</small>
          </button>
        ))}
      </div>
    </>
  );
}

function ShowButton({
  label,
  icon,
  onClick,
}: {
  label: string;
  icon: 'calendar-blank' | 'map-pin' | 'path' | 'play';
  onClick: () => void;
}) {
  return (
    <div className="w-actions">
      <button type="button" className="btn btn-secondary w-btn" onClick={onClick}>
        <Ph name={icon} />
        <span>{label}</span>
      </button>
    </div>
  );
}

function PeriodWidget({ summary }: { summary: Summary }) {
  const { t, lang } = useI18n();
  const actions = useWidgetActions();
  const { totals, verdict, rank } = summary;
  const first = summary.series[0]?.month;
  const last = summary.series.at(-1)?.month;
  const names = shortMonths(lang);
  const tallest = Math.max(1, ...summary.series.map((point) => point.value ?? 0));
  const peak = summary.peak?.month;
  return (
    <>
      <Head>
        {first && last
          ? `${longMonthYear(lang, first)} – ${longMonthYear(lang, last)}`
          : t('w.wPeriod')}
      </Head>
      <div className="w-stats">
        <Stat big={formatCount(lang, totals.total, totals.approximate)} sub={t('kpi.total')} />
        <Stat
          big={verdict.ratio === null ? '—' : formatChange(lang, verdict.ratio)}
          sub={t('kpi.normal', { n: formatNice(lang, totals.normal) })}
        />
        {rank ? (
          <Stat
            big={t('kpi.rankValue', { n: rank.place - 1, of: rank.of })}
            sub={t('kpi.rankSub')}
          />
        ) : null}
      </div>
      <div className="w-cols" style={{ '--n': summary.series.length } as React.CSSProperties}>
        {summary.series.map((point) => (
          <div
            key={point.month}
            className={`w-col${point.kind === 'forecast' ? ' fc' : ''}${point.month === peak ? ' top' : ''}`}
          >
            <i
              style={{ '--h': ((point.value ?? 0) / tallest).toFixed(3) } as React.CSSProperties}
            />
            <span>{names[monthIndex(point.month) % 12] ?? ''}</span>
          </div>
        ))}
      </div>
      {actions && first && last ? (
        <ShowButton
          label={t('w.moreShow')}
          icon="calendar-blank"
          onClick={() => {
            actions.showPeriod(summary.area.id, first, last);
          }}
        />
      ) : null}
    </>
  );
}

function ProvincesWidget({ table }: { table: ProvinceTable }) {
  const { t, lang } = useI18n();
  const largest = Math.max(1, ...table.rows.map((row) => row.total));
  return (
    <>
      <Head>{regionLabel(table, lang, 'other', t('regions.title'))}</Head>
      <div className="w-rows">
        {table.rows.slice(0, 6).map((row) => (
          <div key={row.id} className="w-row">
            <span>{localName(row.names, lang)}</span>
            <span className="w-bar">
              <i style={{ '--w': (row.total / largest).toFixed(3) } as React.CSSProperties} />
            </span>
            <b>{formatCount(lang, row.total, table.approximate)}</b>
          </div>
        ))}
      </div>
    </>
  );
}

function MonthWidget({ detail }: { detail: MonthDetail }) {
  const { t, lang } = useI18n();
  // the board shows a drawn area by its corners, which this card does not have: no way to the board from it
  const hands = useWidgetActions();
  const actions = detail.area.kind === 'drawn' ? null : hands;
  const years = detail.years.filter((year) => year.value !== null);
  const tallest = Math.max(
    1,
    detail.normal ?? 0,
    ...years.map((year) => year.high ?? year.value ?? 0),
  );
  const forecast = detail.kind === 'forecast';
  const first = years[0]?.year;
  const last = years.at(-1)?.year;
  return (
    <>
      <Head>{longMonthYear(lang, detail.month)}</Head>
      <div className="w-stats">
        <Stat
          big={detail.value === null ? '—' : formatCount(lang, detail.value, forecast)}
          sub={forecast ? t('grid.forecast') : detectionsWord(t, lang, detail.value ?? 0)}
        />
        {detail.ratio !== null && detail.normal !== null ? (
          <Stat
            big={formatChange(lang, detail.ratio)}
            sub={t('kpi.normal', { n: formatNice(lang, detail.normal) })}
          />
        ) : null}
        {detail.rank ? (
          <Stat
            big={t('kpi.rankValue', { n: detail.rank.place - 1, of: detail.rank.of })}
            sub={t('kpi.rankSub')}
          />
        ) : null}
      </div>
      <p className="w-head">{t('month.years')}</p>
      <div className="w-bars w-years">
        {years.map((year) => (
          <button
            key={year.year}
            type="button"
            className={`w-yr${year.month === detail.month ? ' sel' : ''}${year.kind === 'forecast' ? ' later' : ''}`}
            style={{ '--h': ((year.value ?? 0) / tallest).toFixed(3) } as React.CSSProperties}
            aria-label={String(year.year)}
            aria-pressed={year.month === detail.month}
            disabled={!actions}
            onClick={() => {
              actions?.showPeriod(detail.area.id, year.month, year.month);
            }}
          />
        ))}
        {detail.normal !== null ? (
          <span
            className="w-norm"
            style={{ '--n': (detail.normal / tallest).toFixed(3) } as React.CSSProperties}
          />
        ) : null}
      </div>
      <div className="w-legend w-ends">
        <span>{first}</span>
        <span>
          <i className="norm" />
          {t('legend.normal')}
        </span>
        <span>{last}</span>
      </div>
      {actions ? (
        <ShowButton
          label={t('w.moreShow')}
          icon="calendar-blank"
          onClick={() => {
            actions.showPeriod(detail.area.id, detail.month, detail.month);
          }}
        />
      ) : null}
    </>
  );
}

function CheckWidget({ check }: { check: Check }) {
  const { t } = useI18n();
  const percent = (share: number) => `${String(Math.round(share * 100))} %`;
  return (
    <>
      <Head>{t('check.title', { a: check.blind_years.first, b: check.blind_years.last })}</Head>
      <div className="w-stats">
        <Stat big={percent(check.poisson.year_error)} sub={t('check.errYear')} />
        <Stat
          big={percent(check.climatology.year_error)}
          sub={t('check.errNormal', { n: Math.round(check.climatology.year_error * 100) })}
        />
        <Stat
          big={percent(1 - check.poisson.month_log_error / check.climatology.month_log_error)}
          sub={t('check.better')}
        />
      </div>
    </>
  );
}

function CountriesWidget({
  countries,
}: {
  countries: readonly Pick<CountryAnswer, 'id' | 'names' | 'average_per_year'>[];
}) {
  const { t, lang } = useI18n();
  const largest = Math.max(1, ...countries.map((country) => country.average_per_year));
  return (
    <>
      <Head>{t('countries.title')}</Head>
      <div className="w-rows">
        {countries.map((country) => (
          <div key={country.id} className="w-row">
            <span>{localName(country.names, lang)}</span>
            <span className="w-bar">
              <i
                style={
                  { '--w': (country.average_per_year / largest).toFixed(3) } as React.CSSProperties
                }
              />
            </span>
            <b>{formatCount(lang, country.average_per_year)}</b>
          </div>
        ))}
      </div>
    </>
  );
}

function WorldWidget({ world }: { world: NonNullable<AreaStats['world']> }) {
  const { t, lang } = useI18n();
  const peak = new Intl.DateTimeFormat(lang, { month: 'long', timeZone: 'UTC' }).format(
    new Date(Date.UTC(2000, world.peak_month - 1, 1)),
  );
  return (
    <>
      <Head>{t('w.wArea')}</Head>
      <div className="w-stats">
        <Stat big={formatCount(lang, world.average_per_year, true)} sub={t('world.average')} />
        <Stat big={peak} sub={t('world.peak')} />
        <Stat big={formatCount(lang, world.last_year_total, true)} sub={t('world.last')} />
      </div>
    </>
  );
}

function FiresWidget({ fires }: { fires: readonly FireSummary[] }) {
  const { t, lang } = useI18n();
  const actions = useWidgetActions();
  const largest = Math.max(1, ...fires.map((fire) => fire.area_ha));
  return (
    <>
      <Head>{t('fires.title')}</Head>
      <div className="w-rows">
        {fires.map((fire) => (
          <button
            key={fire.id}
            type="button"
            className="w-row"
            disabled={!actions}
            onClick={() => {
              actions?.openFire(fire.id);
            }}
          >
            <span>{fire.nearest_place.name}</span>
            <span className="w-bar">
              <i style={{ '--w': (fire.area_ha / largest).toFixed(3) } as React.CSSProperties} />
            </span>
            <b>{areaText(t, lang, fire.area_ha)}</b>
          </button>
        ))}
      </div>
    </>
  );
}

function FireWidget({ detail }: { detail: FireDetail }) {
  const { t, lang } = useI18n();
  const actions = useWidgetActions();
  const { summary } = detail;
  return (
    <>
      <Head>
        {summary.nearest_place.name}, {whereText(t, lang, summary.nearest_place)}
      </Head>
      <div className="w-stats">
        <Stat big={areaText(t, lang, summary.area_ha)} sub={t('fire.area')} />
        <Stat big={formatCount(lang, summary.detection_count)} sub={t('fire.detections')} />
        <Stat
          big={t('fire.mw', { n: formatCount(lang, summary.growth.at(-1)?.frp_mw ?? 0) })}
          sub={t('fire.strip.power')}
        />
      </div>
      <Bars values={summary.growth.map((point) => point.pass_detections)} />
      {actions ? (
        <ShowButton
          label={t('w.openFire')}
          icon="map-pin"
          onClick={() => {
            actions.openFire(summary.id);
          }}
        />
      ) : null}
    </>
  );
}

/** The name of a place of the catalog in the language of the page; an area with no id is one the person drew. */
function usePlaceName(id: string | null, fallback: string): string {
  const { t, lang } = useI18n();
  const config = useConfig();
  if (id === null || id === 'drawn') return t('map.drawn');
  const known = [...(config?.countries ?? []), ...(config?.areas ?? [])].find(
    (item) => item.id === id,
  );
  return known ? localName(known.names, lang) : fallback;
}

/** A figure as the service gave it, at most two decimals: the same figure the assistant reads. */
const exact = (lang: Lang, n: number, signed = false) =>
  numberFormat(LOCALES[lang], {
    maximumFractionDigits: 2,
    signDisplay: signed ? 'exceptZero' : 'auto',
  })
    .format(n)
    .replace('-', '−');

type MonthWeather = Extract<Widget, { type: 'month_weather' }>['data'];

/** The rain and the temperature of a month over an area, each against its normal, as the assistant was given them. */
function MonthWeatherWidget({ weather }: { weather: MonthWeather }) {
  const { t, lang } = useI18n();
  const name = usePlaceName(weather.area, weather.area);
  const by = new Map((weather.observed?.quantities ?? []).map((item) => [item.key, item]));
  const rain = by.get('rain_mm');
  const temperature = by.get('temperature_c');
  const mm = (n: number) => t('w.mm', { n: exact(lang, n) });
  const degrees = (n: number, signed = false) => `${exact(lang, n, signed)} °C`;
  return (
    <>
      <Head>{name}</Head>
      <p className="w-title">{longMonthYear(lang, weather.month)}</p>
      <div className="w-stats w-stats-2">
        {rain ? (
          <>
            <Stat big={mm(rain.value)} sub={t('wx.layer.rain')} />
            <Stat
              big={rain.change_pct === null ? '—' : formatChange(lang, 1 + rain.change_pct / 100)}
              sub={t('kpi.normal', { n: mm(rain.normal) })}
            />
          </>
        ) : null}
        {temperature ? (
          <>
            <Stat big={degrees(temperature.value)} sub={t('w.temperature')} />
            <Stat
              big={temperature.anomaly === null ? '—' : degrees(temperature.anomaly, true)}
              sub={t('kpi.normal', { n: degrees(temperature.normal) })}
            />
          </>
        ) : null}
      </div>
      {weather.attribution ? <p className="note">{weather.attribution}</p> : null}
    </>
  );
}

type WindowStats = Extract<Widget, { type: 'window_stats' }>['data'];

/** The last day of the month of a date `YYYY-MM-DD`. */
const monthEnd = (iso: string) => {
  const day = new Date(`${iso.slice(0, 7)}-01T12:00:00Z`);
  day.setUTCMonth(day.getUTCMonth() + 1, 0);
  return day.toISOString().slice(0, 10);
};

/** Detections of a date window against the same dates of the other years, in the words of the board. */
function WindowWidget({ stats }: { stats: WindowStats }) {
  const { t, lang } = useI18n();
  const actions = useWidgetActions();
  const name = usePlaceName(stats.area.id, stats.area.name);
  const { start, end } = stats.window;
  const count = (value: number | null) => (value === null ? '—' : formatCount(lang, value));
  // the board shows whole months: a window of days inside a month has no place there
  const months =
    start.endsWith('-01') && end === monthEnd(end)
      ? { from: start.slice(0, 7), to: end.slice(0, 7) }
      : null;
  const area = stats.area.id;
  return (
    <>
      <Head>{name}</Head>
      <p className="w-title">
        {dateSpanText(lang, start, end)}
        {stats.partial && stats.complete_through ? (
          <small>{t('dash.cal.through', { date: dateText(lang, stats.complete_through) })}</small>
        ) : null}
      </p>
      <div className="w-stats w-stats-2">
        <Stat big={count(stats.count)} sub={t('regions.detections')} />
        <Stat big={count(stats.median)} sub={t('dash.tile.usual')} />
        <Stat
          big={stats.ratio === null ? '—' : formatChange(lang, stats.ratio)}
          sub={t('dash.tile.against')}
        />
        <Stat
          big={
            stats.rank === null
              ? '—'
              : t('kpi.rankValue', { n: `#${String(stats.rank)}`, of: stats.of ?? '—' })
          }
          sub={t('kpi.rank')}
        />
      </div>
      {actions && months && area ? (
        <ShowButton
          label={t('w.moreShow')}
          icon="calendar-blank"
          onClick={() => {
            actions.showPeriod(area, months.from, months.to);
          }}
        />
      ) : null}
    </>
  );
}

type Point = readonly number[];

/** A small map of the plan: the front, the safety zones, the ways and the places, drawn from the same numbers as the map. */
function PlanMap({ plan, label }: { plan: FirePlan; label: string }) {
  // one hatch per map: two cards on a page must not share an id
  const hatch = `hatch${useId().replaceAll(':', '')}`;
  const W = 320;
  const H = 180;
  const PAD = 14;
  const BOTTOM = 18;
  // the front is parts, each with its outer ring first and then its holes
  const front = plan.contours.find((item) => item.hours === plan.hours)?.polygons ?? [];
  const ways = plan.crews.filter((crew) => crew.status !== 'block');
  const zones = plan.safe_zones.filter((ring) => ring.length >= 3);
  const all: Point[] = [
    ...front.flat(2),
    ...zones.flat(),
    ...ways.flatMap((crew) => [...crew.route, ...crew.escape]),
  ];
  const lats = all.map((p) => p[1] ?? 0);
  const k = Math.cos(((Math.min(...lats) + Math.max(...lats)) / 2) * (Math.PI / 180));
  const xs = all.map((p) => (p[0] ?? 0) * k);
  const ys = all.map((p) => p[1] ?? 0);
  const x0 = Math.min(...xs);
  const y0 = Math.min(...ys);
  const span = (a: number[], low: number) => Math.max(...a) - low || 1;
  const scale = Math.min((W - 2 * PAD) / span(xs, x0), (H - 2 * PAD - BOTTOM) / span(ys, y0));
  const ox = (W - span(xs, x0) * scale) / 2;
  const oy = (H - BOTTOM - span(ys, y0) * scale) / 2;
  const at = (p: Point): [number, number] => [
    ox + ((p[0] ?? 0) * k - x0) * scale,
    H - BOTTOM - oy - ((p[1] ?? 0) - y0) * scale,
  ];
  const list = (points: readonly Point[]) =>
    points
      .map((p) =>
        at(p)
          .map((v) => v.toFixed(1))
          .join(','),
      )
      .join(' ');
  return (
    <svg className="mm" viewBox={`0 0 ${String(W)} ${String(H)}`} role="img" aria-label={label}>
      <defs>
        <pattern id={hatch} width={6} height={6} patternUnits="userSpaceOnUse">
          <path className="mm-hatch" d="M-1,7L7,-1" />
        </pattern>
      </defs>
      <rect className="mm-bg" width={W} height={H} rx={8} />
      {front.map((part) => (
        <path
          // a part is known by where its outer ring begins
          key={String(part[0]?.[0])}
          className="mm-f3"
          fillRule="evenodd"
          d={part.map((ring) => `M${list(ring).replaceAll(' ', 'L')}Z`).join('')}
        />
      ))}
      {zones.map((ring) => (
        <polygon
          key={String(ring[0])}
          className="mm-safe"
          style={{ fill: `url(#${hatch})` }}
          points={list(ring)}
        />
      ))}
      {ways.map((crew) => (
        <g key={crew.number}>
          <polyline className="mm-attack" points={list(crew.route)} />
          <polyline className="mm-escape" points={list(crew.escape)} />
          <circle className="mm-entry" cx={at(crew.entry)[0]} cy={at(crew.entry)[1]} r={5} />
        </g>
      ))}
    </svg>
  );
}

function PlanWidget({ plan }: { plan: FirePlan }) {
  const { t, lang } = useI18n();
  const actions = useWidgetActions();
  const zone = usePlaceZone(plan);
  const leave = plan.report.leave_in_h;
  const km =
    plan.crews
      .filter((crew) => crew.status !== 'block')
      .reduce((sum, crew) => sum + routeLength(crew.route), 0) / 1000;
  return (
    <>
      <Head>{t('w.wPlan')}</Head>
      <PlanMap plan={plan} label={t('w.wPlan')} />
      <div className="w-stats">
        <Stat big={crewsText(t, lang, plan.crews.length)} sub={t('w.inPlan')} />
        <Stat
          big={leave === null ? `8+ ${t('pl.h')}` : planClock(lang, plan, leave, zone)}
          sub={t('w.workLabel')}
        />
        <Stat
          big={`${new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(km)} ${t('pl.km')}`}
          sub={t('w.routes')}
        />
      </div>
      {actions ? (
        <ShowButton
          label={t('w.showPlan')}
          icon="path"
          onClick={() => {
            actions.showPlan(plan);
          }}
        />
      ) : null}
    </>
  );
}
