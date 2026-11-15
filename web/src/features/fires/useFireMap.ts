import { useMemo } from 'react';
import type { Bounds } from '../map/basemaps';
import type { FireLayerData } from '../map/useFireLayers';
import { useFiresState } from './context';
import { fireCollections } from './mapData';
import { joinCredits } from './access';
import { useAccessRoute, useFire, useFiresList } from './queries';

type Position = readonly number[];

const positions = (coordinates: unknown): Position[] =>
  Array.isArray(coordinates) && typeof coordinates[0] === 'number'
    ? [coordinates as Position]
    : Array.isArray(coordinates)
      ? coordinates.flatMap(positions)
      : [];

function boundsOf(points: readonly Position[]): Bounds | undefined {
  const lngs = points.map((p) => p[0] ?? 0);
  const lats = points.map((p) => p[1] ?? 0);
  if (lngs.length === 0) return undefined;
  return [
    [Math.min(...lngs), Math.min(...lats)],
    [Math.max(...lngs), Math.max(...lats)],
  ];
}

// what frames a fire in view: where it burned; with a forecast front, where it may go; with a plan, the crews' ways
const framed = (forecast: boolean, planned: boolean) =>
  planned
    ? (['planLines', 'planPins'] as const)
    : forecast
      ? (['scar', 'contours', 'detections'] as const)
      : (['scar', 'detections'] as const);

/** What the map shows for the fires: the layers, and the frame around the fire in view or around all of them. */
export function useFireMap(enabled: boolean): { data: FireLayerData | null; bounds?: Bounds } {
  const state = useFiresState();
  const list = useFiresList().data;
  const shown = useFire(state.fireId, state.pass).data;
  const latest = useFire(state.fireId, null).data;
  const access = useAccessRoute(state.fireId, state.pass).data ?? null;
  const detail = state.fireId ? (state.record?.fire ?? shown ?? null) : null;
  const whole = state.fireId ? (state.record?.fire ?? latest ?? null) : null;

  const fires = list?.fires;
  const attribution = list?.attribution;
  const { fireId, plan, forecast, crewHi, crewFocus, hovered } = state;

  const data = useMemo(
    () =>
      enabled
        ? {
            ...fireCollections({
              fires: fires ?? [],
              selectedId: fireId,
              detail,
              plan,
              access,
              forecast,
            }),
            credits: joinCredits([
              detail?.attribution ?? attribution,
              fireId ? access?.attribution : null,
            ]),
            crewHi,
            hovered,
          }
        : null,
    [enabled, fires, fireId, detail, plan, access, forecast, attribution, crewHi, hovered],
  );

  // framed on the fire as it is now, so that an early pass, when the fire was not there yet, keeps the frame
  const bounds = useMemo(() => {
    // a crew asked for: its way in and its way out
    const crew = crewFocus ? plan?.crews.find((item) => item.number === crewFocus.crew) : undefined;
    if (crew) return boundsOf([...crew.route, ...crew.escape]);
    // the whole region while no fire is open
    if (!whole) return undefined;
    const frame = fireCollections({
      fires: [],
      selectedId: fireId,
      detail: whole,
      plan,
      forecast,
    });
    return boundsOf([
      ...framed(forecast > 0, plan !== null).flatMap((layer) =>
        frame[layer].features.flatMap((feature) => positions(feature.geometry.coordinates)),
      ),
      ...(access?.road_path && plan === null ? [access.fire_edge_point] : []),
    ]);
  }, [whole, fireId, plan, access, crewFocus, forecast]);

  return { data, bounds };
}
