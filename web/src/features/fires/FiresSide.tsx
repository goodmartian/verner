import { LOCALES, localName } from '../../i18n/lang';
import { areaId, useConfig } from '../../config/context';
import { WORLD } from '../calendar/areas';
import { usePlaceZone } from '../../config/usePlaceZone';
import { memo, type CSSProperties } from 'react';
import { useApiErrorText } from '../../api/useApiErrorText';
import type { FireDetail, FireSummary } from '../../api/types';
import { useI18n } from '../../i18n/context';
import type { MessageKey } from '../../i18n/en';
import { Ph } from '../../ui/Ph';
import { Tiles, type TileData } from '../../ui/Tiles';
import { useBoard } from '../board/context';
import { AreaName } from '../calendar/AreaName';
import { useRegions } from '../calendar/queries';
import { EmptyNote } from '../../ui/EmptyNote';
import { useConditions } from '../weather/useConditions';
import { useWeatherMoment } from '../weather/useMoment';
import { useAskPop } from '../../ui/AskPop';
import { detectionsWord } from '../calendar/text';
import { useFireAsk } from './useFireAsk';
import { FireGrowth } from './FireGrowth';
import { SavedPlans } from './SavedPlans';
import { useFiresState } from './context';
import { useFire, useFiresCovered, useFiresList } from './queries';
import {
  areaText,
  compass,
  factsAt,
  formatClock,
  formatPass,
  periodText,
  frontSpeed,
  whereText,
} from './text';

/** The fire as it stood at a pass: its growth point, or none when the pass is before the fire. */
function pointAt(fire: FireSummary, pass: number) {
  return fire.growth.find((point) => point.pass_index === pass);
}

/** A tile label starts with a capital, as on the calendar board; the keys are shared with running text. */
const capital = (lang: string, text: string) =>
  text.charAt(0).toLocaleUpperCase(lang) + text.slice(1);

/** One fire of the list: the place, how big it was at the pass, the bars of what each pass found. */
function FireRow({ fire, pass }: { fire: FireSummary; pass: number }) {
  const { t, lang } = useI18n();
  const state = useFiresState();
  const point = pointAt(fire, pass);
  const n = point?.detections ?? 0;
  const tallest = Math.max(1, ...fire.growth.map((item) => item.pass_detections));
  // the little chart opens the card of the fire at this pass; a press on it does not open the fire
  const zone = usePlaceZone(fire);
  const time = useFiresList().data?.passes[pass]?.time;
  const pop = useAskPop();
  const ask = useFireAsk(fire.nearest_place.name, time ? formatPass(lang, time, zone) : '');
  const bound = pop.bind(
    ask(
      fire.nearest_place.name,
      `${String(n)} ${detectionsWord(t, lang, n)}`,
      n > 0 ? areaText(t, lang, point?.area_ha ?? 0) : t('fires.noYet'),
    ),
  );
  return (
    <button
      type="button"
      className={`fire-row${n > 0 ? '' : ' empty'}${state.hovered === fire.id ? ' hot' : ''}`}
      onMouseEnter={() => {
        state.setHovered(fire.id);
      }}
      onMouseLeave={() => {
        state.setHovered(null);
      }}
      onFocus={() => {
        state.setHovered(fire.id);
      }}
      onBlur={() => {
        state.setHovered(null);
      }}
      onClick={() => {
        state.select(fire.id);
      }}
    >
      <span className="fr-name">{fire.nearest_place.name}</span>
      <span className="fr-area">
        {n > 0 ? areaText(t, lang, point?.area_ha ?? 0) : t('fires.noYet')}
      </span>
      <span className="fr-sub">{whereText(t, lang, fire.nearest_place)}</span>
      <span
        className="spark"
        aria-hidden="true"
        onClick={(event) => {
          // a press on the little chart shows the pill, and does not open the fire
          if (!('aria-haspopup' in bound)) return;
          event.stopPropagation();
          bound.onClick(event);
        }}
      >
        {fire.growth.map((item) => (
          <i
            key={item.pass_index}
            className={
              item.pass_index > pass ? 'later' : item.pass_index === pass ? 'now' : undefined
            }
            style={{ '--h': (item.pass_detections / tallest).toFixed(2) } as CSSProperties}
          />
        ))}
      </span>
      {pop.card}
    </button>
  );
}

/** The region over the map while no fire is open: on the pointer it opens the fires of the region and a way to change it. */
export function RegionChip({ onRegion }: { onRegion: () => void }) {
  const { t, lang } = useI18n();
  const state = useFiresState();
  const list = useFiresList().data;
  const covered = useFiresCovered();
  if (state.fireId !== null) return null;
  const archive = covered === false;
  const fires = list?.available && !archive ? list.fires : [];
  const pass = state.pass ?? (list ? list.passes.length - 1 : 0);
  const first = list?.days[0];
  const last = list?.days.at(-1);
  return (
    <span className="ov ov-plain">
      <button type="button" className="ov-label">
        <AreaName />
      </button>
      <div className="ov-pop" role="dialog">
        <p className="ov-pop-t">
          <AreaName />
        </p>
        {archive || !first || !last ? null : (
          <p className="ov-pop-s">
            {t('fires.count', { n: fires.length })}, {periodText(t, lang, first, last)}
          </p>
        )}
        {archive ? null : (
          <ol className="fires ov-fires">
            {fires.map((fire) => (
              <li key={fire.id}>
                <FireRow fire={fire} pass={pass} />
              </li>
            ))}
          </ol>
        )}
        <button type="button" className="btn btn-secondary ov-region" onClick={onRegion}>
          <Ph name="map-pin" />
          <span>{t('fires.change')}</span>
        </button>
      </div>
    </span>
  );
}

/** The list of the last days' fires: the nearest place, how big, the same at every pass as a row of bars. */
interface FiresListProps {
  /** Opens the choice of the region. */
  onRegion: () => void;
  /** Opens the calendar, for a region that has no live fires. */
  onCalendar: () => void;
}

export const FiresList = memo(function FiresList({ onRegion, onCalendar }: FiresListProps) {
  const { t, lang } = useI18n();
  const errorText = useApiErrorText();
  const { area, setArea } = useBoard();
  const config = useConfig();
  const covered = useFiresCovered();
  const archive = covered === false;
  const state = useFiresState();
  const list = useFiresList();
  const data = list.data;
  const zone = usePlaceZone();
  const k = state.pass ?? (data ? data.passes.length - 1 : 0);
  const fires = data?.available && !archive ? data.fires : [];
  const first = data?.days[0];
  const last = data?.days.at(-1);
  // a place with no zone of its own, the world, has no local time to tell
  const updated = data?.updated_at ? formatClock(lang, data.updated_at, zone) : '';
  // the ways out of a list with no fires: the statistics of this area, the area burning most now, the example
  const regions = useRegions().data?.regions;
  const here = areaId(area);
  const burning = regions
    ?.filter((item) => item.fires_now > 0 && item.id !== here)
    .reduce<(typeof regions)[number] | null>(
      (top, item) => (top && top.fires_now >= item.fires_now ? top : item),
      null,
    );
  const toCalendar = { label: t('fires.openCal'), run: onCalendar };
  const toBurning = burning
    ? {
        label: `${localName(burning.names, lang)}, ${t('fires.count', { n: burning.fires_now })}`,
        run: () => {
          setArea(burning.id);
        },
      }
    : null;
  const toExample = {
    label: t('fires.example'),
    run: () => {
      state.setDemo(true);
    },
  };

  return (
    <>
      {covered === null ? <span className="skel" aria-busy="true" /> : null}
      <div className="list-head">
        <h1 id="h-list">{t('fires.title')}</h1>
        <span className="count" id="count">
          {fires.length > 0 && !archive ? fires.length : ''}
        </span>
      </div>
      <div className="region-line">
        <button type="button" className="region-btn" id="region-btn" onClick={onRegion}>
          <Ph name="map-pin" />
          <span id="region-name">
            <AreaName />
          </span>
          <Ph name="caret-down" />
        </button>
        {first && last && !archive ? (
          <span className="period">
            {periodText(t, lang, first, last)}
            {updated && !state.demo ? (
              <>
                {' · '}
                <span className="stamp">{t('fires.updated', { time: updated })}</span>
              </>
            ) : null}
          </span>
        ) : null}
      </div>
      {areaId(area) === WORLD && fires.length > 0 ? (
        <p className="period">{t('fires.worldTop', { n: fires.length })}</p>
      ) : null}
      <ol className="fires" id="fires">
        {fires.map((fire) => (
          <li key={fire.id}>
            <FireRow fire={fire} pass={k} />
          </li>
        ))}
        {archive ? (
          <EmptyNote
            as="li"
            wide
            icon="circle-dashed"
            text={t('fires.notCovered', {
              countries: (config?.countries ?? [])
                .map((item) => localName(item.names, lang))
                .join(', '),
            })}
            actions={[toCalendar]}
          />
        ) : list.isError ? (
          <EmptyNote
            as="li"
            wide
            icon="warning"
            text={errorText(list.error)}
            actions={[toCalendar]}
          />
        ) : data && fires.length === 0 ? (
          <EmptyNote
            as="li"
            wide
            icon={data.available || state.demo ? 'check-circle' : 'warning'}
            text={t(
              data.available || state.demo
                ? config?.countries.some((item) => item.id === areaId(area))
                  ? 'fires.empty'
                  : 'fires.regionEmpty'
                : 'fires.unavailable',
            )}
            actions={
              state.demo
                ? [toCalendar]
                : // a quiet region leads to the one burning most now; the example stands in when nothing burns or nothing is loaded
                  [(data.available ? toBurning : null) ?? toExample, toCalendar]
            }
          />
        ) : null}
      </ol>
      <SavedPlans />
      {state.demo ? (
        <>
          <p className="period">{t('fires.exampleNote')}</p>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              state.setDemo(false);
            }}
          >
            <span>{t('fires.live')}</span>
          </button>
        </>
      ) : null}
    </>
  );
});

/** What the fire at a pass says in the four numbers, the conditions as three tiles. */
export function FireNumbers({ detail }: { detail: FireDetail }) {
  const { t, lang } = useI18n();
  const zone = usePlaceZone(detail);
  const facts = factsAt(detail.summary, detail.pass_index);
  const number = new Intl.NumberFormat(lang === 'en' ? 'en-GB' : lang, {
    maximumFractionDigits: 0,
  });
  const conditions = useConditions(detail);
  const moment = useWeatherMoment();
  const tenths = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
  const front = frontSpeed(t, lang, detail.spread);
  // a tile opens the card of its figure: the number as written on the tile, for the pass on the map or, for the weather, the hour it is for
  const place = detail.summary.nearest_place.name;
  const figureAsk = useFireAsk(place, formatPass(lang, detail.pass_time, zone));
  const weatherAsk = useFireAsk(place, formatPass(lang, moment, zone));
  const figures: TileData[] = [
    {
      key: 'area',
      label: t('fire.area'),
      big: facts.detections > 0 ? areaText(t, lang, facts.areaHa) : '0',
    },
    { key: 'detections', label: t('fire.detections'), big: number.format(facts.detections) },
    {
      key: 'power',
      label: t('fire.power'),
      sub: t('fire.strip.pass'),
      big: facts.detections > 0 ? t('fire.mw', { n: number.format(facts.powerMw) }) : '0',
    },
    {
      key: 'last',
      label: t('fire.last'),
      big: zone ? (
        new Intl.DateTimeFormat(LOCALES[lang], {
          hour: '2-digit',
          minute: '2-digit',
          timeZone: zone,
        }).format(new Date(detail.summary.last_detection_at))
      ) : (
        <span className="skel" aria-busy="true" />
      ),
      sub: zone
        ? new Intl.DateTimeFormat(LOCALES[lang], {
            day: 'numeric',
            month: 'short',
            timeZone: zone,
            timeZoneName: 'shortOffset',
          }).format(new Date(detail.summary.last_detection_at))
        : undefined,
    },
  ];
  const none = t('wx.none');
  const wind =
    conditions.speed !== null && conditions.from !== null ? (
      <>
        <Ph
          name="arrow-up"
          style={{ transform: `rotate(${String(Math.round((conditions.from + 180) % 360))}deg)` }}
        />
        {t('wx.speed', { speed: number.format(conditions.speed) })}
      </>
    ) : (
      none
    );
  const weather: TileData[] = [
    {
      key: 'wind',
      label: t('wx.layer.wind'),
      sub:
        conditions.from !== null
          ? t(`dirFrom.${String(compass(conditions.from / 45))}` as MessageKey)
          : undefined,
      big: wind,
    },
    {
      key: 'gusts',
      label: capital(lang, t('wx.gusts')),
      big:
        conditions.gust !== null ? t('wx.speed', { speed: number.format(conditions.gust) }) : none,
    },
    {
      key: 'precip',
      label: capital(lang, t('wx.precip')),
      big: conditions.precip !== null ? t('wx.mmh', { n: tenths.format(conditions.precip) }) : none,
    },
    {
      key: 'dryness',
      label:
        conditions.hdw !== null
          ? capital(lang, t('wx.dryHdw', { n: number.format(conditions.hdw) }))
          : t('wx.layer.dryness'),
      big: conditions.dryness?.name ?? none,
    },
    {
      key: 'front',
      label: capital(lang, t('fire.ros')),
      ...(detail.spread?.rate_source === 'weather' ? { sub: t('fire.rosFrom') } : {}),
      big: front.value,
    },
    {
      key: 'air',
      label: capital(lang, t('fire.air')),
      big:
        conditions.temperature !== null && conditions.humidity !== null
          ? `${number.format(conditions.temperature)} °C, ${number.format(conditions.humidity)}%`
          : none,
    },
  ];
  const said: Record<string, string | undefined> = {
    last: zone ? formatPass(lang, detail.summary.last_detection_at, zone) : undefined,
    wind:
      conditions.speed !== null
        ? t('wx.speed', { speed: number.format(conditions.speed) })
        : undefined,
  };
  const asked = (tiles: TileData[], ask: ReturnType<typeof useFireAsk>) =>
    tiles.map((tile) => {
      const value = said[tile.key] ?? (typeof tile.big === 'string' ? tile.big : undefined);
      return value === undefined ? tile : { ...tile, ask: ask(tile.label, value, tile.sub) };
    });
  return (
    <>
      <Tiles items={asked(figures, figureAsk)} />
      <section className="block" aria-labelledby="h-wx">
        <h2 id="h-wx">{t('fire.conditions')}</h2>
        <Tiles items={asked(weather, weatherAsk)} id="wx-row" />
        <p className="wx-src">{t('fire.wxAt', { time: formatPass(lang, moment, zone) })}</p>
        {detail.weather?.source === 'grid' ? <p className="wx-src">{t('wx.grid')}</p> : null}
      </section>
    </>
  );
}

/** The chosen fire: the way back, its name and place, then the numbers; on a wide screen the stylesheet leaves only the numbers. */
export function FireView({ onPlan }: { onPlan: () => void }) {
  const { t, lang } = useI18n();
  const errorText = useApiErrorText();
  const state = useFiresState();
  const open = useFire(state.fireId, state.pass);
  const detail = state.fireId ? open.data : undefined;
  return (
    <>
      <button
        type="button"
        className="btn back"
        id="back"
        onClick={() => {
          state.select(null);
        }}
      >
        <Ph name="caret-left" />
        <span>{t('fire.back')}</span>
      </button>
      {detail ? (
        <>
          <div className="fire-head">
            <h1 id="fd-name">{detail.summary.nearest_place.name}</h1>
            <p className="sub" id="fd-sub">
              {whereText(t, lang, detail.summary.nearest_place)}
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary plan-open"
            id="plan-open"
            onClick={onPlan}
          >
            <Ph name="path" />
            <span>{t('plan.title')}</span>
          </button>
          <FireNumbers detail={detail} />
          <FireGrowth detail={detail} />
        </>
      ) : open.isError ? (
        <p className="note">{errorText(open.error)}</p>
      ) : null}
    </>
  );
}
