import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import { useBoard } from '../board/context';
import { useWidgetActions } from '../chat/actions';
import { daysByDate } from '../climate/days';
import { formatDayShort } from '../fires/text';
import { useClimateArea, useClimateMonth, useDaysArea, useMonthDays } from '../climate/queries';
import { monthLine } from '../climate/monthLine';
import { AreaName } from './AreaName';
import { yearOf } from './months';
import { useCalendar, useMonth, usePicked } from './queries';
import { detectionsWord, formatChange, formatCount, longMonthYear } from './text';
import { Segments } from '../../ui/Segments';

/** The month on the map as a strip along its top: the numbers in a line, the years side by side, and the question. */
export function MonthStrip() {
  const { t, lang } = useI18n();
  const board = useBoard();
  const actions = useWidgetActions();
  const month = usePicked();
  const detail = useMonth().data;
  // a month still running is read against the usual of the same dates
  const running = useCalendar().data?.series.find((item) => item.month === month);
  const normal = running?.partial ? running.median : (detail?.normal ?? null);
  const weather = useClimateMonth(month, useClimateArea(board.area)).data;
  const monthDays = useMonthDays(month, useDaysArea(board.area)).data;
  if (!month) return null;
  const line = monthLine(t, lang, weather);
  const day = board.day;
  const dayRow = day ? daysByDate(monthDays).get(day) : undefined;

  const forecast = detail?.kind === 'forecast';
  const cell = (value: string, label: string, extra?: boolean) => (
    <span className={`fs-i${extra ? ' fs-x' : ''}`}>
      <b>{value}</b>
      <small>{label}</small>
    </span>
  );
  const against = (value: number, normal: number) =>
    normal > 0 ? formatChange(lang, value / normal) : '—';
  const years = [...board.years].sort();
  const own = yearOf(month);

  return (
    <div className="fire-strip month-strip" aria-live="polite">
      <span className="fs-name">
        <b>{day ? formatDayShort(lang, day) : longMonthYear(lang, month)}</b>
        <small>
          <AreaName />
        </small>
      </span>
      {day ? (
        dayRow ? (
          <>
            {cell(formatCount(lang, dayRow.detections), detectionsWord(t, lang, dayRow.detections))}
            {cell(formatCount(lang, dayRow.clusters), t('cal.clusters'))}
          </>
        ) : monthDays !== undefined ? (
          // "no data" only once the days of the month have come
          cell('—', t('strip.noData'))
        ) : null
      ) : detail && detail.value !== null ? (
        forecast ? (
          <>
            {cell(formatCount(lang, detail.value, true), t('period.forecast'))}
            {detail.forecast
              ? cell(
                  `${formatCount(lang, detail.forecast.low)}–${formatCount(lang, detail.forecast.high)}`,
                  t('legend.range'),
                  true,
                )
              : null}
            {normal !== null ? cell(formatCount(lang, normal), t('legend.normal'), true) : null}
            {normal !== null
              ? cell(against(detail.value, normal), t('strip.vsNormal'), true)
              : null}
          </>
        ) : (
          <>
            {cell(formatCount(lang, detail.value), detectionsWord(t, lang, detail.value))}
            {normal !== null ? cell(formatCount(lang, normal), t('legend.normal'), true) : null}
            {normal !== null
              ? cell(against(detail.value, normal), t('strip.vsNormal'), true)
              : null}
          </>
        )
      ) : detail ? (
        cell('—', t('strip.noData'))
      ) : null}
      {!day && !forecast && years.length > 1 ? (
        <Segments
          label={t('compare.title')}
          items={years.map((year) => [year, String(year)] as const)}
          value={own}
          onChange={(year) => {
            board.setPick(`${String(year)}-${month.slice(5)}`);
          }}
        />
      ) : null}
      {line && !day ? <p className="ms-wx">{line}</p> : null}
      {actions ? (
        <button
          type="button"
          className="btn btn-secondary ms-ask"
          aria-label={t('chat.askAi')}
          title={t('chat.askAi')}
          onClick={() => {
            actions.addMonth(month);
          }}
        >
          <Ph name="sparkle" />
          <span>{t('chat.askAi')}</span>
        </button>
      ) : null}
    </div>
  );
}
