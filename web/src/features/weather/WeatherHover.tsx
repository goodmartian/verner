import type { Map as MaplibreMap, MapMouseEvent } from 'maplibre-gl';
import { useEffect, useState } from 'react';
import type { WeatherAt, WeatherLegend } from '../../api/types';
import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import { bandOf } from './conditions';
import { fetchWeatherAt } from './queries';
import { placeTip, type Box } from './tipPlace';

const DELAY_MS = 150;
// what the card needs at most, to keep it inside the map
const WIDTH = 270;
const HEIGHT = 56;
// what the card gives way to: the things that stand over the map
const OVER = '.fire-strip, .cluster-strip, .month-strip, .timeline, .tools, .wx-key, .ov';

/** The boxes of what stands over the map, in the coordinates of the map. */
function overMap(container: HTMLElement): Box[] {
  const origin = container.getBoundingClientRect();
  return [...document.querySelectorAll(OVER)].flatMap((element) => {
    const box = element.getBoundingClientRect();
    return box.width === 0 && box.height === 0
      ? []
      : [
          {
            left: box.left - origin.left,
            top: box.top - origin.top,
            right: box.right - origin.left,
            bottom: box.bottom - origin.top,
          },
        ];
  });
}

interface Tip {
  x: number;
  y: number;
  hour: string;
  at: WeatherAt;
}

interface WeatherHoverProps {
  map: MaplibreMap | null;
  /** The hour the weather is asked for; null when there is none, or when no weather layer is on. */
  hour: string | null;
  legend: WeatherLegend | undefined;
}

/** The values under the pointer: the wind, rain, dryness and air of the spot, asked of the server a moment after the pointer rests. */
export function WeatherHover({ map, hour, legend }: WeatherHoverProps) {
  const { t, lang } = useI18n();
  const [tip, setTip] = useState<Tip | null>(null);

  useEffect(() => {
    if (!map || !hour) return;
    let timer = 0;
    let pending: AbortController | undefined;
    const stop = () => {
      window.clearTimeout(timer);
      pending?.abort();
    };
    const ask = (event: MapMouseEvent, delay: number) => {
      stop();
      const { lng, lat } = event.lngLat;
      const { x, y } = event.point;
      timer = window.setTimeout(() => {
        const mine = new AbortController();
        pending = mine;
        fetchWeatherAt(lng, lat, hour, mine.signal)
          .then((at) => {
            if (!mine.signal.aborted) setTip(at ? { x, y, hour, at } : null);
          })
          .catch(() => {
            if (!mine.signal.aborted) setTip(null);
          });
      }, delay);
    };
    const move = (event: MapMouseEvent) => {
      ask(event, DELAY_MS);
    };
    // a touch has no pointer to rest: the tap asks at once
    const tap = (event: MapMouseEvent) => {
      ask(event, 0);
    };
    const leave = () => {
      stop();
      setTip(null);
    };
    map.on('mousemove', move);
    map.on('click', tap);
    map.on('mouseout', leave);
    map.on('movestart', leave);
    return () => {
      stop();
      map.off('mousemove', move);
      map.off('click', tap);
      map.off('mouseout', leave);
      map.off('movestart', leave);
    };
  }, [map, hour]);

  if (!map || tip?.hour !== hour) return null;
  const { at } = tip;
  const number = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
  // the wind is whole km/h, as in the card of a fire
  const whole = new Intl.NumberFormat(lang, { maximumFractionDigits: 0 });
  const container = map.getContainer();
  const place = placeTip(
    tip,
    { width: WIDTH, height: HEIGHT },
    { width: container.clientWidth, height: container.clientHeight },
    overMap(container),
  );
  const dryness = bandOf(legend, 'dryness', at.dryness.category, lang);
  return (
    <div
      className="wx-tip"
      role="status"
      aria-label={t('wx.tip')}
      style={{
        left: place.left,
        top: place.top,
        transform: `translate(${place.flipX ? '-100%' : '0'}, ${place.flipY ? '-100%' : '0'})`,
      }}
    >
      <div>
        <Ph
          name="arrow-up"
          fill
          className="wx-arrow"
          style={{
            transform: `rotate(${String(Math.round((at.wind.from_deg + 180) % 360))}deg)`,
            color: at.wind.color,
          }}
        />
        {t('wx.speed', { speed: whole.format(at.wind.speed_kmh) })}, {t('wx.gusts')}{' '}
        {whole.format(at.wind.gust_kmh)} · {t('wx.mmh', { n: number.format(at.rain.mm_per_h) })}
      </div>
      <div>
        {t('wx.layer.dryness')}: {dryness?.name ?? '—'} · {number.format(at.temperature_c)} °C,{' '}
        {number.format(at.humidity_pct)} %
      </div>
    </div>
  );
}
