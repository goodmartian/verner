import { useMemo, useState } from 'react';
import { useI18n } from '../../i18n/context';
import { useBoard } from '../board/context';
import { dayFigures } from '../calendar/text';
import { formatDayShort } from '../fires/text';
import { Timeline } from '../timeline/Timeline';
import { DAY } from '../timeline/scale';
import { usePlayback } from '../timeline/usePlayback';
import { useCalendar } from '../calendar/queries';
import { daysByDate, monthDates, wholeDays } from './days';
import type { MonthDays } from '../../api/types';

const STEP_MS = 700;

interface DayPlayerProps {
  month: string;
  days: MonthDays;
  /** The day the months player went down to: the person worked the player, so its tag shows at once. */
  entered?: string | null;
}

const startOf = (date: string) => Date.parse(`${date}T00:00:00Z`);

/** The days of the month on a scale of time, the player of the calendar one level down: play walks the days that had fires. */
export function DayPlayer({ month, days, entered }: DayPlayerProps) {
  const { t, lang } = useI18n();
  const board = useBoard();
  const { day, setDay } = board;
  const byDate = useMemo(() => daysByDate(days), [days]);
  const dates = useMemo(() => monthDates(month), [month]);
  const tallest = Math.max(1, ...[...byDate.values()].map((row) => row.detections));
  const here = day ? byDate.get(day) : undefined;
  const monthCount = useCalendar().data?.series.find((item) => item.month === month)?.count;
  const whole = useMemo(() => wholeDays(days, monthCount), [days, monthCount]);
  const from = startOf(dates[0] ?? `${month}-01`);

  // the day the player itself went to: a day picked elsewhere (a bar of the days card) keeps the handle without its tag,
  // which comes once the person plays or seeks here
  const [mine, setMine] = useState<string | null>(entered ?? null);
  const go = (date: string | null) => {
    setMine(date);
    setDay(date);
  };
  const walk = [...byDate.keys()].sort();
  const playback = usePlayback(walk, day ? walk.indexOf(day) : -1, STEP_MS, go);

  return (
    <Timeline
      id="cal-tl"
      label={t('calendar.title')}
      from={from}
      to={from + dates.length * DAY}
      bars={dates.flatMap((date) => {
        const row = byDate.get(date);
        return row
          ? [{ at: startOf(date) + DAY / 2, span: DAY, height: row.detections / tallest }]
          : [];
      })}
      ticks={dates
        .filter((_, index) => index % 7 === 0)
        .map((date) => ({
          at: startOf(date),
          label: date.endsWith('-01') ? formatDayShort(lang, date) : String(Number(date.slice(8))),
        }))}
      steps={walk.map((date) => ({ at: startOf(date) + DAY / 2, value: date }))}
      value={day ? startOf(day) + DAY / 2 : null}
      valueLabel={day ? formatDayShort(lang, day) : ''}
      {...(here
        ? {
            // the same whole numbers as the bars of the days card, so the two never differ by one
            valueNote: dayFigures(
              t,
              lang,
              whole.get(here.date) ?? here.detections,
              here.clusters,
            ).join(' · '),
          }
        : {})}
      tag={playback.playing || (day !== null && day === mine)}
      playing={playback.playing}
      playLabel={playback.playing ? t('pass.pause') : t('cal.playDays')}
      onPlay={() => {
        // the day it stands on is now the player's own: its tag shows from the first press
        setMine(day);
        playback.toggle();
      }}
      onSeek={(date) => {
        playback.stop();
        go(date);
      }}
      // the cross takes the player one level up, back to the months: the day goes, the month stays
      closeLabel={t('cal.allDays')}
      onClose={() => {
        playback.stop();
        go(null);
      }}
    />
  );
}
