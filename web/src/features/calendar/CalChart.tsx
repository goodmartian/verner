import { memo } from 'react';
import type { Calendar } from '../../api/calendar';
import { useI18n } from '../../i18n/context';
import { useWidth } from '../../lib/useWidth';
import { useAskPop } from '../../ui/AskPop';
import { useAskers } from './askInfo';
import { monthIndex, type Month } from './months';
import { formatCount, longMonthYear, shortMonth } from './text';

interface Geometry {
  width: number;
  height: number;
}

/** The size the drawing is made at: as wide as its box, at least 300. */
function useGeometry() {
  const { ref, width } = useWidth();
  const w = Math.max(300, Math.round(width || 600));
  return { ref, size: { width: w, height: w > 520 ? 220 : 190 } satisfies Geometry };
}

const TOP = 22;
const BOTTOM = 22;
/** Room for the numbers of the right axis. */

interface RangeChartProps {
  /** The months ahead, each with the forecast of the model. */
  months: readonly Calendar['series'][number][];
  picked: Month | null;
  onPick: (month: Month) => void;
  /** Names the chart for screen readers. */
  title: string;
}

/** The months ahead: the blue line for the model, dashed for the usual, a pale band for the range they are likely in. */
export const RangeChart = memo(function RangeChart({
  months: series,
  picked,
  onPick,
  title,
}: RangeChartProps) {
  const { lang } = useI18n();
  const pop = useAskPop();
  const askers = useAskers();
  const { ref, size } = useGeometry();
  const { width: Wd, height: H } = size;
  const n = series.length;
  const gw = Wd / Math.max(n, 1);
  const max =
    Math.max(1, ...series.map((m) => Math.max(m.median ?? 0, m.forecast?.high ?? 0))) * 1.06;
  const Y = (x: number) => TOP + (H - TOP - BOTTOM) * (1 - x / max);
  const X = (j: number) => gw * j + gw / 2;
  const values = gw >= 46;
  const year = (m: Month) => Math.floor(monthIndex(m) / 12);
  const label = (m: Month, j: number) => {
    const january = monthIndex(m) % 12 === 0;
    // a new year is told by the whole year after the month: "Янв 27" reads as the 27th of January
    if (january && j > 0) return `${shortMonth(lang, m)} ${String(year(m))}`;
    return n <= 12 || j === 0 ? shortMonth(lang, m) : '';
  };
  const line = (get: (m: (typeof series)[number]) => number | null | undefined) =>
    series.flatMap((m, j) => {
      const v = get(m);
      return v == null ? [] : [`${X(j).toFixed(1)},${Y(v).toFixed(1)}`];
    });
  const normal = line((m) => m.median);
  const model = line((m) => m.forecast?.median);
  const up = series.map((m, j) => `${X(j).toFixed(1)},${Y(m.forecast?.high ?? 0).toFixed(1)}`);
  const down = series
    .map((m, j) => `${X(j).toFixed(1)},${Y(m.forecast?.low ?? 0).toFixed(1)}`)
    .reverse();

  return (
    <div className="fc-chart" id="fc-chart" ref={ref}>
      <svg viewBox={`0 0 ${String(Wd)} ${String(H)}`} role="group" aria-label={title}>
        <line className="ax" x1={0} x2={Wd} y1={H - BOTTOM} y2={H - BOTTOM} />
        {n > 1 ? <polygon className="band" points={[...up, ...down].join(' ')} /> : null}
        {series.map((m, j) => {
          const cx = X(j);
          const text = label(m.month, j);
          const value = m.forecast?.median ?? 0;
          return (
            <g key={m.month}>
              <g
                className={`g${m.month === picked ? ' on' : ''}`}
                data-month={m.month}
                role="button"
                tabIndex={0}
                aria-label={`${longMonthYear(lang, m.month)}: ${formatCount(lang, value, true)}`}
                {...pop.bind(askers?.month(m), {
                  keys: true,
                  onPick: () => {
                    onPick(m.month);
                  },
                })}
              >
                <rect
                  className="g-hit"
                  x={gw * j + 1}
                  y={0}
                  width={Math.max(1, gw - 2)}
                  height={H - BOTTOM}
                  rx={4}
                />
                {values ? (
                  <text className="v" x={cx} y={Y(value) - 6} textAnchor="middle">
                    {formatCount(lang, value, true).replace('≈ ', '≈')}
                  </text>
                ) : null}
              </g>
              {text ? (
                <text x={cx} y={H - 6} textAnchor="middle">
                  {text}
                </text>
              ) : null}
            </g>
          );
        })}
        {normal.length > 1 ? <polyline className="nl" points={normal.join(' ')} /> : null}
        {model.length > 1 ? <polyline className="ml" points={model.join(' ')} /> : null}
        {model.length === 1 ? (
          <circle className="md" cx={X(0)} cy={Y(series[0]?.forecast?.median ?? 0)} r={4} />
        ) : null}
      </svg>
      {pop.card}
    </div>
  );
});
