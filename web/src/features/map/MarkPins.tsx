import { Marker, type Map as MaplibreMap } from 'maplibre-gl';
import { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import type { LngLat } from './draw/geometry';
import type { MarkKind } from './draw/shapes';

export interface MarkPin {
  id: string;
  kind: MarkKind;
  position: LngLat;
}

interface MarkPinsProps {
  map: MaplibreMap | null;
  marks: readonly MarkPin[];
  onMove: (id: string, position: LngLat) => void;
  onRemove: (id: string) => void;
}

/** The marks of the operator on the map: a pin with its number, dragged to move it, a cross to take it off. */
export function MarkPins({ map, marks, onMove, onRemove }: MarkPinsProps) {
  const { t } = useI18n();
  const elements = useMemo(
    () =>
      new Map(
        marks.map((mark) => {
          const element = document.createElement('div');
          element.className = 'mk';
          return [mark.id, element];
        }),
      ),
    [marks],
  );

  useEffect(() => {
    if (!map) return;
    const pins = marks.flatMap((mark) => {
      const element = elements.get(mark.id);
      if (!element) return [];
      const marker = new Marker({ element, draggable: true, anchor: 'bottom', offset: [0, -4] })
        .setLngLat(mark.position)
        .addTo(map);
      marker.on('dragend', () => {
        const at = marker.getLngLat();
        onMove(mark.id, [at.lng, at.lat]);
      });
      return [marker];
    });
    return () => {
      for (const pin of pins) pin.remove();
    };
  }, [map, marks, elements, onMove]);

  return marks.map((mark, index) => {
    const element = elements.get(mark.id);
    const number = marks.slice(0, index + 1).filter((item) => item.kind === mark.kind).length;
    const name = t(mark.kind === 'entry' ? 'plan.entryMark' : 'plan.hotMark', { n: number });
    return element
      ? createPortal(
          <div className={`mark ${mark.kind}`}>
            <Ph name={mark.kind === 'entry' ? 'sign-in' : 'target'} />
            <span>{name}</span>
            <button
              type="button"
              className="mk-x"
              aria-label={t('plan.removeMark', { name })}
              onPointerDown={(event) => {
                event.stopPropagation();
              }}
              onClick={(event) => {
                event.stopPropagation();
                onRemove(mark.id);
              }}
            >
              <Ph name="x" />
            </button>
          </div>,
          element,
          mark.id,
        )
      : null;
  });
}
