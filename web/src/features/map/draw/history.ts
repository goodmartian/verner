/** A value with the earlier and the undone values around it. */
export interface History<T> {
  past: readonly T[];
  present: T;
  future: readonly T[];
}

export const startHistory = <T>(present: T): History<T> => ({ past: [], present, future: [] });

export const commit = <T>(history: History<T>, present: T): History<T> => ({
  past: [...history.past, history.present],
  present,
  future: [],
});

export function undo<T>(history: History<T>): History<T> {
  const previous = history.past.at(-1);
  if (previous === undefined) return history;
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future],
  };
}

export function redo<T>(history: History<T>): History<T> {
  const [next, ...rest] = history.future;
  if (next === undefined) return history;
  return { past: [...history.past, history.present], present: next, future: rest };
}
