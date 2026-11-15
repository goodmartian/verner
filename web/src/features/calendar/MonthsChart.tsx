import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { useI18n } from '../../i18n/context';
import { useAskPop, type AskInfo } from '../../ui/AskPop';
import { ChartTip, tipLeft } from '../../ui/ChartTip';
import { formatChange, formatCount, longMonthYear, shortMonths } from './text';
import styles from './MonthsChart.module.css';

export interface ChartMonth {
  month: string;
  count: number | null;
  median: number | null;
  /** Counted from MODIS and brought to the scale of VIIRS. */
  converted?: boolean;
}

/** One satellite of the series, drawn in place of the harmonized series. */
export interface ChartSatellite {
  id: string;
  name: string;
  values: readonly (number | null)[];
}

interface MonthsChartProps {
  months: readonly ChartMonth[];
  picked: string | null;
  onPick: (month: string) => void;
  satellites?: readonly ChartSatellite[];
  /** The card of a month on hover or press: its figure and the question for the chat. */
  ask?: (month: string) => AskInfo | null | undefined;
}

const HEIGHT = 168;
// half of the widest axis label: a label closer to an edge than this is anchored to that edge
const EDGE = 32;
// room under the line for the labels of the axis, and above for the dot of the highest month
const FOOT = 24;
const TOP = 8;
const TONES = ['ink', 'route', 'muted'] as const;

/** Where the line goes: a run of points, broken where a month has no count. */
function path(points: readonly (readonly [number, number] | null)[]): string {
  let out = '';
  let open = false;
  for (const point of points) {
    if (!point) {
      open = false;
      continue;
    }
    out += `${open ? 'L' : 'M'}${point[0].toFixed(1)} ${point[1].toFixed(1)}`;
    open = true;
  }
  return out;
}

/** The labels under the line: years when the window is long, months when it is short; few enough to read. */
function ticks(months: readonly ChartMonth[], width: number): number[] {
  const every = months.length > 30 ? 12 : 3;
  // a label of a month is longer than a year
  const room = Math.max(1, Math.floor(width / (months.length > 30 ? 64 : 84)));
  const all = months
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => (Number(item.month.slice(5)) - 1) % every === 0)
    .map(({ index }) => index);
  const step = Math.ceil(all.length / room);
  return all.filter((_, at) => at % step === 0);
}

/** The months as a line with a soft fill under it and the usual month as a quiet dashed line; a crosshair names the month under the pointer. */
export function MonthsChart({ months, picked, onPick, satellites, ask }: MonthsChartProps) {
  const { t, lang } = useI18n();
  const pop = useAskPop();
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const measure = () => {
      setWidth(Math.round(element.getBoundingClientRect().width));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  const n = months.length;
  const lines = satellites ?? [];
  const top = Math.max(
    1,
    ...(satellites
      ? satellites.flatMap((line) => line.values.map((value) => value ?? 0))
      : months.flatMap((item) => [item.count ?? 0, item.median ?? 0])),
  );
  const x = (index: number) => (n > 1 ? (index / (n - 1)) * width : width / 2);
  const y = (value: number) => TOP + (1 - value / top) * (HEIGHT - FOOT - TOP);
  const base = HEIGHT - FOOT;
  const point = (value: number | null, index: number) =>
    value === null ? null : ([x(index), y(value)] as const);
  const count = months.map((item, index) => point(item.count, index));
  const line = path(count);
  // the fill closes each run of the line on the floor of the chart
  const runs = count.reduce<(readonly [number, number])[][]>((all, current) => {
    if (!current) all.push([]);
    else (all.at(-1) ?? all[all.push([]) - 1])?.push(current);
    return all;
  }, []);
  const fill = runs
    .filter((run) => run.length > 1)
    .map((run) => {
      const first = run[0];
      const last = run[run.length - 1];
      return first && last
        ? `${path(run)}L${last[0].toFixed(1)} ${String(base)}L${first[0].toFixed(1)} ${String(base)}Z`
        : '';
    })
    .join('');
  const median = path(months.map((item, index) => point(item.median, index)));
  const at = picked ? months.findIndex((item) => item.month === picked) : -1;
  const shown = hover ?? (at >= 0 ? at : null);
  // the months brought from MODIS are drawn in their own colour; the satellites are drawn as they were counted, so none
  const firstConverted = satellites ? -1 : months.findIndex((item) => item.converted === true);
  const lastConverted = months.findLastIndex((item) => item.converted === true);

  const indexAt = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const share = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0;
    return Math.max(0, Math.min(n - 1, Math.round(share * (n - 1))));
  };
  // the pill stands by the point of the month: a small place at the dot
  const anchorAt = (svg: Element, index: number) => {
    const rect = svg.getBoundingClientRect();
    return new DOMRect(rect.left + x(index) - 4, rect.top + y(months[index]?.count ?? 0) - 4, 8, 8);
  };
  const infoAt = (index: number) => {
    const month = months[index]?.month;
    return month ? ask?.(month) : null;
  };
  const key = (event: KeyboardEvent<SVGSVGElement>) => {
    if ((event.key === 'Enter' || event.key === ' ') && at >= 0) {
      const info = infoAt(at);
      if (info) {
        event.preventDefault();
        pop.open(info, anchorAt(event.currentTarget, at), event.currentTarget, true);
      }
      return;
    }
    const step = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0;
    if (!step || n === 0) return;
    event.preventDefault();
    const next = Math.max(0, Math.min(n - 1, (at >= 0 ? at : n - 1) + step));
    const month = months[next]?.month;
    if (month) onPick(month);
  };

  const current = shown === null ? undefined : months[shown];
  const tip = current
    ? [
        longMonthYear(lang, current.month),
        current.count === null ? '—' : formatCount(lang, current.count),
        current.median === null
          ? ''
          : t('dash.tip.usual', { n: formatCount(lang, current.median) }),
        current.count !== null && current.median
          ? `${t('dash.tile.against')} ${formatChange(lang, current.count / current.median)}`
          : '',
      ].filter(Boolean)
    : [];
  const shownX = shown === null ? 0 : x(shown);

  return (
    <div className={styles.chart} ref={box}>
      {width > 0 ? (
        <svg
          className={styles.svg}
          width={width}
          height={HEIGHT}
          viewBox={`0 0 ${String(width)} ${String(HEIGHT)}`}
          role="img"
          aria-label={t('calendar.chart')}
          tabIndex={0}
          onKeyDown={key}
          onPointerMove={(event) => {
            const index = indexAt(event);
            setHover(index);
          }}
          onPointerDown={(event) => {
            setHover(indexAt(event));
          }}
          onPointerLeave={() => {
            setHover(null);
          }}
          onClick={(event) => {
            const index = indexAt(event as unknown as PointerEvent<SVGSVGElement>);
            const month = months[index]?.month;
            if (month) onPick(month);
            const info = infoAt(index);
            if (info) {
              pop.open(
                info,
                anchorAt(event.currentTarget, index),
                event.currentTarget,
                event.detail === 0,
              );
            }
          }}
        >
          <line className={styles.floor} x1={0} x2={width} y1={base} y2={base} />
          {satellites ? (
            lines.map((item, index) => (
              <path
                key={item.id}
                className={styles.sat}
                data-tone={TONES[index % TONES.length]}
                d={path(item.values.map((value, at2) => point(value, at2)))}
              />
            ))
          ) : (
            <>
              <path className={styles.fill} d={fill} />
              <path className={styles.median} d={median} />
              <path className={styles.line} d={line} />
              {firstConverted >= 0 ? (
                <path
                  className={styles.convertedLine}
                  d={path(count.slice(firstConverted, lastConverted + 2))}
                />
              ) : null}
            </>
          )}
          {ticks(months, width).map((index) => {
            const item = months[index];
            // a label stays at its own month; near an edge it is anchored to that side, so it is not cut off
            const at = x(index);
            const side = at < EDGE ? 'start' : at > width - EDGE ? 'end' : 'middle';
            return item ? (
              <text
                key={item.month}
                className={styles.tick}
                x={at}
                y={HEIGHT - 6}
                textAnchor={side}
              >
                {months.length > 30
                  ? item.month.slice(0, 4)
                  : `${shortMonths(lang)[Number(item.month.slice(5)) - 1] ?? ''} ${item.month.slice(0, 4)}`}
              </text>
            ) : null;
          })}
          {shown !== null ? (
            <>
              <line className={styles.cross} x1={x(shown)} x2={x(shown)} y1={TOP} y2={base} />
              {(satellites ? [] : [months[shown]?.count ?? null]).map((value) =>
                value === null ? null : (
                  <circle
                    key="dot"
                    className={styles.dot}
                    data-picked={shown === at ? 'on' : undefined}
                    cx={x(shown)}
                    cy={y(value)}
                    r={4}
                  />
                ),
              )}
            </>
          ) : null}
          {at >= 0 && at !== shown && !satellites && months[at]?.count != null ? (
            <circle
              className={styles.dot}
              data-picked="on"
              cx={x(at)}
              cy={y(months[at].count)}
              r={4}
            />
          ) : null}
        </svg>
      ) : null}
      {tip.length > 0 && hover !== null ? (
        <ChartTip left={tipLeft(shownX, width)} lines={tip} />
      ) : null}
      {pop.card}
      {satellites ? (
        <ul className={styles.legend}>
          {satellites.map((item, index) => (
            <li key={item.id} data-tone={TONES[index % TONES.length]}>
              {item.name}
            </li>
          ))}
        </ul>
      ) : (
        <ul className={styles.legend}>
          <li>{t('dash.legend.count')}</li>
          <li data-tone="route" data-dash="on">
            {t('dash.legend.usual')}
          </li>
          {firstConverted >= 0 ? <li data-tone="converted">{t('dash.legend.converted')}</li> : null}
        </ul>
      )}
    </div>
  );
}
