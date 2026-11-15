import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';

interface SegmentsProps<T extends string | number | boolean> {
  label: string;
  /** Value, text, and optionally the id of the button. */
  items: readonly (readonly [T, string] | readonly [T, string, string])[];
  /** The group itself: its id, a class for its place on the page, a tip. */
  id?: string;
  className?: string;
  tip?: string;
  value: T;
  onChange: (value: T) => void;
}

/**
 * The switch of the owner (`.seg`) with a thumb under the chosen segment. The thumb moves by transform only: its width
 * and place are measured once per change and given as a scale and a shift, so nothing animates `width` or `left`.
 */
export function Segments<T extends string | number | boolean>({
  label,
  items,
  id,
  className,
  tip,
  value,
  onChange,
}: SegmentsProps<T>) {
  const box = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState<{ x: number; w: number } | null>(null);
  const [ready, setReady] = useState(false);
  const key = items.map(([item]) => String(item)).join();

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    const measure = () => {
      const active = element.querySelector<HTMLElement>('[aria-pressed="true"]');
      setThumb(active ? { x: active.offsetLeft, w: active.offsetWidth } : null);
    };
    measure();
    // the first place is taken without a move
    const frame = requestAnimationFrame(() => {
      setReady(true);
    });
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [value, key]);

  return (
    <div
      id={id}
      className={className ? `seg seg-thumbed ${className}` : 'seg seg-thumbed'}
      data-tip={tip}
      role="group"
      aria-label={label}
      ref={box}
      data-ready={ready ? 'on' : undefined}
    >
      {thumb ? (
        <span
          className="seg-thumb"
          aria-hidden="true"
          style={{ '--x': `${String(thumb.x)}px`, '--w': String(thumb.w) } as CSSProperties}
        />
      ) : null}
      {items.map(([item, text, buttonId]) => (
        <button
          key={String(item)}
          id={buttonId}
          type="button"
          aria-pressed={value === item}
          onClick={() => {
            onChange(item);
          }}
        >
          {text}
        </button>
      ))}
    </div>
  );
}
