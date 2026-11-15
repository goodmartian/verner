import {
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';
import { Ph } from '../../ui/Ph';
import {
  fittingLabels,
  tagShift,
  tagWidth,
  nearestStep,
  neighbour,
  type Bar,
  type Label,
  type Step,
  type Tick,
} from './scale';

/** A small mark on the scale that stands for something to look at, with a few characters under it. */
export interface Mark {
  at: number;
  label: string;
}

interface TimelineProps<T> {
  id?: string;
  label: string;
  /** The moments the scale runs between. */
  from: number;
  to: number;
  bars: readonly Bar[];
  ticks?: readonly Tick[];
  /** From here on the scale is paler; with a label it is also a line of its own. */
  now?: { at: number; label?: string } | null;
  marks?: readonly Mark[];
  /** Where the handle can stand: a click, a drag or the arrow keys go to the nearest of them. */
  steps: readonly Step<T>[];
  /** Where the handle stands, null when nowhere. */
  value: number | null;
  /** The tag over the handle: the moment, and under it in smaller type what the map shows at it, when that says something. */
  valueLabel: string;
  valueNote?: string;
  /** False keeps the handle bare: the tag waits until the person works the scale (the screen reader still has the value). */
  tag?: boolean;
  /** The time zone, said once at the end of the scale; for scales of the hours of a day. */
  zone?: string;
  playing: boolean;
  playLabel: string;
  onPlay: () => void;
  onSeek: (value: T) => void;
  closeLabel: string;
  onClose: () => void;
  /** A way up or down a level, for the calendar; a plain button beside the cross. */
  level?: { label: string; onClick: () => void } | null;
}

/** How near the pointer has to be to a mark, px, for it to be named. */
const MARK_REACH = 9;
/** The room the tag has beyond each end of the rail: the margin of the rail in the stylesheet. */
const RAIL_MARGIN = 8;

const pct = (at: number, from: number, to: number) =>
  `${String(Math.min(100, Math.max(0, ((at - from) / (to - from)) * 100)))}%`;

/** The width of an element, kept up to date; 0 until it is measured. */
function useWidth(ref: { current: HTMLElement | null }): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const watch = new ResizeObserver(() => {
      setWidth(element.getBoundingClientRect().width);
    });
    watch.observe(element);
    return () => {
      watch.disconnect();
    };
  }, [ref]);
  return width;
}

/** One scale of time under a play button: bars where things happened, one handle to move over them. */
export function Timeline<T>({
  id,
  label,
  from,
  to,
  bars,
  ticks = [],
  now = null,
  marks = [],
  steps,
  value,
  valueLabel,
  valueNote,
  tag = true,
  zone,
  playing,
  playLabel,
  onPlay,
  onSeek,
  closeLabel,
  onClose,
  level = null,
}: TimelineProps<T>) {
  const rail = useRef<HTMLDivElement>(null);
  const width = useWidth(rail);
  const [dragging, setDragging] = useState(false);
  // the mark the pointer is on: of the marks only this one and the chosen one are named
  const [near, setNear] = useState<number | null>(null);

  const seek = (clientX: number) => {
    const box = rail.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    const share = Math.min(1, Math.max(0, (clientX - box.left) / box.width));
    const step = nearestStep(steps, from + share * (to - from));
    if (step && step.at !== value) onSeek(step.value);
  };

  const follow = useEffectEvent((event: globalThis.PointerEvent) => {
    seek(event.clientX);
  });
  useEffect(() => {
    if (!dragging) return;
    const stop = () => {
      setDragging(false);
    };
    window.addEventListener('pointermove', follow);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    return () => {
      window.removeEventListener('pointermove', follow);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
    };
  }, [dragging]);

  const press = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    seek(event.clientX);
    setDragging(true);
  };

  const hover = (clientX: number) => {
    const box = rail.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    const x = clientX - box.left;
    const found = marks.find(
      (mark) => Math.abs(((mark.at - from) / (to - from)) * box.width - x) <= MARK_REACH,
    );
    setNear(found?.at ?? null);
  };

  // the arrows go one step, Home and End to the first and the last; undefined is a key that is none of these
  const jump = (key: string): Step<T> | null | undefined => {
    switch (key) {
      case 'ArrowRight':
      case 'ArrowUp':
        return neighbour(steps, value, 1);
      case 'ArrowLeft':
      case 'ArrowDown':
        return neighbour(steps, value, -1);
      case 'Home':
        return neighbour(steps, null, 1);
      case 'End':
        return neighbour(steps, null, -1);
      default:
        return undefined;
    }
  };
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = jump(event.key);
    if (target === undefined) return;
    event.preventDefault();
    if (target) onSeek(target.value);
  };

  // above the rail the handle has its time, and "now" its word when the handle is not in the way; under it go the rest
  const high: Label[] = [
    ...(value === null || !tag
      ? []
      : [
          {
            key: 'value',
            at: value,
            text: valueLabel,
            side: 'middle' as const,
            rank: -1,
            width: tagWidth(valueLabel, valueNote),
          },
        ]),
    ...(now?.label
      ? [{ key: 'now', at: now.at, text: now.label, side: 'middle' as const, rank: 0 }]
      : []),
  ];
  const low: Label[] = [
    ...(zone ? [{ key: 'zone', at: to, text: zone, side: 'end' as const, rank: -1 }] : []),
    ...marks
      .filter((mark) => mark.at === value || mark.at === near)
      .map((mark) => ({
        key: `mark-${String(mark.at)}`,
        at: mark.at,
        text: mark.label,
        side: 'middle' as const,
        rank: 0,
      })),
    ...ticks.map((tick) => ({
      key: `tick-${String(tick.at)}`,
      at: tick.at,
      text: tick.label,
      side: 'start' as const,
      rank: 1,
    })),
    ...bars.flatMap((bar) =>
      bar.label
        ? [
            {
              key: `bar-${String(bar.at)}`,
              at: bar.at,
              text: bar.label,
              side: 'middle' as const,
              rank: 1,
            },
          ]
        : [],
    ),
  ];
  const shownHigh = fittingLabels(high, from, to, width);
  const shownLow = fittingLabels(low, from, to, width);
  const at = (moment: number) => ({ left: pct(moment, from, to) });

  return (
    <section
      className="timeline"
      id={id}
      aria-label={label}
      style={{ '--now': now ? pct(now.at, from, to) : '100%' } as CSSProperties}
    >
      <button type="button" className="play" aria-label={playLabel} onClick={onPlay}>
        <Ph name={playing ? 'pause' : 'play'} fill />
      </button>
      <div
        className="tl-scale"
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-valuemin={from}
        aria-valuemax={to}
        aria-valuenow={value ?? from}
        aria-valuetext={valueNote ? `${valueLabel}, ${valueNote}` : valueLabel}
        onPointerDown={press}
        onPointerMove={(event) => {
          hover(event.clientX);
        }}
        onPointerLeave={() => {
          setNear(null);
        }}
        onPointerUp={(event) => {
          // a finger leaves nothing under it: only a mouse keeps naming the mark it rests on
          if (event.pointerType !== 'mouse') setNear(null);
        }}
        onKeyDown={keys}
      >
        <div ref={rail} className="tl-rail">
          {ticks.map((tick) => (
            <span key={tick.at} className="tl-tick" style={at(tick.at)} />
          ))}
          {bars.map((bar) => {
            const style = {
              ...at(bar.at),
              '--h': bar.height.toFixed(3),
              ...(bar.color ? { '--c': bar.color } : {}),
              ...(bar.span ? { width: `calc(${pct(bar.span, 0, to - from)} - 1px)` } : {}),
            } as CSSProperties;
            const kind = bar.height > 0 ? 'tl-bar' : 'tl-dot';
            return (
              <span
                key={bar.at}
                className={`${kind}${bar.pale ? ' pale' : ''}${bar.ring ? ' ring' : ''}${bar.rain ? ' rain' : ''}${bar.at === value ? ' on' : ''}`}
                style={style}
              />
            );
          })}
          {now?.label ? <span className="tl-now" style={at(now.at)} /> : null}
          {now?.label && shownHigh.has('now') ? (
            <span className="tl-nowlabel" style={at(now.at)}>
              {now.label}
            </span>
          ) : null}
          {marks.map((mark) => (
            <span
              key={mark.at}
              className={`tl-mark${mark.at === value ? ' on' : ''}`}
              style={at(mark.at)}
            />
          ))}
          {value === null ? null : (
            <span className="tl-handle" style={at(value)}>
              {tag ? (
                <b
                  style={{
                    translate: `calc(-50% + ${String(tagShift(((value - from) / (to - from)) * width, tagWidth(valueLabel, valueNote), width, RAIL_MARGIN))}px) 0`,
                  }}
                >
                  {valueLabel}
                  {valueNote ? <small>{valueNote}</small> : null}
                </b>
              ) : null}
            </span>
          )}
        </div>
        <div className="tl-axis" aria-hidden="true">
          {low.map((word) =>
            shownLow.has(word.key) ? (
              <span key={word.key} className={`tl-w ${word.side}`} style={at(word.at)}>
                {word.text}
              </span>
            ) : null,
          )}
        </div>
      </div>
      <div className="tl-end">
        {level ? (
          <button type="button" className="btn btn-secondary tl-level" onClick={level.onClick}>
            {level.label}
          </button>
        ) : null}
        <button type="button" className="icon-btn" aria-label={closeLabel} onClick={onClose}>
          <Ph name="x" />
        </button>
      </div>
    </section>
  );
}
