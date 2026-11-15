import { useEffect, useRef, useState } from 'react';
import { advance, head } from './pace';

const reduced = () =>
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * What is shown of an answer that arrives in pieces: the pieces wait in a buffer and come out frame by frame at an even
 * pace, which follows how far behind the buffer is; when the answer is over the rest is written fast. A text that was
 * there whole (a chat of the history) is shown at once. The text comes out by whole words.
 */
export function useSmoothText(text: string, streaming: boolean): string {
  const [shown, setShown] = useState(() => (streaming ? 0 : text.length));
  const position = useRef(shown);
  const latest = useRef({ text, streaming });
  useEffect(() => {
    latest.current = { text, streaming };
  });

  useEffect(() => {
    if (reduced()) {
      position.current = latest.current.text.length;
      setShown(position.current);
      return;
    }
    if (!streaming && position.current >= latest.current.text.length) return;
    let frame = 0;
    let before = performance.now();
    const tick = (now: number) => {
      const { text: current, streaming: live } = latest.current;
      // a long pause (a hidden tab) is not a long step
      const dt = Math.min((now - before) / 1000, 0.1);
      before = now;
      position.current = advance(
        Math.min(position.current, current.length),
        current.length,
        dt,
        !live,
      );
      setShown(Math.floor(position.current));
      if (live || position.current < current.length) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [streaming]);

  const out = head(text, Math.min(shown, text.length));
  // by whole words: a word that is still being written waits for its last letter
  return out.length >= text.length ? out : out.slice(0, Math.max(0, out.search(/\s\S*$/)));
}
