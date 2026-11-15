import { useLayoutEffect, useState } from 'react';

/** Where an element is on screen, kept current as it or the window changes. */
export function useElementRect(element: HTMLElement | null): DOMRect | null {
  const [rect, setRect] = useState<DOMRect | null>(null);

  useLayoutEffect(() => {
    if (!element) return;
    const measure = () => {
      setRect(element.getBoundingClientRect());
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    window.addEventListener('resize', measure);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [element]);

  return element ? rect : null;
}
