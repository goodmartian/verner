import { useEffect, useMemo, useState } from 'react';
import { areaId } from '../../config/context';
import { useBoard } from '../board/context';
import type { Bounds } from '../map/basemaps';
import { useRegionGeometry } from '../region/queries';
import { useAreaShape } from './areas';
import { useCellMap } from './queries';

// a quick answer (a country, about 0.05 s) shows no sign of loading at all: the sign would only blink
export const MAP_BUSY_AFTER_MS = 300;

/** The cells of the month or the outline of the area are still on the way, for longer than a blink. */
export function useCalendarMapBusy(enabled: boolean): boolean {
  const { area } = useBoard();
  const cells = useCellMap(enabled).isFetching;
  const outline = useRegionGeometry(enabled ? areaId(area) : null).isFetching;
  const fetching = enabled && (cells || outline);
  const [late, setLate] = useState(false);
  useEffect(() => {
    if (!fetching) return;
    const timer = window.setTimeout(() => {
      setLate(true);
    }, MAP_BUSY_AFTER_MS);
    return () => {
      window.clearTimeout(timer);
      setLate(false);
    };
  }, [fetching]);
  return fetching && late;
}

/** What the map shows for the calendar: the cells of the picked month and where the area is. */
export function useCalendarMap(enabled: boolean) {
  const map = useCellMap(enabled).data ?? null;
  const cells = useMemo(() => (map ? { kind: map.kind, collection: map } : null), [map]);
  const shape = useAreaShape();
  const bounds = useMemo<Bounds | undefined>(
    () =>
      shape
        ? [
            [shape.bbox[0], shape.bbox[1]],
            [shape.bbox[2], shape.bbox[3]],
          ]
        : undefined,
    [shape],
  );
  return { cells, outline: shape?.outline ?? null, bounds };
}
