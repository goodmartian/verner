import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, call, callEmpty } from '../../api/client';
import type { PlanRequest } from '../../api/types';
import { useBoard } from '../board/context';
import { useFiresState } from './context';
import { areaId } from '../../config/context';
import { useAreaFlags, WORLD } from '../calendar/areas';
import { areaRequests } from '../../api/area';
import { orAbsent } from '../climate/queries';

const PLANS = ['plans'] as const;
import type { AreaRef } from '../../config/types';

/** The fires of the last three days in the region, or the example when `demo` is set. */
export const useFires = (demo: boolean, region?: AreaRef, enabled = true) =>
  useQuery({
    enabled,
    queryKey: ['fires', demo, region],
    queryFn: () =>
      call(
        region
          ? areaRequests.fires(region, demo)
          : api.GET('/api/fires', { params: { query: { demo } } }),
      ),
    // the server builds a new snapshot every half hour
    refetchInterval: 5 * 60_000,
  });

/** One fire as it was at a pass (the last one when `pass` is null). */
export const useFire = (id: string | null, pass: number | null) =>
  useQuery({
    enabled: id !== null,
    queryKey: ['fire', id, pass],
    queryFn: () => {
      if (!id) throw new Error('no fire');
      return call(
        api.GET('/api/fires/{fire_id}', {
          params: { path: { fire_id: id }, query: pass === null ? {} : { pass } },
        }),
      );
    },
    // the pass being looked at stays on screen while the next one loads
    placeholderData: (previous) => previous,
  });

export const usePlanMaker = () =>
  useMutation({
    mutationFn: ({ fireId, request }: { fireId: string; request: PlanRequest }) =>
      call(
        api.POST('/api/fires/{fire_id}/plan', {
          params: { path: { fire_id: fireId } },
          body: request,
        }),
      ),
  });

/** Whether the fires have the area on the board: the countries with full data and the whole world (its 50 largest); null until it is known. */
export function useFiresCovered(): boolean | null {
  const { area } = useBoard();
  const covered = useAreaFlags().covered;
  const id = areaId(area);
  // a region of a country is asked for its fires at once: its own answer, an empty list, says what is there; only the calendar knows more
  return id === WORLD ? true : (covered ?? (id === null ? null : true));
}

/** The list of fires as the board asks for it: the example or the live ones, in the region on the board. */
export function useFiresList() {
  const { demo } = useFiresState();
  const { area } = useBoard();
  const id = areaId(area);
  const covered = useFiresCovered();
  const enabled = id !== null && covered === true;
  const query = useFires(demo, area ?? undefined, enabled);
  return { ...query, data: enabled ? query.data : undefined, isError: enabled && query.isError };
}

/** The ground under the open fire (a grid of classes and the share of each under the outline); null while the server has no tile of it (404). */
export const useLandCover = (id: string | null, pass: number | null) =>
  useQuery({
    enabled: id !== null,
    queryKey: ['fire', id, pass, 'land-cover'],
    queryFn: () => {
      if (!id) throw new Error('no fire');
      return orAbsent(
        api.GET('/api/fires/{fire_id}/land-cover', {
          params: { path: { fire_id: id }, query: pass === null ? {} : { pass } },
        }),
      );
    },
    retry: false,
    staleTime: 10 * 60_000,
  });

/** The way in to the open fire (OpenStreetMap roads); null when the server has no route for it (404). */
export const useAccessRoute = (id: string | null, pass: number | null) =>
  useQuery({
    enabled: id !== null,
    queryKey: ['fire', id, pass, 'access-route'],
    queryFn: () => {
      if (!id) throw new Error('no fire');
      return orAbsent(
        api.GET('/api/fires/{fire_id}/access-route', {
          params: { path: { fire_id: id }, query: pass === null ? {} : { pass } },
        }),
      );
    },
    retry: false,
    staleTime: 10 * 60_000,
  });

/** The plans of this browser, the newest first. */
export const usePlans = () =>
  useQuery({
    queryKey: PLANS,
    retry: false,
    queryFn: () => call(api.GET('/api/plans')),
  });

/** Keeps a plan: the server makes it again on one pass, and keeps the plan and the card of the fire. */
export function useSavePlan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (plan: { fireId: string; title: string; request: PlanRequest }) =>
      call(
        api.POST('/api/plans', {
          body: { fire_id: plan.fireId, title: plan.title, request: plan.request },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: PLANS }),
  });
}

/** A kept plan with the fire as it was when the plan was made. */
export const useOpenPlan = () =>
  useMutation({
    mutationFn: (id: number) =>
      call(api.GET('/api/plans/{plan_id}', { params: { path: { plan_id: id } } })),
  });

export function useDeletePlan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      callEmpty(api.DELETE('/api/plans/{plan_id}', { params: { path: { plan_id: id } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: PLANS }),
  });
}
