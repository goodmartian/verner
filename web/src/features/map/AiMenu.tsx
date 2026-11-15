import { Marker, type Map as MaplibreMap } from 'maplibre-gl';
import { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import type { LngLat } from './draw/geometry';

interface AiMenuProps {
  map: MaplibreMap | null;
  /** Where the shape was pressed. */
  at: LngLat;
  /** The shape can be a drawing of the person's own: not a point. */
  canAdopt: boolean;
  onAsk: () => void;
  onAdopt: () => void;
  onClose: () => void;
}

/** The two things to do with a drawing of the assistant, at the place it was pressed: ask about it, or make a copy of it that is the person's own. */
export function AiMenu({ map, at, canAdopt, onAsk, onAdopt, onClose }: AiMenuProps) {
  const { t } = useI18n();
  const element = useMemo(() => document.createElement('div'), []);

  useEffect(() => {
    if (!map) return;
    // the menu opens toward the middle of the map, so that no edge cuts it
    const spot = map.project(at);
    const box = map.getContainer();
    const width = element.offsetWidth || 200;
    const room = { right: box.clientWidth - spot.x - 16, left: spot.x - 16 };
    // the side with room for it, the right one first; when neither has, the menu is centred on the place
    const side = room.right >= width ? 'left' : room.left >= width ? 'right' : null;
    const above = spot.y > box.clientHeight / 2;
    const marker = new Marker({
      element,
      anchor: `${above ? 'bottom' : 'top'}${side ? `-${side}` : ''}` as 'top',
      offset: [side === 'left' ? 8 : side === 'right' ? -8 : 0, above ? -8 : 8],
    })
      .setLngLat(at)
      .addTo(map);
    // another press on the map, or a move of the map, takes the menu away
    map.on('movestart', onClose);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      map.off('movestart', onClose);
      document.removeEventListener('keydown', onKey);
      marker.remove();
    };
  }, [map, at, element, onClose]);

  return createPortal(
    <div className="ai-menu" role="menu" aria-label={t('map.aiMenu')}>
      <button
        type="button"
        role="menuitem"
        className="btn btn-primary"
        onClick={(event) => {
          event.stopPropagation();
          onAsk();
        }}
      >
        <Ph name="sparkle" />
        <span>{t('map.aiAsk')}</span>
      </button>
      {canAdopt ? (
        <button
          type="button"
          role="menuitem"
          className="btn btn-secondary"
          onClick={(event) => {
            event.stopPropagation();
            onAdopt();
          }}
        >
          <Ph name="polygon" />
          <span>{t('map.aiAdopt')}</span>
        </button>
      ) : null}
    </div>,
    element,
  );
}
