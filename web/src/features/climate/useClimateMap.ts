import { localName } from '../../i18n/lang';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useMemo } from 'react';
import { useI18n } from '../../i18n/context';
import { useBoard } from '../board/context';
import type { EmptyAction } from '../../ui/EmptyNote';
import { usePicked } from '../calendar/queries';
import { longMonthYear } from '../calendar/text';
import { cornersOf, useImageLayers, type Picture } from '../map/useImageLayers';
import { useMapCredits } from '../map/useMapCredits';
import { gradientOf, type OverlayCard } from '../map/overlays';
import { useWeatherState } from '../weather/context';
import type { KeyRow } from '../weather/LayerKey';
import { useClimateArea, useClimateBounds, useClimateLegend } from './queries';

/** The layers go under the cells and the outline of the calendar. */
const UNDER = 'calendar-outline';

const within = (
  value: string | null,
  first: string | null | undefined,
  last: string | null | undefined,
) => value !== null && !!first && !!last && value >= first && value <= last;

function address(layer: string, month: string): string {
  const url = new URL('/api/climate/grid.png', window.location.origin);
  url.search = new URLSearchParams({ layer, month }).toString();
  return url.href;
}

/**
 * The weather of the month on the map of the calendar: its layers as tiles among the overlays, with their key.
 * Nothing while the server has none yet.
 */
export function useClimateMap(map: MaplibreMap | null, enabled: boolean) {
  const { lang } = useI18n();
  const board = useBoard();
  const month = usePicked();
  const area = useClimateArea(board.area);
  const legendQuery = useClimateLegend(enabled && area !== null);
  const legend = legendQuery.data;
  const { climate: on, toggleClimate } = useWeatherState();

  const available = enabled && area !== null && legend?.available === true;
  // a month is covered from the first to the last month of the weather, and not by the forecast ahead of it
  const covered =
    available && board.day === null && within(month, legend.first_month, legend.last_month);
  const layers = useMemo(() => (covered ? legend.month_layers : []), [covered, legend]);

  const bounds = useClimateBounds(available).data;
  const pictures = useMemo<Picture[]>(
    () =>
      layers.map((layer) => ({
        id: layer.layer,
        url: month && on.includes(`month:${layer.layer}`) ? address(layer.layer, month) : null,
        opacity: layer.opacity,
      })),
    [layers, month, on],
  );
  const corners = useMemo(() => (bounds ? cornersOf(bounds.coordinates) : null), [bounds]);
  useImageLayers(map, 'climate-month', corners, pictures, UNDER);

  const shown = useMemo(
    () => layers.filter((layer) => on.includes(`month:${layer.layer}`)),
    [layers, on],
  );
  useMapCredits(map, 'climate-credits', shown.length > 0 ? (legend?.attribution ?? null) : null);

  const cards = useMemo<OverlayCard[]>(
    () =>
      layers.map((layer) => ({
        id: `month:${layer.layer}`,
        label: localName(layer.name, lang),
        gradient: gradientOf(layer.bands.map((band) => band.color)),
        on: on.includes(`month:${layer.layer}`),
      })),
    [layers, lang, on],
  );
  const rows = useMemo<KeyRow[]>(
    () =>
      shown.map((layer) => ({
        id: layer.layer,
        title: localName(layer.name, lang),
        unit: layer.unit,
        bands: layer.bands,
      })),
    [shown, lang],
  );

  // the server has no weather of the months yet: the menu says so, and does not leave the item out
  const pending = enabled && area !== null && legendQuery.isSuccess && legend?.available !== true;
  // the weather of the months exists, but not for this month: that is an answer, not a wait
  const empty = available && board.day === null && month !== null && !covered;
  // past the last month of the weather (the running month is, until it is published): the way to that last month
  const last = legend?.last_month;
  const latest: EmptyAction | null =
    empty && last && month > last
      ? {
          label: longMonthYear(lang, last),
          run: () => {
            board.setPick(last);
          },
        }
      : null;
  return { cards, rows, toggle: toggleClimate, pending, empty, latest };
}
