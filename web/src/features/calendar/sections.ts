/** A section of the board with the distance of its top below the sticky bar (negative: it is under the bar). */
export interface SectionPlace<T extends string> {
  id: T;
  top: number;
}

/** How far a glide has come at the share `p` of its time: it starts softly, goes fastest in the middle and slows to a stop. */
export function ease(p: number): number {
  const at = Math.min(1, Math.max(0, p));
  return at < 0.5 ? 4 * at ** 3 : 1 - (-2 * at + 2) ** 3 / 2;
}

/** How long a glide over `distance` pixels takes, in milliseconds: longer for a longer way, never slow. */
export const glideTime = (distance: number) => Math.min(800, Math.max(320, Math.abs(distance) * 0.4));

/**
 * Scrolls a box to where `target()` says, eased. The target is asked again on every frame, so a card that grows on
 * the way does not throw the scroll off. A wheel, a touch or a key of the person ends it where it is. Returns the
 * way to stop it. The glide is the answer to a press on a section and lasts under a second, so it runs under
 * reduced motion too: the owner asked for it there.
 */
export function glide(scroller: HTMLElement, target: () => number, done: () => void): () => void {
  const limit = () => Math.max(0, scroller.scrollHeight - scroller.clientHeight);
  const aim = () => Math.max(0, Math.min(target(), limit()));
  const from = scroller.scrollTop;
  const time = glideTime(aim() - from);
  const started = performance.now();
  const ends = ['wheel', 'touchstart', 'keydown'] as const;
  let frame = 0;
  let over = false;
  const stop = () => {
    if (over) return;
    over = true;
    cancelAnimationFrame(frame);
    for (const name of ends) window.removeEventListener(name, stop, true);
    done();
  };
  for (const name of ends) window.addEventListener(name, stop, { capture: true, passive: true });
  const tick = (now: number) => {
    const p = (now - started) / time;
    scroller.scrollTop = from + (aim() - from) * ease(p);
    if (p < 1) frame = requestAnimationFrame(tick);
    else stop();
  };
  frame = requestAnimationFrame(tick);
  return stop;
}

/**
 * The section the bar lights. At the very top the first is lit, at the very end the last. In between it is the
 * section that holds the point a third of the way down the box under the sticky bar: from its top to the top of
 * the next one.
 */
export function activeSection<T extends string>(
  places: readonly SectionPlace<T>[],
  scrollTop: number,
  clientHeight: number,
  scrollHeight: number,
): T | null {
  const first = places[0];
  const last = places.at(-1);
  if (!first || !last) return null;
  if (scrollTop < 8) return first.id;
  if (scrollTop + clientHeight >= scrollHeight - 8) return last.id;
  const point = clientHeight / 3;
  let now = first;
  for (const place of places) if (place.top <= point) now = place;
  return now.id;
}
