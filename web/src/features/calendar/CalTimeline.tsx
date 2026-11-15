import { useMemo, useState } from 'react';
import { useI18n } from '../../i18n/context';
import { useBoard } from '../board/context';
import { DayPlayer } from '../climate/DayPlayer';
import { daysByDate } from '../climate/days';
import { useDaysArea, useMonthDays } from '../climate/queries';
import { Timeline } from '../timeline/Timeline';
import { usePlayback } from '../timeline/usePlayback';
import { monthIndex } from './months';
import { useCalendar, usePicked } from './queries';
import { detectionsWord, formatCount, longMonthYear, shortMonth } from './text';

const STEP_MS = 700;
/** The months the scale shows at once. */
const SHOWN = 12;

/** The months around the one on the map on a scale of time; play walks them on into the forecast. The button to the days is there only while the map is big. */
export function CalTimeline({ onClose, big }: { onClose: () => void; big: boolean }) {
  const { t, lang } = useI18n();
  const board = useBoard();
  const series = useCalendar().data?.series;
  const picked = usePicked();
  const monthDays = useMonthDays(picked, useDaysArea(board.area)).data;
  const byDate = useMemo(() => daysByDate(monthDays), [monthDays]);
  // the day this player went down to: there the person worked the player, and the day player shows its tag at once
  const [entered, setEntered] = useState<string | null>(null);
  // the day player is left: a day picked later elsewhere starts without the tag
  if (board.day === null && entered !== null) setEntered(null);
  // a month of the line is what was counted, or what the forecast says of a month ahead
  const months = (series ?? [])
    .map((month) => ({
      month: month.month,
      ahead: month.kind === 'forecast',
      value: month.count ?? month.forecast?.median ?? null,
    }))
    .filter((cell) => cell.value !== null);
  const at = picked
    ? Math.max(
        0,
        months.findIndex((cell) => cell.month === picked),
      )
    : 0;
  const here = months[at];
  const playback = usePlayback(
    months.map((cell) => cell.month),
    at,
    STEP_MS,
    board.setPick,
  );

  // a cluster of fires is open: its hours have the place of the player
  if (board.cluster) return null;
  // a day is picked: the player shows the days of its month
  if (board.day && picked && monthDays) {
    return <DayPlayer month={picked} days={monthDays} entered={entered} />;
  }
  if (!picked || !here)
    return <section className="timeline" id="cal-tl" aria-label={t('calendar.title')} />;
  const from = Math.max(0, Math.min(months.length - SHOWN, at - 8));
  const shown = months.slice(from, from + SHOWN);
  const tallest = Math.max(1, ...shown.map((cell) => cell.value ?? 0));
  const first = shown[0];
  const edge = shown.find((cell) => cell.ahead);
  const forecast = here.ahead;

  return (
    <Timeline
      id="cal-tl"
      label={t('calendar.title')}
      from={monthIndex(first?.month ?? picked)}
      to={monthIndex(shown.at(-1)?.month ?? picked) + 1}
      bars={shown.map((cell) => ({
        at: monthIndex(cell.month) + 0.5,
        span: 1,
        height: (cell.value ?? 0) / tallest,
        pale: cell.ahead,
        label:
          cell === first || cell.month.endsWith('-01')
            ? `${shortMonth(lang, cell.month)} ${cell.month.slice(0, 4)}`
            : shortMonth(lang, cell.month),
      }))}
      now={edge ? { at: monthIndex(edge.month) } : null}
      steps={shown.map((cell) => ({ at: monthIndex(cell.month) + 0.5, value: cell.month }))}
      value={monthIndex(picked) + 0.5}
      valueLabel={longMonthYear(lang, picked)}
      valueNote={
        forecast
          ? `${formatCount(lang, here.value ?? 0, true)}, ${t('period.forecast')}`
          : `${new Intl.NumberFormat(lang).format(Math.round(here.value ?? 0))} ${detectionsWord(t, lang, here.value ?? 0)}`
      }
      playing={playback.playing}
      playLabel={playback.playing ? t('pass.pause') : t('pass.playMonths')}
      onPlay={playback.toggle}
      onSeek={(month) => {
        playback.stop();
        board.setPick(month);
      }}
      closeLabel={t('pass.close')}
      onClose={() => {
        playback.stop();
        onClose();
      }}
      level={
        // the way down to the days is of the big map: a small one has the player and its cross
        big && byDate.size > 0
          ? {
              label: t('cal.byDay'),
              onClick: () => {
                playback.stop();
                const day = [...byDate.keys()].sort()[0];
                if (!day) return;
                setEntered(day);
                board.setDay(day);
              },
            }
          : null
      }
    />
  );
}
