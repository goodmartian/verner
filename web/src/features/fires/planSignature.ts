import type { FirePlan } from '../../api/types';

/** The plan as a signature: the same plan is told apart from another by it, and a saved one by its mark. */
export const planSignature = (plan: FirePlan) =>
  JSON.stringify([
    plan.fire_id,
    plan.pass_index,
    plan.hours,
    plan.entry.position,
    plan.crews.map((c) => [c.entry, c.status]),
  ]);
