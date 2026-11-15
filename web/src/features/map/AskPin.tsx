import { Marker, type Map as MaplibreMap, type MapMouseEvent } from 'maplibre-gl';
import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import type { LngLat } from './draw/geometry';

interface AskPinProps {
  map: MaplibreMap | null;
  /** The corners of the area just closed. */
  points: readonly LngLat[];
  /** The plan form is open: the button puts the area in the plan instead of in the question. */
  planning: boolean;
  onPress: () => void;
}

// how far from the area and its button the pointer may be before the button fades
const NEAR_PX = 16;

/**
 * The button beside the area that was just drawn, at its easternmost corner: "Ask about this area",
 * or "Add to the plan" while the plan form is open. It shows when the area is closed, and fades
 * when the pointer moves away from the area.
 */
export function AskPin({ map, points, planning, onPress }: AskPinProps) {
  const { t } = useI18n();
  // it shows at once: the pointer has just closed the area, and a finger has no pointer to move over it to show it
  const [away, setAway] = useState(false);
  const element = useMemo(() => document.createElement('div'), []);

  useEffect(() => {
    if (!map) return;
    const east = points.reduce<LngLat | null>(
      (best, point) => (best === null || point[0] > best[0] ? point : best),
      null,
    );
    if (!east) return;
    const marker = new Marker({ element, anchor: 'left', offset: [10, 0] })
      .setLngLat(east)
      .addTo(map);
    const onMove = (event: MapMouseEvent) => {
      const corners = points.map((point) => map.project(point));
      const box = element.getBoundingClientRect();
      const frame = map.getContainer().getBoundingClientRect();
      const left = Math.min(...corners.map((c) => c.x)) - NEAR_PX;
      const top = Math.min(Math.min(...corners.map((c) => c.y)), box.top - frame.top) - NEAR_PX;
      const right =
        Math.max(Math.max(...corners.map((c) => c.x)), box.right - frame.left) + NEAR_PX;
      const bottom =
        Math.max(Math.max(...corners.map((c) => c.y)), box.bottom - frame.top) + NEAR_PX;
      const { x, y } = event.point;
      setAway(!(x >= left && x <= right && y >= top && y <= bottom));
    };
    map.on('mousemove', onMove);
    return () => {
      map.off('mousemove', onMove);
      marker.remove();
    };
  }, [map, points, element]);

  return createPortal(
    <button
      type="button"
      className={`btn btn-primary map-ask${away ? ' away' : ''}`}
      onPointerEnter={() => {
        setAway(false);
      }}
      onClick={(event) => {
        event.stopPropagation();
        onPress();
      }}
    >
      <Ph name={planning ? 'path' : 'sparkle'} />
      <span>{t(planning ? 'map.areaToPlan' : 'map.askArea')}</span>
    </button>,
    element,
  );
}
