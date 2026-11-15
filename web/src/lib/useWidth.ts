import { useEffect, useRef, useState } from 'react';

/**
 * The width of an element in pixels, kept current; 0 until it is on the screen.
 *
 * With `steps` (ascending, fixed for the life of the component) the width comes as the largest step it reaches: a
 * component that only asks on which side of a threshold it stands is then drawn again when it crosses one, not for
 * every pixel of a resize.
 */
export function useWidth(steps?: readonly number[]) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      const now = element.clientWidth;
      setWidth(steps ? (steps.findLast((step) => step <= now) ?? 0) : now);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [steps]);
  return { ref, width };
}
