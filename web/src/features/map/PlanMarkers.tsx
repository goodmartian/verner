import { usePlaceZone } from '../../config/usePlaceZone';
import { Marker, type Map as MaplibreMap } from 'maplibre-gl';
import { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import type { FireDetail, FirePlan } from '../../api/types';
import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import { planChips } from '../fires/planChips';

interface PlanMarkersProps {
  map: MaplibreMap | null;
  plan: FirePlan;
  detail: FireDetail;
}

/** The labels of the plan on the map: crews, entries, hotspots, the safety zone, where the fronts end. */
export function PlanMarkers({ map, plan, detail }: PlanMarkersProps) {
  const { t, lang } = useI18n();
  const zone = usePlaceZone(detail);
  const chips = useMemo(
    () => planChips(t, lang, plan, detail, zone),
    [t, lang, plan, detail, zone],
  );
  const elements = useMemo(
    () =>
      new Map(
        chips.map((chip) => {
          const element = document.createElement('div');
          element.className = 'mk';
          return [chip.key, element];
        }),
      ),
    [chips],
  );

  useEffect(() => {
    if (!map) return;
    const markers = chips.flatMap((chip) => {
      const element = elements.get(chip.key);
      return element
        ? [
            new Marker({ element, anchor: chip.anchor, offset: chip.offset ?? [0, 0] })
              .setLngLat(chip.at)
              .addTo(map),
          ]
        : [];
    });
    return () => {
      for (const marker of markers) marker.remove();
    };
  }, [map, chips, elements]);

  return chips.map((chip) => {
    const element = elements.get(chip.key);
    return element
      ? createPortal(
          <div className={`chip ${chip.tone}`}>
            {chip.icon ? <Ph name={chip.icon} /> : null}
            {chip.tone === 'safe' ? <span>{chip.text}</span> : chip.text}
          </div>,
          element,
          chip.key,
        )
      : null;
  });
}
