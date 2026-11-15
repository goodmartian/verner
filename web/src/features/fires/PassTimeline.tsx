import { useMemo } from 'react';
import { useI18n } from '../../i18n/context';
import { detectionsWord, formatCount } from '../calendar/text';
import { Timeline } from '../timeline/Timeline';
import { HOUR, dayTicks } from '../timeline/scale';
import { usePlayback } from '../timeline/usePlayback';
import { useWeatherLegend } from '../weather/queries';
import { tailHours } from '../weather/time';
import { useNowHour } from '../weather/useMoment';
import { useFiresState } from './context';
import {
  FORECAST_HOURS,
  passBars,
  passBounds,
  passSteps,
  passWalk,
  type Moment,
} from './passScale';
import { useFire, useFiresList } from './queries';
import { formatDayShort, formatPass } from './text';
import { usePlaceZone } from '../../config/usePlaceZone';

const STEP_MS = 800;
const NO_PASSES: never[] = [];

/** The satellite passes and the weather forecast after them on one scale of time: the handle moves over them, play walks them. */
export function PassTimeline() {
  const { t, lang } = useI18n();
  const state = useFiresState();
  const list = useFiresList().data;
  const detail = useFire(state.fireId, state.pass).data;
  // the forecast of the growth is made from the last pass, whichever pass is on screen
  const latest = useFire(state.fireId, null).data;
  const passes = list?.passes ?? NO_PASSES;
  const last = passes.length - 1;
  const k = state.pass ?? last;
  const here = passes[k];
  const zone = usePlaceZone(detail ?? here);
  const { clock, forecast } = state;

  const end = useWeatherLegend().data?.grid?.end;
  const now = useNowHour();
  const nowMs = Date.parse(now);
  const { from, to } = zone
    ? passBounds(passes[0]?.time, nowMs, end, zone)
    : { from: nowMs, to: nowMs };

  // the page renders often (every pointer move on the board, every query that lands); these are built when their inputs change
  const growth = detail?.summary.growth ?? null;
  const series = useMemo(
    () =>
      passes.map((pass) => {
        if (!growth) return pass.detection_count;
        return growth.find((point) => point.pass_index === pass.index)?.pass_detections ?? 0;
      }),
    [passes, growth],
  );
  const bars = useMemo(() => passBars(passes, series), [passes, series]);

  // its marks stand after the last pass
  const lastMs = passes.length > 0 ? Date.parse(passes[last]?.time ?? '') : null;
  const spread = Boolean(latest?.spread);
  const marks = useMemo(
    () =>
      spread && lastMs !== null
        ? FORECAST_HOURS.map((hours) => ({ hours, at: lastMs + hours * HOUR }))
        : [],
    [spread, lastMs],
  );

  const go = (moment: Moment) => {
    if (moment.kind === 'pass') {
      state.setPass(moment.index);
    } else if (moment.kind === 'clock') {
      state.setClock(moment.hour);
    } else {
      state.setPass(last);
      state.setForecast(moment.hours);
    }
  };
  const walk = useMemo(() => passWalk(passes, now, end), [passes, now, end]);
  const slow = useMemo(() => (end ? tailHours(now, end) : []), [now, end]);
  const hourly = useMemo(() => (end ? tailHours(now, end, 1) : []), [now, end]);
  const steps = useMemo(() => passSteps(passes, hourly, now, marks), [passes, hourly, now, marks]);
  const ticks = useMemo(
    () => (zone ? dayTicks(from, to, (day) => formatDayShort(lang, day), zone) : []),
    [from, to, lang, zone],
  );
  const markLabels = useMemo(
    () => marks.map((mark) => ({ at: mark.at, label: t('tl.hours', { h: mark.hours }) })),
    [marks, t],
  );
  const stand = clock
    ? passes.length + slow.findLastIndex((hour) => Date.parse(hour) <= Date.parse(clock))
    : k;
  const playback = usePlayback(walk, stand, STEP_MS, go);

  const moment =
    clock ??
    (forecast > 0 && lastMs !== null
      ? new Date(lastMs + forecast * HOUR).toISOString()
      : (here?.time ?? null));
  const count = series[k] ?? 0;
  // what the map shows is said only when the bar does not say it: the detections of a pass, or what is not a pass
  const note = clock
    ? t(clock === now ? 'tl.wxNow' : 'tl.wxFc')
    : forecast > 0
      ? t('tl.fcIn', { h: forecast })
      : count > 0
        ? `${formatCount(lang, count)} ${detectionsWord(t, lang, count)}`
        : undefined;

  if (!zone)
    return <section className="timeline skel" aria-busy="true" aria-label={t('pass.title')} />;
  return (
    <Timeline
      id="timeline"
      label={t('pass.title')}
      from={from}
      to={to}
      bars={bars}
      ticks={ticks}
      now={{ at: nowMs, label: t('tl.now') }}
      marks={markLabels}
      steps={steps}
      value={moment ? Date.parse(moment) : null}
      valueLabel={moment ? formatPass(lang, moment, zone) : ''}
      {...(note ? { valueNote: note } : {})}
      playing={playback.playing}
      playLabel={playback.playing ? t('pass.pause') : t('pass.play')}
      onPlay={playback.toggle}
      onSeek={(next) => {
        playback.stop();
        go(next);
      }}
      closeLabel={t('pass.close')}
      onClose={() => {
        playback.stop();
        state.setPlayer(false);
      }}
    />
  );
}
