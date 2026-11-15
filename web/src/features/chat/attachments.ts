import type { LngLat } from '../map/draw/geometry';
import type { AreaRef } from '../../config/types';

/** What the person puts on the question besides words: a month of the calendar, a figure of the board or an area drawn on the map. */
export type Attachment =
  | { kind: 'month'; month: string; area: AreaRef | string; label: string }
  /** One figure of the board (a year, a row of a card, a point of a chart) that the person asks about. */
  | { kind: 'fact'; label: string; value: string; area: string; period: string }
  | {
      kind: 'area';
      id: string;
      points: readonly LngLat[];
      n: number;
      label?: string;
      role?: 'area' | 'safe_zone';
    };
