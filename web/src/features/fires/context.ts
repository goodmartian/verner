import { createContext, useContext } from 'react';
import type { FirePlan } from '../../api/types';
import type { LngLat } from '../map/draw/geometry';
import type { PlanRecord } from '../../api/types';

export type MarkKind = 'entry' | 'hot';

export interface Mark {
  kind: MarkKind;
  position: LngLat;
}

export type Hours = 1 | 3 | 6;

/** What the operator asks of the plan. */
export interface Brief {
  crews: number;
  hours: Hours;
  marks: readonly Mark[];
  /** Corners of the work area drawn on the map. */
  area: readonly LngLat[] | null;
  /** Keys of the blocks the operator overruled (`issues[].key`), sent with the brief. */
  overrides: readonly string[];
}

/** What the map does with the marks of the operator, so that its undo and redo cover them. */
export interface MarksApi {
  clear: (kind: MarkKind) => void;
  load: (marks: readonly Mark[]) => void;
}

export const MAX_CREWS = 20;

export interface Fires {
  /** Look at the example fires instead of the live ones. */
  demo: boolean;
  setDemo: (demo: boolean) => void;
  fireId: string | null;
  /** The fire the pointer is on in the list, drawn out on the map; null when none. */
  hovered: string | null;
  setHovered: (id: string | null) => void;
  /** Opens a fire (or closes it with null); everything about the old one is dropped. */
  select: (id: string | null) => void;
  /** The pass on screen; null is the last one. */
  pass: number | null;
  setPass: (pass: number) => void;
  /** An hour of the player's forecast tail, after the last pass, where the weather is the only thing to look at; null on a pass. */
  clock: string | null;
  setClock: (clock: string) => void;
  brief: Brief;
  setCrews: (crews: number) => void;
  setHours: (hours: Hours) => void;
  /** The marks the map has, told by it after each change; the map keeps them with its drawings. */
  setMarks: (marks: readonly Mark[]) => void;
  /** Takes off every mark of one kind. */
  clearMarks: (kind: MarkKind) => void;
  /** The map says how marks are set and taken off; null when it is gone. */
  bindMarks: (api: MarksApi | null) => void;
  setArea: (area: readonly LngLat[] | null) => void;
  /** Overrules a block of the plan, or takes that back. */
  toggleOverride: (key: string) => void;
  /** The kind of mark the next click on the map places. */
  placing: MarkKind | null;
  setPlacing: (kind: MarkKind | null) => void;
  /** The hours of the forecast front on the map, 1, 3 or 6; 0 when none is shown. */
  forecast: 0 | 1 | 3 | 6;
  setForecast: (hours: 0 | 1 | 3 | 6) => void;
  /** The row of satellite passes over the map is open. */
  player: boolean;
  setPlayer: (player: boolean) => void;
  /** The plan form is open. */
  planning: boolean;
  setPlanning: (planning: boolean) => void;
  plan: FirePlan | null;
  setPlan: (plan: FirePlan | null) => void;
  /** The vegetation around the open fire is drawn on the map. */
  cover: boolean;
  setCover: (cover: boolean) => void;
  /** The plan window is open in the place of the conversation. */
  dock: boolean;
  setDock: (dock: boolean) => void;
  /** The crew whose lines the pointer is on in the plan window; 0 when none. */
  crewHi: number;
  setCrewHi: (crew: number) => void;
  /** The crew the map is asked to frame; the object is new at each ask. */
  crewFocus: { crew: number } | null;
  focusCrew: (crew: number) => void;
  /** A saved plan on screen: its fire is the one kept with it. */
  record: PlanRecord | null;
  openRecord: (record: PlanRecord) => void;
  /** The plan on screen has been kept in this browser: the same plan while `signature` matches. */
  saved: string | null;
  setSaved: (signature: string | null) => void;
}

export const FiresContext = createContext<Fires | null>(null);

export function useFiresState(): Fires {
  const value = useContext(FiresContext);
  if (!value) throw new Error('useFiresState needs a FiresProvider above it');
  return value;
}
