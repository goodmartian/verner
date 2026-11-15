import type { AskInfo } from '../../ui/AskPop';
import { useWidgetActions } from '../chat/actions';

/**
 * The card of a figure of a fire: what it is, its number, and «Спросить ИИ», which puts the figure in the question with the fire that is open.
 * `place` and `period` say where and when the figure is; without the hands of the shell (a test of a part alone) there is no card.
 */
export function useFireAsk(place: string, period: string) {
  const actions = useWidgetActions();
  return (title: string, value: string, note?: string): AskInfo | null =>
    actions
      ? {
          title,
          value,
          ...(note ? { note } : {}),
          ask: () => {
            actions.addFact({ label: title, value, area: place, period });
          },
        }
      : null;
}
