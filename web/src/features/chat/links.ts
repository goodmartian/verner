/** What a link in the text of an answer points at. */
export type Target =
  | { kind: 'web'; url: string }
  | { kind: 'fire'; id: string }
  | { kind: 'period'; from: string; to: string }
  | { kind: 'area'; id: string }
  | { kind: 'shape'; id: string };

const MONTH = '(\\d{4}-(?:0[1-9]|1[0-2]))';
const PERIOD = new RegExp(`^period:${MONTH}(?:\\.\\.${MONTH})?$`);
const FIRE = /^fire:([A-Za-z0-9_-]{1,40})$/;
const AREA = /^area:([A-Za-z0-9_-]{1,40})$/;
const SHAPE = /^shape:(A\d{1,4})$/;

/** The target of a link, or null for one that is not to be followed: only web addresses and the four schemes of the assistant. */
export function parseTarget(url: string): Target | null {
  if (/^https?:\/\//i.test(url)) return { kind: 'web', url };
  const fire = FIRE.exec(url);
  if (fire?.[1]) return { kind: 'fire', id: fire[1] };
  const period = PERIOD.exec(url);
  if (period?.[1]) {
    const to = period[2] ?? period[1];
    // the start is not later than the end
    return period[1] <= to ? { kind: 'period', from: period[1], to } : null;
  }
  const area = AREA.exec(url);
  if (area?.[1]) return { kind: 'area', id: area[1] };
  const shape = SHAPE.exec(url);
  if (shape?.[1]) return { kind: 'shape', id: shape[1] };
  return null;
}

/** For the markdown renderer: an address it may keep as it is, or the empty one, which takes the link away and leaves its words. */
export const keepTarget = (url: string): string => (parseTarget(url) ? url : '');
