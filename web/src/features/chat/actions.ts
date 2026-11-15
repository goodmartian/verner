import { createContext, useContext } from 'react';
import type { FirePlan } from '../../api/types';
import type { AreaRef } from '../../config/types';

/** What a button inside an answer can do to the board; the shell gives it its hands. */
export interface WidgetActions {
  openFire: (id: string) => void;
  showPeriod: (area: AreaRef | string, from: string, to: string) => void;
  /** Shows a place of the calendar by its code (`AR`, a province, a country) or the name of an area drawn on the map. */
  showArea: (code: string) => void;
  /** The pointer is on the mention of a fire in an answer (null when it leaves): the fire is marked on the map. */
  hoverFire: (id: string | null) => void;
  /** Centres the map on a drawing of the assistant by its name, `A3`. */
  showShape: (id: string) => void;
  showPlan: (plan: FirePlan) => void;
  /** Puts a month of the board in the question as an attachment, the same one the plus of the field gives. */
  addMonth: (month: string) => void;
  /** Puts one figure of the board in the question: it goes as a line of context, `label: value (area, period)`. */
  addFact: (fact: { label: string; value: string; area: string; period: string }) => void;
  /** Takes a file the assistant prepared into the downloads; rejects when the file is gone or the request fails. */
  downloadFile?: (file: { id: string; name: string }) => Promise<void>;
}

export const WidgetActionsContext = createContext<WidgetActions | null>(null);

export function useWidgetActions(): WidgetActions | null {
  return useContext(WidgetActionsContext);
}
