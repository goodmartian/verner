import { useCallback } from 'react';
import type { FireDetail, FirePlan, PlanRequest } from '../../api/types';
import { useFiresState, type Brief } from './context';
import { useFire, usePlanMaker } from './queries';

/** What the planner is asked: the brief of the operator. A pass goes only when the person chose one: else the server takes the last pass that saw the fire. */
export function toRequest(pass: number | null, brief: Brief): PlanRequest {
  return {
    ...(pass === null ? {} : { pass }),
    crews: brief.crews,
    hours: brief.hours,
    marks: brief.marks.map((mark) => ({
      kind: mark.kind,
      position: [mark.position[0], mark.position[1]],
    })),
    area: brief.area ? brief.area.map((corner) => [corner[0], corner[1]]) : null,
    overrides: [...brief.overrides],
  };
}

/** The fire on screen: the one kept with an opened saved plan, or the one from the server at the pass on screen. */
export function useShownFire(): FireDetail | undefined {
  const state = useFiresState();
  const open = useFire(state.fireId, state.pass);
  return state.fireId ? (state.record?.fire ?? open.data) : undefined;
}

/**
 * Puts a plan on the map: the fire is selected and the plan set (the demo switch follows the plan).
 * The button of a card also opens the dock; a plan the assistant makes by itself does not, as the chat
 * is still writing the answer that explains it.
 */
export function useShowPlan() {
  const { demo, setDemo, select, setPlan, setDock } = useFiresState();
  return useCallback(
    (plan: FirePlan, dock = true) => {
      if ((plan.source === 'demo') !== demo) setDemo(plan.source === 'demo');
      select(plan.fire_id);
      setPlan(plan);
      if (dock) setDock(true);
    },
    [demo, setDemo, select, setPlan, setDock],
  );
}

/** Makes the plan of the open fire from the brief; `overrides` replaces the blocks the operator has overruled. */
export function useBuildPlan() {
  const detail = useShownFire();
  const maker = usePlanMaker();
  const { setPlan, brief, pass, toggleOverride } = useFiresState();

  const build = useCallback(
    async (overrides: readonly string[] = brief.overrides): Promise<FirePlan> => {
      if (!detail) throw new Error('no fire is open');
      const plan = await maker.mutateAsync({
        fireId: detail.summary.id,
        request: toRequest(pass, { ...brief, overrides }),
      });
      setPlan(plan);
      return plan;
    },
    [detail, brief, pass, maker, setPlan],
  );

  /** Overrules a block, or takes it back, and makes the plan again. */
  const override = useCallback(
    async (keys: readonly string[], on: boolean) => {
      const next = on
        ? [...new Set([...brief.overrides, ...keys])]
        : brief.overrides.filter((item) => !keys.includes(item));
      for (const item of keys) {
        if (brief.overrides.includes(item) !== on) toggleOverride(item);
      }
      await build(next);
    },
    [brief.overrides, toggleOverride, build],
  );

  return { build, override, pending: maker.isPending, error: maker.error };
}
