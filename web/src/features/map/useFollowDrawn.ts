import type { Map as MaplibreMap, MapMouseEvent } from 'maplibre-gl';
import { useEffect, useRef } from 'react';
import { useBoard, type DrawnArea } from '../board/context';

/**
 * On the calendar the board follows the person's drawings: an area just closed is shown at once,
 * and a press on another drawn area shows that one. The fires keep their drawings to themselves.
 */
export function useFollowDrawn(
  map: MaplibreMap | null,
  on: boolean,
  areas: readonly DrawnArea[],
  asking: string | null,
  pan: boolean,
) {
  const { showDrawn, polygon } = useBoard();
  const latest = useRef({ on, areas, pan, polygon, showDrawn });
  useEffect(() => {
    latest.current = { on, areas, pan, polygon, showDrawn };
  });

  // each closed area is shown once, when it is closed; undo and redo close nothing
  const shown = useRef<string | null>(null);
  useEffect(() => {
    if (!asking || asking === shown.current) return;
    shown.current = asking;
    const { on: following, areas: now, showDrawn: show } = latest.current;
    const area = now.find((item) => item.id === asking);
    if (following && area?.role === 'area') show(area.points);
  }, [asking]);

  useEffect(() => {
    if (!map) return;
    const onPress = (event: MapMouseEvent & { features?: { properties?: unknown }[] }) => {
      const now = latest.current;
      if (!now.on || !now.pan) return;
      const properties = event.features?.[0]?.properties;
      const id =
        properties && typeof properties === 'object' && 'id' in properties
          ? properties.id
          : undefined;
      const area = now.areas.find((item) => item.id === id);
      // the area already on the board keeps its picked month and day
      if (area?.role === 'area' && area.points !== now.polygon) now.showDrawn(area.points);
    };
    map.on('click', 'sketch-fill', onPress);
    return () => {
      map.off('click', 'sketch-fill', onPress);
    };
  }, [map]);
}
