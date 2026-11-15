import type { FeatureCollection, MultiPolygon, Polygon } from 'geojson';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useAreaShape } from '../calendar/areas';
import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import type { FireDetail, FirePlan } from '../../api/types';
import { useBoard } from '../board/context';
import type { Basemap, Bounds } from './basemaps';
import type { LngLat } from './draw/geometry';
import { useDrawing } from './draw/useDrawing';
import { AiMenu } from './AiMenu';
import { AskPin } from './AskPin';
import { boundsRing } from './draw/ai';
import { tacticOf } from './draw/shapes';
import { MarkPins } from './MarkPins';
import { PlanMarkers } from './PlanMarkers';
import { useFiresState } from '../fires/context';
import { useClimateMap } from '../climate/useClimateMap';
import { useWeatherMap } from '../weather/useWeatherMap';
import { WeatherHover } from '../weather/WeatherHover';
import { Toast } from '../../ui/Toast';
import { LayerKey } from '../weather/LayerKey';
import { useCalendarLayers } from './useCalendarLayers';
import { useCoverLayer } from './useCoverLayer';
import { useMapCredits } from './useMapCredits';
import { useDayFireLayer } from './useDayFireLayer';
import { useFireLayers, type FireLayerData } from './useFireLayers';
import { MapTools } from './MapTools';
import type { MapPadding } from './framing';
import { useMapView } from './useMapView';
import { useFollowDrawn } from './useFollowDrawn';
import { useCalendarMapBusy } from '../calendar/useCalendarMap';

interface MapStageProps {
  mode: 'fires' | 'cal';
  /** Room the interface takes around the map, so the country is framed in what is left. */
  padding: MapPadding;
  /** The selected fire's frame; otherwise the current area's frame is used. */
  bounds?: Bounds;
  /** Asks the assistant about a drawn area. */
  onAskArea: (id: string) => void;
  /** Asks the assistant about a drawing of its own: by its name and the corners of the area around it. */
  onAskShape: (shape: {
    id: string;
    label: string | null;
    points: readonly LngLat[];
    role: 'area' | 'safe_zone';
  }) => void;
  /** The row of passes or months over the map is on. */
  player: boolean;
  onPlayer: () => void;
  /** What sits over the map's top (the strip of the fire or the month) and bottom (the player). */
  overlay: ReactNode;
  bottom: ReactNode;
  /** The calendar's map fills the whole right area instead of its window. */
  big: boolean;
  onBig: () => void;
  /** The plan's lines are on the map: its key is shown. */
  legend: boolean;
  /** The fires on the map; given only while the fires are on the board. */
  fires?: {
    data: FireLayerData | null;
    onSelect: (id: string) => void;
    /** A mark is being placed: the next click on the map sets it. */
    placing: 'entry' | 'hot' | null;
    onPlacing: (kind: 'entry' | 'hot' | null) => void;
    /** The plan form is open: a drawn area can become the work area. */
    planning: boolean;
    onUseArea: (corners: readonly LngLat[]) => void;
    /** The plan made for the open fire, to be labelled on the map. */
    plan: { plan: FirePlan; detail: FireDetail } | null;
    /** The vegetation around the open fire, when there is a grid of it. */
    cover: {
      image: string | null;
      bbox: readonly number[];
      attribution: string | null;
      loading: boolean;
      on: boolean;
      onToggle: () => void;
      key: readonly { id: number; name: string; color: string }[];
    } | null;
  };
  calendar?: {
    cells: { kind: string; collection: FeatureCollection } | null;
    outline: Polygon | MultiPolygon | null;
    /** The clusters of fires of the picked day, when a day is picked. */
    dayFires?: {
      data: FeatureCollection;
      selected: string | null;
      onSelect: (id: string) => void;
    };
  };
}

const noop = () => undefined;

// the longest the pale bar stands over a map that is still being drawn
const SKEL_MAX_MS = 6000;

/** The stage of the page: the map with its tools, the strip over its top and the player over its bottom. */
export function MapStage({
  mode,
  padding,
  bounds,
  onAskArea,
  onAskShape,
  player,
  onPlayer,
  overlay,
  bottom,
  big,
  onBig,
  legend,
  calendar,
  fires,
}: MapStageProps) {
  const { t } = useI18n();
  const [basemap, setBasemap] = useState<Basemap>('map');
  const shape = useAreaShape();
  const frame = useMemo<Bounds | undefined>(
    () =>
      bounds ??
      (shape
        ? [
            [shape.bbox[0], shape.bbox[1]],
            [shape.bbox[2], shape.bbox[3]],
          ]
        : undefined),
    [bounds, shape],
  );
  const { container, map, zoomIn, zoomOut } = useMapView(basemap, padding, frame);
  // the map is drawn from tiles that come in a few seconds: the pale bar stands over it until it is still for the first time, and no more
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    if (!map) return;
    const still = () => {
      setSettled(true);
    };
    // a map that is already still has no event to come: ask once, after this frame
    const asked = window.requestAnimationFrame(() => {
      if (map.loaded()) setSettled(true);
    });
    map.once('idle', still);
    // slow tiles do not keep the bar for ever: after a few seconds the map is what there is
    const cap = window.setTimeout(still, SKEL_MAX_MS);
    return () => {
      window.clearTimeout(cap);
      window.cancelAnimationFrame(asked);
      map.off('idle', still);
    };
  }, [map]);
  useCalendarLayers(map, calendar?.cells ?? null, calendar?.outline ?? null);
  const drawing = useDrawing(map);
  const placing = fires?.placing ?? null;
  const { addMark } = drawing;
  const place = useCallback(
    (position: LngLat) => {
      if (placing) addMark(placing, position);
    },
    [placing, addMark],
  );
  useFireLayers(map, fires?.data ?? null, {
    onSelect: fires?.onSelect ?? noop,
    placing: placing !== null,
    onPlace: place,
  });
  const cover = fires?.cover?.image ? fires.cover : null;
  useCoverLayer(
    map,
    cover?.image ? { image: cover.image, bbox: cover.bbox } : null,
    cover?.on ?? false,
  );
  useMapCredits(map, 'cover-credits', cover?.on ? cover.attribution : null);
  useDayFireLayer(
    map,
    calendar?.dayFires?.data ?? null,
    calendar?.dayFires?.selected ?? null,
    calendar?.dayFires?.onSelect ?? noop,
  );
  const weather = useWeatherMap(map, mode === 'fires', basemap === 'map');
  const climate = useClimateMap(map, mode === 'cal');
  const overlayCards = mode === 'cal' ? climate.cards : weather.cards;
  const { setDrawn, bindAi } = useBoard();
  // the assistant draws through the board: the map says what it can do with the drawings
  const { draw: aiDraw, clear: aiClear, show: aiShow } = drawing.ai;
  useEffect(() => {
    bindAi({ draw: aiDraw, clear: aiClear, show: aiShow });
    return () => {
      bindAi(null);
    };
  }, [bindAi, aiDraw, aiClear, aiShow]);
  const picked = drawing.ai.picked;
  const pickedShape = picked
    ? drawing.ai.shapes.find((shape) => shape.id === picked.id)
    : undefined;
  const asked = drawing.areas.find((area) => area.id === drawing.asking);
  // the marks live with the drawings, so that undo and redo cover them; the plan form reads them from here
  const { setMarks, bindMarks } = useFiresState();
  const { marks, clearMarks, loadMarks } = drawing;
  useEffect(() => {
    setMarks(marks.map((mark) => ({ kind: mark.kind, position: mark.position })));
  }, [setMarks, marks]);
  useEffect(() => {
    bindMarks({ clear: clearMarks, load: loadMarks });
    return () => {
      bindMarks(null);
    };
  }, [bindMarks, clearMarks, loadMarks]);
  const tools = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setDrawn(drawing.areas);
  }, [setDrawn, drawing.areas]);
  useFollowDrawn(map, mode === 'cal', drawing.areas, drawing.asking, drawing.tool === 'pan');
  // the fires' own layers come with the list beside the map, which says when it is loading
  const busy = useCalendarMapBusy(mode === 'cal');

  // the toolbar's height is what the player stands on
  useEffect(() => {
    const element = tools.current?.querySelector('.tools');
    const app = element?.closest('.app');
    if (!(element instanceof HTMLElement) || !(app instanceof HTMLElement)) return;
    const observer = new ResizeObserver(() => {
      app.style.setProperty('--tools-h', `${String(Math.ceil(element.offsetHeight))}px`);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  return (
    <main className="stage">
      <div ref={container} id="map" role="region" aria-busy={!frame} aria-label={t('map.label')} />
      {!settled ? <span className="skel map-skel" aria-hidden="true" /> : null}
      <button
        type="button"
        className="icon-btn cal-map-max"
        id="cal-map-max"
        aria-expanded={big}
        aria-label={t(big ? 'common.shrink' : 'common.expand')}
        onClick={onBig}
      >
        <Ph name={big ? 'arrows-in-line-horizontal' : 'arrows-out-line-horizontal'} />
      </button>
      <div ref={tools} style={{ display: 'contents' }}>
        <MapTools
          mode={mode}
          basemap={basemap}
          onBasemap={setBasemap}
          onZoomIn={zoomIn}
          onZoomOut={zoomOut}
          tool={drawing.tool}
          shape={drawing.shape}
          onTool={drawing.chooseTool}
          onShape={drawing.chooseShape}
          canUndo={drawing.canUndo}
          canRedo={drawing.canRedo}
          onUndo={drawing.undo}
          onRedo={drawing.redo}
          onClear={drawing.clear}
          placing={fires?.placing}
          onPlacing={fires?.onPlacing}
          player={player}
          onPlayer={onPlayer}
          cover={fires?.cover ?? undefined}
          overlays={
            overlayCards.length > 0 || (mode === 'cal' && (climate.pending || climate.empty))
              ? {
                  cards: overlayCards,
                  pending: mode === 'cal' && climate.pending,
                  empty: mode === 'cal' && climate.empty,
                  latest: mode === 'cal' ? climate.latest : null,
                  onToggle: mode === 'cal' ? climate.toggle : weather.toggle,
                }
              : undefined
          }
        />
      </div>
      <div className="overlays" id="overlays" aria-live="polite">
        {overlay}
      </div>
      <ul
        className="map-key map-legend"
        id="map-legend"
        aria-label={t('key.title')}
        hidden={!legend}
      >
        <li>
          <i className="k k-attack" />
          <span>{t('key.attack')}</span>
        </li>
        <li>
          <i className="k k-escape" />
          <span>{t('key.escape')}</span>
        </li>
        <li>
          <i className="k k-fc" />
          <span>{t('key.forecast')}</span>
        </li>
        <li>
          <i className="k k-safe" />
          <span>{t('key.safe')}</span>
        </li>
      </ul>
      <LayerKey
        rows={mode === 'cal' ? climate.rows : weather.rows}
        cover={fires?.cover?.on ? fires.cover.key : null}
      />
      <Toast message={mode === 'cal' ? null : weather.missing} />
      {/* the points of the month or the outline of the area are slow to come: the map says it is not drawn yet */}
      <div className="toast map-busy" role="status" data-shown={busy ? 'on' : undefined}>
        {busy ? (
          <>
            <Ph name="circle-notch" className="spin" />
            <span>{t('map.loading')}</span>
          </>
        ) : null}
      </div>
      <div className="bottom">{bottom}</div>
      <WeatherHover
        map={map}
        hour={drawing.tool === 'pan' && !placing ? weather.hoverHour : null}
        legend={weather.legend}
      />
      {fires ? (
        <MarkPins
          map={map}
          marks={drawing.marks}
          onMove={drawing.moveMark}
          onRemove={drawing.remove}
        />
      ) : null}
      {fires?.plan ? (
        <PlanMarkers map={map} plan={fires.plan.plan} detail={fires.plan.detail} />
      ) : null}
      {picked && pickedShape ? (
        <AiMenu
          map={map}
          at={picked.at}
          canAdopt={pickedShape.kind !== 'point'}
          onAsk={() => {
            onAskShape({
              id: pickedShape.id ?? picked.id,
              label: pickedShape.label ?? null,
              role: tacticOf(pickedShape) === 'safe' ? 'safe_zone' : 'area',
              points:
                pickedShape.closed && pickedShape.points.length >= 4
                  ? pickedShape.points
                  : boundsRing(pickedShape.points),
            });
            drawing.ai.dismiss();
          }}
          onAdopt={() => {
            drawing.ai.adopt(picked.id);
            drawing.ai.dismiss();
          }}
          onClose={drawing.ai.dismiss}
        />
      ) : null}
      {asked ? (
        <AskPin
          map={map}
          points={asked.points}
          planning={fires?.planning ?? false}
          onPress={() => {
            if (fires?.planning) fires.onUseArea(asked.points);
            else onAskArea(asked.id);
            drawing.dismissAsk();
            drawing.chooseTool('pan');
          }}
        />
      ) : null}
    </main>
  );
}
