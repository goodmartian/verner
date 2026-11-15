import { createContext, useContext } from 'react';
import type { DrawShape } from '../../api/types';
import type { LngLat } from '../map/draw/geometry';
import type { Month, MonthRange } from '../calendar/months';
import type { AreaRef } from '../../config/types';

/** How many years can be compared at once: each has a line of its own in the chart. */
export const MAX_COMPARED_YEARS = 4;

/** An area drawn on the map: its name (`U1`) and its corners. */
export interface DrawnArea {
  id: string;
  points: readonly LngLat[];
  /** A zone marked as safe is told to the assistant as one, which then checks it against the fires. */
  role: 'area' | 'safe_zone';
}

/** What the map does with the assistant's drawings; the map hands it over when it is there. */
export interface AiMap {
  draw: (shapes: readonly DrawShape[], replace: boolean) => void;
  clear: () => void;
  /** Centres the map on a drawing. */
  show: (id: string) => void;
}

/** What the calendar and the map are looking at: the place, the period and the month on the map. */
export interface Board {
  /** A catalog area, independent polygon, or saved area. */
  area: AreaRef | null;
  /** The corners of the area when `area` is `drawn`. */
  polygon: readonly LngLat[] | null;
  /** Every area on the map that closes on itself, so that the assistant can be told of them. */
  drawn: readonly DrawnArea[];
  /** The years put side by side; two or more make a comparison. */
  years: readonly number[];
  /** The chosen period; null means the default one of the area. */
  range: MonthRange | null;
  /** The month shown on the map; null means the first month of the period. */
  pick: Month | null;
  /** The day of the month on the map, `YYYY-MM-DD`; null while the month as a whole is shown. */
  day: string | null;
  /** The cluster of fires of that day that is open, by its id; null for none. */
  cluster: string | null;
  /** The hour of the open cluster whose weather is on screen, an ISO time; null for the hour of its first detection. */
  clock: string | null;
  /** The forecast's blind check is shown instead of the period. */
  check: boolean;
  setArea: (area: AreaRef | string) => void;
  showDrawn: (polygon: readonly LngLat[]) => void;
  /** The map tells what is drawn on it now; an area that is gone is no longer shown. */
  setDrawn: (drawn: readonly DrawnArea[]) => void;
  /** Adds a year to the comparison, or takes it out. */
  toggleYear: (year: number) => void;
  setRange: (range: MonthRange | null) => void;
  setPick: (month: Month) => void;
  /** Picks a day of the month on the map (or the month again with null); the open cluster is closed. */
  setDay: (day: string | null) => void;
  setCluster: (cluster: string | null) => void;
  setClock: (clock: string | null) => void;
  setCheck: (check: boolean) => void;
  /** The fires are on screen: an outline on the board gives way to the place shown before it, until the statistics are back. */
  setOnFires: (on: boolean) => void;
  /** The assistant draws on the map (what it drew before goes first when `replace` is on). Drawn before the map is there, it waits for it. */
  drawAi: (shapes: readonly DrawShape[], replace: boolean) => void;
  /** Takes the assistant's drawings off the map: another chat has none of them. */
  clearAi: () => void;
  /** Centres the map on a drawing of the assistant by its name, `A3`. */
  showShape: (id: string) => void;
  /** The map says it can show the drawings (null when it is gone). */
  bindAi: (map: AiMap | null) => void;
}

export const BoardContext = createContext<Board | null>(null);

export function useBoard(): Board {
  const value = useContext(BoardContext);
  if (!value) throw new Error('useBoard needs a BoardProvider above it');
  return value;
}
