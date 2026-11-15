import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from 'react';
import { createPortal } from 'react-dom';
import { useI18n } from '../i18n/context';
import { Ph } from './Ph';
import styles from './AskPop.module.css';

/** What the pill takes to the chat, and how the figure is told to a screen reader. */
export interface AskInfo {
  /** Which figure: a month and its area, a row of a card. Not shown: it is seen where the press was. */
  title: string;
  /** The number, as it is written on the board. Not shown either. */
  value: string;
  /** What the figure is against: kept for the description of the pill. */
  note?: string;
  /** The pill: puts the figure in the question and opens the chat. */
  ask: () => void;
  /** A second segment of the pill: takes the board to the figure (an area, a month). */
  show?: { label: string; run: () => void };
}

type Origin = HTMLElement | SVGElement;

interface Shown {
  info: AskInfo;
  /** The place that was pressed. */
  rect: DOMRect;
  /** The element the pill was opened from: Escape gives the focus back to it, a press on it does not close the pill. */
  origin: Origin | null;
  /** Opened from the keyboard: the focus goes onto the pill. */
  focus: boolean;
}

interface BindOptions {
  /** What the element does by itself on a click (picks the month); the pill comes after it. */
  onPick?: () => void;
  /** The element does not turn Enter and Space into a click (an SVG group): the pill takes them. */
  keys?: boolean;
}

const OPENED = 'senda:ask-pop';
/** The pill goes by itself when the pointer is not on it. */
const LIFE_MS = 4000;
const GAP = 6;

const originOf = (element: Element): Origin | null =>
  element instanceof HTMLElement || element instanceof SVGElement ? element : null;

/**
 * «Спросить ИИ» over a pressed figure: a small pill, nothing on hover. A press on a number, a row, a bar, a point or a cell
 * shows it next to the figure, outside the data; a press elsewhere, Escape, a scroll or four quiet seconds take it away.
 * One hook serves any number of figures of a card: `bind` goes on each of them, `card` is set once.
 */
export function useAskPop() {
  const [shown, setShown] = useState<Shown | null>(null);
  const id = useId();

  const close = useCallback(() => {
    setShown(null);
  }, []);

  // one pill at a time on the page
  useEffect(() => {
    const other = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== id) close();
    };
    window.addEventListener(OPENED, other);
    return () => {
      window.removeEventListener(OPENED, other);
    };
  }, [id, close]);

  /** Shows the pill for a figure that has a place on the screen; a point of a chart gives the place by hand. */
  const open = (info: AskInfo, rect: DOMRect, origin: Origin | null, focus = false) => {
    window.dispatchEvent(new CustomEvent(OPENED, { detail: id }));
    setShown({ info, rect, origin, focus });
  };

  /** The props of a figure; without info the figure keeps only its own click. */
  const bind = (info: AskInfo | null | undefined, options: BindOptions = {}) => {
    if (!info) {
      return {
        onClick: options.onPick,
        ...(options.keys
          ? {
              onKeyDown: (event: KeyboardEvent) => {
                if (event.key !== 'Enter' && event.key !== ' ') return;
                event.preventDefault();
                options.onPick?.();
              },
            }
          : {}),
      };
    }
    return {
      'aria-haspopup': 'true' as const,
      onClick: (event: MouseEvent) => {
        // a hint inside the figure keeps its own click
        if (event.target instanceof Element && event.target.closest('[data-no-ask]')) return;
        options.onPick?.();
        // detail 0 is a click made by the keyboard
        open(
          info,
          event.currentTarget.getBoundingClientRect(),
          originOf(event.currentTarget),
          event.detail === 0,
        );
      },
      ...(options.keys
        ? {
            onKeyDown: (event: KeyboardEvent) => {
              if (event.key !== 'Enter' && event.key !== ' ') return;
              event.preventDefault();
              options.onPick?.();
              open(
                info,
                event.currentTarget.getBoundingClientRect(),
                originOf(event.currentTarget),
                true,
              );
            },
          }
        : {}),
    };
  };

  const card = shown
    ? createPortal(<AskPill shown={shown} onClose={close} />, document.body)
    : null;

  return { bind, open, close, card };
}

const overlap = (a: DOMRect, b: DOMRect) =>
  Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
  Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));

function AskPill({ shown, onClose }: { shown: Shown; onClose: () => void }) {
  const { t } = useI18n();
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const timer = useRef(0);
  const id = useId();
  const { info, origin, rect } = shown;

  /*
   * Next to the pressed figure, outside it: over it, else under it, else at its sides. Of the places that fit the window the one that
   * covers the least of the other buttons, switches and numbers wins; the pressed figure itself is never covered.
   */
  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    const w = element.offsetWidth;
    const h = element.offsetHeight;
    const centre = rect.left + rect.width / 2 - w / 2;
    const middle = rect.top + rect.height / 2 - h / 2;
    const places = [
      { left: centre, top: rect.top - GAP - h },
      { left: centre, top: rect.bottom + GAP },
      { left: rect.right + GAP, top: middle },
      { left: rect.left - GAP - w, top: middle },
    ].map((place) => ({
      left: Math.max(8, Math.min(innerWidth - w - 8, place.left)),
      top: place.top,
    }));
    const fits = places.filter((place) => place.top >= 8 && place.top + h <= innerHeight - 8);
    const others = [...document.querySelectorAll('button, [role="button"], [role="tab"], input')]
      .filter(
        (other) => !element.contains(other) && !origin?.contains(other) && !other.contains(origin),
      )
      .map((other) => other.getBoundingClientRect())
      .filter((r) => r.width > 0 && r.height > 0);
    const cost = (place: { left: number; top: number }) => {
      const mine = new DOMRect(place.left, place.top, w, h);
      return overlap(mine, rect) * 1000 + others.reduce((sum, r) => sum + overlap(mine, r), 0);
    };
    const best = (fits.length > 0 ? fits : places).reduce((a, b) => (cost(b) < cost(a) ? b : a));
    element.style.left = `${String(Math.round(best.left))}px`;
    element.style.top = `${String(Math.round(Math.max(8, best.top)))}px`;
  }, [rect, origin, info]);

  useEffect(() => {
    if (shown.focus) button.current?.focus();
  }, [shown.focus, info]);

  const rest = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(onClose, LIFE_MS);
  }, [onClose]);
  const keep = () => {
    window.clearTimeout(timer.current);
  };
  useEffect(() => {
    rest();
    return keep;
  }, [rest]);

  useEffect(() => {
    const away = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (box.current?.contains(target) || origin?.contains(target)) return;
      onClose();
    };
    const key = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      onClose();
      origin?.focus();
    };
    const scroll = (event: Event) => {
      if (!(event.target instanceof Node) || !box.current?.contains(event.target)) onClose();
    };
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', key);
    document.addEventListener('scroll', scroll, true);
    return () => {
      document.removeEventListener('pointerdown', away);
      document.removeEventListener('keydown', key);
      document.removeEventListener('scroll', scroll, true);
    };
  }, [origin, onClose]);

  return (
    <div
      ref={box}
      className={styles.pill}
      role="group"
      onPointerEnter={keep}
      onPointerLeave={rest}
      onFocus={keep}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) rest();
      }}
    >
      <button
        ref={button}
        type="button"
        className={styles.ask}
        aria-describedby={`${id}-d`}
        onClick={() => {
          onClose();
          info.ask();
        }}
      >
        <Ph name="sparkle" />
        <span>{t('chat.askAi')}</span>
      </button>
      {info.show ? (
        <button
          type="button"
          className={styles.show}
          onClick={() => {
            onClose();
            info.show?.run();
          }}
        >
          {info.show.label}
        </button>
      ) : null}
      <span className="visually-hidden" id={`${id}-d`}>
        {[info.title, info.value, info.note].filter(Boolean).join('. ')}
      </span>
    </div>
  );
}
