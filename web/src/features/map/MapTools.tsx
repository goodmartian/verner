import { useRef, useState } from 'react';
import { useI18n } from '../../i18n/context';
import type { MessageKey } from '../../i18n/en';
import { EmptyNote, type EmptyAction } from '../../ui/EmptyNote';
import { Ph, type PhName } from '../../ui/Ph';
import { PopupMenu } from '../../ui/PopupMenu';
import type { OverlayCard } from './overlays';
import { BASEMAPS, BASEMAP_LABEL, type Basemap } from './basemaps';
import type { Tool } from './draw/controller';
import type { ShapeKind } from './draw/shapes';

const SHAPES: { kind: ShapeKind; key: string; icon: PhName; label: MessageKey }[] = [
  { kind: 'rectangle', key: 'R', icon: 'selection', label: 'map.shape.rectangle' },
  { kind: 'circle', key: 'O', icon: 'circle-dashed', label: 'map.shape.circle' },
  { kind: 'polygon', key: 'P', icon: 'polygon', label: 'map.shape.polygon' },
  { kind: 'ruler', key: 'L', icon: 'ruler', label: 'map.shape.ruler' },
  { kind: 'approach', key: 'A', icon: 'arrow-right', label: 'map.shape.approach' },
  { kind: 'escape', key: 'E', icon: 'sign-out', label: 'map.shape.escape' },
  { kind: 'safe', key: 'Z', icon: 'shield', label: 'map.shape.safe' },
];

interface MapToolsProps {
  mode: 'fires' | 'cal';
  basemap: Basemap;
  onBasemap: (basemap: Basemap) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  tool: Tool;
  shape: ShapeKind;
  onTool: (tool: Tool) => void;
  onShape: (shape: ShapeKind) => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onClear: () => void;
  /** The kind of mark the next click on the map places; only the fires have marks. */
  placing?: 'entry' | 'hot' | null;
  onPlacing?: (kind: 'entry' | 'hot' | null) => void;
  /** The row of passes (fires) or months (calendar) over the map. */
  player: boolean;
  onPlayer: () => void;
  /** The vegetation around the open fire: a tile among the overlays; its key is on the map. */
  cover?: {
    image: string | null;
    loading: boolean;
    on: boolean;
    onToggle: () => void;
  };
  /** The pictures of the weather, as tiles among the overlays. */
  overlays?: {
    cards: readonly OverlayCard[];
    onToggle: (id: string) => void;
    /** The weather layers of the month are not there yet: a tile that is off says so. */
    pending?: boolean;
    /** The weather of the months is there, but not for the month on the map. */
    empty?: boolean;
    /** The last month the weather has, when the month on the map is past it: the way to a month that has it. */
    latest?: EmptyAction | null;
  };
}

/** The map's toolbar, in the stylesheet's `.tools`: the hand, the shapes, the pencil, the marks, undo, the player, layers, zoom. */
export function MapTools({
  mode,
  basemap,
  onBasemap,
  onZoomIn,
  onZoomOut,
  tool,
  shape,
  onTool,
  onShape,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onClear,
  placing,
  onPlacing,
  player,
  onPlayer,
  cover,
  overlays,
}: MapToolsProps) {
  const { t } = useI18n();
  const layersButton = useRef<HTMLButtonElement>(null);
  const shapesButton = useRef<HTMLButtonElement>(null);
  const [layersOpen, setLayersOpen] = useState(false);
  const [shapesOpen, setShapesOpen] = useState(false);
  const current = SHAPES.find((item) => item.kind === shape) ?? SHAPES[0];
  const mark = (kind: 'entry' | 'hot', icon: PhName, label: MessageKey) =>
    onPlacing ? (
      <button
        type="button"
        className="icon-btn"
        data-tool={kind}
        aria-pressed={placing === kind}
        aria-label={t(label)}
        onClick={() => {
          onPlacing(placing === kind ? null : kind);
        }}
      >
        <Ph name={icon} />
      </button>
    ) : null;

  return (
    <div className="tools" role="toolbar" aria-label={t('map.tools')}>
      <button
        type="button"
        className="icon-btn"
        data-tool="pan"
        aria-pressed={tool === 'pan' && !placing}
        aria-label={t('map.tool.pan')}
        onClick={() => {
          onPlacing?.(null);
          onTool('pan');
        }}
      >
        <Ph name="hand" />
      </button>
      <span className="tool-split">
        <button
          type="button"
          className="icon-btn"
          id="shape-btn"
          data-tool="area"
          aria-pressed={tool === shape}
          aria-label={`${t(current?.label ?? 'map.tool.shapes')}, ${current?.key ?? ''}`}
          onClick={() => {
            onPlacing?.(null);
            onTool(shape);
          }}
        >
          <Ph name={current?.icon ?? 'selection'} />
        </button>
        <button
          ref={shapesButton}
          type="button"
          className="shape-caret"
          id="shape-caret"
          aria-expanded={shapesOpen}
          aria-haspopup="menu"
          aria-label={t('map.tool.shapes')}
          onClick={() => {
            setShapesOpen((open) => !open);
          }}
        >
          <Ph name="caret-down" />
        </button>
      </span>
      <PopupMenu
        anchor={shapesButton}
        open={shapesOpen}
        className="shape-menu"
        label={t('map.tool.shapes')}
        id="shape-menu"
        onClose={() => {
          setShapesOpen(false);
        }}
      >
        {SHAPES.map((item) => (
          <span key={item.kind} style={{ display: 'contents' }}>
            {item.kind === 'ruler' || item.kind === 'approach' ? (
              <div className="menu-sep" role="separator" />
            ) : null}
            <button
              type="button"
              className="menu-item"
              role="menuitemradio"
              aria-checked={shape === item.kind}
              onClick={() => {
                onShape(item.kind);
                setShapesOpen(false);
              }}
            >
              <span className="mi">
                <Ph name={item.icon} />
                <span>{t(item.label)}</span>
              </span>
              <kbd>{item.key}</kbd>
            </button>
          </span>
        ))}
      </PopupMenu>
      <button
        type="button"
        className="icon-btn"
        data-tool="pen"
        aria-pressed={tool === 'pencil'}
        aria-label={t('map.tool.pencil')}
        onClick={() => {
          onPlacing?.(null);
          onTool('pencil');
        }}
      >
        <Ph name="pencil-simple" />
      </button>
      {mode === 'fires' ? mark('entry', 'sign-in', 'plan.entryTool') : null}
      {mode === 'fires' ? mark('hot', 'target', 'plan.hotTool') : null}
      <button
        type="button"
        className="icon-btn"
        id="erase"
        aria-label={t('map.tool.erase')}
        onClick={onClear}
      >
        <Ph name="eraser" />
      </button>
      <span className="tsep" aria-hidden="true" />
      <button
        type="button"
        className="icon-btn"
        id="undo"
        aria-label={t('map.undo')}
        disabled={!canUndo}
        onClick={onUndo}
      >
        <Ph name="arrow-counter-clockwise" />
      </button>
      <button
        type="button"
        className="icon-btn"
        id="redo"
        aria-label={t('map.redo')}
        disabled={!canRedo}
        onClick={onRedo}
      >
        <Ph name="arrow-clockwise" />
      </button>
      <span className="tsep" aria-hidden="true" />
      <button
        type="button"
        className="icon-btn"
        id="player-btn"
        aria-pressed={player}
        aria-label={t(mode === 'cal' ? 'pass.months' : 'pass.tool')}
        onClick={onPlayer}
      >
        <Ph name="chart-bar" />
      </button>
      <button
        ref={layersButton}
        type="button"
        className="icon-btn"
        id="layers-btn"
        aria-expanded={layersOpen}
        aria-controls="layers-pop"
        aria-label={t('map.layers')}
        onClick={() => {
          setLayersOpen((open) => !open);
        }}
      >
        <Ph name="stack" />
      </button>
      <span className="tsep" aria-hidden="true" />
      <button
        type="button"
        className="icon-btn"
        id="zin"
        aria-label={t('map.zoomIn')}
        onClick={onZoomIn}
      >
        <Ph name="plus" />
      </button>
      <button
        type="button"
        className="icon-btn"
        id="zout"
        aria-label={t('map.zoomOut')}
        onClick={onZoomOut}
      >
        <Ph name="minus" />
      </button>
      <PopupMenu
        anchor={layersButton}
        open={layersOpen}
        className="layers-pop"
        role="dialog"
        label={t('map.layers')}
        id="layers-pop"
        align="end"
        up
        onClose={() => {
          setLayersOpen(false);
        }}
      >
        <div className="menu-label" id="layers-base">
          {t('map.layers.base')}
        </div>
        <div className="lp-row" role="group" aria-labelledby="layers-base">
          {BASEMAPS.map((name) => (
            <button
              key={name}
              type="button"
              className="base-opt"
              aria-pressed={basemap === name}
              onClick={() => {
                onBasemap(name);
              }}
            >
              <img src={`/thumbs/${name}.png`} alt="" width={48} height={48} loading="lazy" />
              {t(BASEMAP_LABEL[name])}
            </button>
          ))}
        </div>
        {overlays?.cards.length || overlays?.pending || overlays?.empty || cover ? (
          <>
            <div className="menu-sep" role="separator" />
            <div className="menu-label" id="layers-over">
              {t('map.layers.overlays')}
            </div>
            <div className="lp-row" role="group" aria-labelledby="layers-over">
              {overlays?.cards.map((card) => (
                <button
                  key={card.id}
                  type="button"
                  className="base-opt"
                  data-overlay={card.id}
                  aria-pressed={card.on}
                  onClick={() => {
                    overlays.onToggle(card.id);
                  }}
                >
                  <span className="wx-thumb" style={{ background: card.gradient }} />
                  {card.label}
                </button>
              ))}
              {overlays?.pending || overlays?.empty ? (
                <button type="button" className="base-opt" data-overlay="climate" disabled>
                  <span className="wx-thumb wx-pending" />
                  {t('map.climate')}
                  <small>{t(overlays.empty ? 'map.climateEmpty' : 'map.climatePending')}</small>
                </button>
              ) : null}
              {cover ? (
                <button
                  type="button"
                  className="base-opt"
                  data-cover
                  aria-pressed={cover.loading ? undefined : cover.on}
                  aria-busy={cover.loading || undefined}
                  disabled={cover.loading}
                  onClick={cover.onToggle}
                >
                  {cover.image ? (
                    <img src={cover.image} alt="" width={48} height={48} />
                  ) : (
                    <span className="wx-thumb wx-pending" />
                  )}
                  {t('fires.cover')}
                  {cover.loading ? <small>{t('map.climatePending')}</small> : null}
                </button>
              ) : null}
            </div>
            {overlays?.latest ? (
              <EmptyNote text={t('empty.climateLast')} actions={[overlays.latest]} />
            ) : null}
          </>
        ) : null}
      </PopupMenu>
    </div>
  );
}
