import type { Map as MaplibreMap } from 'maplibre-gl';
import { useMemo } from 'react';
import { useI18n } from '../../i18n/context';
import { areaId } from '../../config/context';
import { useBoard } from '../board/context';
import { useFiresList } from '../fires/queries';
import { gradientOf, type OverlayCard } from '../map/overlays';
import type { LegendKind } from './conditions';
import type { KeyRow } from './LayerKey';
import { useWeatherState, type WeatherLayer } from './context';
import { fireWinds, windCollection } from './fireWinds';
import { useFireWeather, useGridBounds, useWeatherLegend, useWindPoints } from './queries';
import { inSpan } from './time';
import { useWeatherMoment } from './useMoment';
import { unitText } from './units';
import { useWeatherLayers } from './useWeatherLayers';
import { useWindAnimation } from './useWindAnimation';
import { useWholeZoom } from './useWholeZoom';

const CARDS: readonly WeatherLayer[] = ['rain', 'dryness'];

/** Everything the weather puts on the map and its tools, from the choices made in the settings and the layers menu. */
export function useWeatherMap(
  map: MaplibreMap | null,
  enabled: boolean,
  /** The base map is the light one of lines, or a darker one. */
  lightBase: boolean,
) {
  const { t } = useI18n();
  const { wind, layers, toggleLayer, animation } = useWeatherState();
  const legend = useWeatherLegend(enabled).data;
  const available = enabled && legend?.available === true;
  const moment = useWeatherMoment();
  // the pictures and the arrows over the map have their own hours; outside them there is nothing, not a guess
  const gridHour = available && inSpan(legend.grid, moment) ? moment : null;
  const list = useFiresList().data;
  // the arrows stand at the fires of the region on the board: the weather of the others is not asked for
  const region = areaId(useBoard().area);
  const fireWeather = useFireWeather(available && wind === 'fires', {
    region: region === 'WORLD' ? null : region,
  }).data;

  const winds = useMemo(
    () =>
      enabled && wind === 'fires'
        ? fireWinds(fireWeather, legend, moment, new Set(list?.fires.map((fire) => fire.id)))
        : [],
    [enabled, wind, fireWeather, legend, moment, list],
  );
  const zoom = useWholeZoom(map);
  const points = useWindPoints(moment, zoom, wind === 'all' && gridHour !== null).data ?? null;
  const bounds = useGridBounds(available && (layers.length > 0 || animation)).data;
  const credits = available && (wind !== 'off' || layers.length > 0) ? legend.attribution : null;
  const asked = available ? layers : [];
  useWeatherLayers(map, {
    bounds,
    legend,
    layers: asked,
    hour: gridHour,
    wind: wind === 'all' && gridHour !== null ? points : null,
    fires: useMemo(
      () => windCollection(winds, (speed) => t('wx.speed', { speed: Math.round(speed) })),
      [winds, t],
    ),
    credits,
  });

  useWindAnimation(map, {
    enabled: available && animation,
    bounds,
    hour: gridHour,
    tone: lightBase ? 'dark' : 'light',
  });

  const cards = useMemo<OverlayCard[]>(
    () =>
      available
        ? CARDS.flatMap((id) => {
            const colors = legend.layers
              .find((layer) => layer.layer === id)
              ?.bands.map((band) => band.color);
            return colors
              ? [
                  {
                    id,
                    label: t(`wx.layer.${id}`),
                    gradient: gradientOf(colors),
                    on: layers.includes(id),
                  },
                ]
              : [];
          })
        : [],
    [available, legend, layers, t],
  );

  const shown = useMemo<LegendKind[]>(
    () => [
      ...(wind !== 'off' ? (['wind'] as const) : []),
      ...CARDS.filter((id) => layers.includes(id)),
    ],
    [wind, layers],
  );
  const watching = available && shown.length > 0;
  // the arrows at the fires have the hours of the fires, the pictures and the wind everywhere those of the grid
  const hourThere =
    wind === 'fires' && layers.length === 0
      ? available && inSpan(legend.fires, moment)
      : gridHour !== null;
  const rows = useMemo<KeyRow[]>(
    () =>
      shown.flatMap((id) => {
        const layer = legend?.layers.find((item) => item.layer === id);
        return layer
          ? [{ id, title: t(`wx.layer.${id}`), unit: unitText(t, layer.unit), bands: layer.bands }]
          : [];
      }),
    [shown, legend, t],
  );
  return {
    legend: available ? legend : undefined,
    cards,
    /** Turns a layer of the menu on or off. */
    toggle: (id: string) => {
      const layer = CARDS.find((item) => item === id);
      if (layer) toggleLayer(layer);
    },
    rows: watching ? rows : [],
    /** What the key says in place of its strips when the data lacks the hour. */
    missing: watching && !hourThere ? t('wx.noHour') : null,
    /** The hour to ask the server about under the pointer; null while no layer of the weather is on. */
    hoverHour: watching ? gridHour : null,
  };
}
