import { useEffect, useEffectEvent, useState } from 'react';

/** Play for a player: every `ms` it goes to the next of the `walk`, `at` being where it stands now (-1 before the first); it stops at the end. */
export function usePlayback<T>(walk: readonly T[], at: number, ms: number, go: (value: T) => void) {
  const [playing, setPlaying] = useState(false);
  const next = useEffectEvent(() => {
    const value = walk[at + 1];
    if (value === undefined) setPlaying(false);
    else go(value);
  });
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(next, ms);
    return () => {
      window.clearInterval(timer);
    };
  }, [playing, ms]);

  return {
    playing,
    stop: () => {
      setPlaying(false);
    },
    /** Pause, or play on; from the end it starts over from the first. */
    toggle: () => {
      if (playing) {
        setPlaying(false);
        return;
      }
      const first = walk[0];
      if (at >= walk.length - 1 && first !== undefined) go(first);
      setPlaying(true);
    },
  };
}
