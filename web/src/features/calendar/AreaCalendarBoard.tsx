import type { Ref } from 'react';
import { ApiError } from '../../api/client';
import { useApiErrorText } from '../../api/useApiErrorText';
import { useI18n } from '../../i18n/context';
import { EmptyNote } from '../../ui/EmptyNote';
import { Ph } from '../../ui/Ph';
import { useConfig } from '../../config/context';
import { useBoard } from '../board/context';
import { ExportButton } from './AreaActions';
import { AreaName } from './AreaName';
import { BoardSkeleton } from './BoardSkeleton';
import { CalDash } from './CalDash';
import { PeriodPicker } from './PeriodPicker';
import { yearOf, type MonthRange } from './months';
import { useCalendar, useRange, useRecord } from './queries';
import { longMonthYear, periodTitle } from './text';
import styles from './AreaCalendarBoard.module.css';

export function AreaCalendarBoard({
  slotRef,
  onRegion,
}: {
  slotRef: Ref<HTMLDivElement>;
  onRegion: () => void;
}) {
  const { t, lang } = useI18n();
  const board = useBoard();
  const query = useCalendar();
  const data = query.isError ? undefined : query.data;
  const stale = query.isPlaceholderData;
  // before the first answer there is nothing to say yet: the area comes with the config, and the calendar after it;
  // "no data" is said only when the config has come and gave no area to ask about
  const config = useConfig();
  const waiting = query.isPending && (board.area !== null || config === null);
  const { range, limits } = useRange();
  const errorText = useApiErrorText();
  const picked =
    board.pick ??
    data?.series.filter((point) => point.count !== null).at(-1)?.month ??
    data?.series[0]?.month ??
    null;
  // the record the satellites have seen, not the years the picker can reach: the whole of it is named in words
  const record = data ? { from: data.first_month, to: data.current_month.month } : undefined;
  const forecastPreset = data?.presets.find((preset) => preset.kind === 'forecast');
  const context = (whole: MonthRange) => ({
    forecast: forecastPreset
      ? { from: forecastPreset.first_month, to: forecastPreset.last_month }
      : null,
    record: record ?? whole,
  });
  const title =
    range && limits ? periodTitle(t, lang, range, context(limits)) : t('calendar.title');
  // the whole record answers whatever the period: the way out of a period it has nothing for
  const whole = useRecord().data;
  const error = query.error instanceof ApiError ? query.error : null;
  const toWhole = whole
    ? [
        {
          label: t('period.titleWhole', {
            a: yearOf(whole.first_month),
            b: yearOf(whole.current_month.month),
          }),
          run: () => {
            board.setRange(null);
          },
        },
        {
          label: longMonthYear(lang, whole.current_month.month),
          run: () => {
            board.setRange({ from: whole.current_month.month, to: whole.current_month.month });
          },
        },
      ]
    : [];
  const pickArea = { label: t('fires.change'), run: onRegion };
  // a period the area has no months for, an area of sea, or a failure that asking again may mend
  const failure =
    error?.code === 'invalid_period' && toWhole.length > 0 ? (
      <EmptyNote wide icon="calendar-blank" text={t('empty.period')} actions={toWhole} />
    ) : error?.code === 'no_land' ? (
      <EmptyNote wide icon="map-pin-area" text={t('empty.noLand')} actions={[pickArea]} />
    ) : error?.code === 'invalid_area' ? (
      // an outline the service cannot take (across the 180th meridian, crossing itself) is not mended by asking again
      <EmptyNote wide icon="warning" text={errorText(error)} actions={[pickArea]} />
    ) : (
      <EmptyNote
        wide
        icon="warning"
        text={error?.status === 503 ? t('area.unavailable') : errorText(query.error)}
        actions={[
          {
            label: t('chat.retry'),
            run: () => {
              if (!query.isFetching) void query.refetch();
            },
          },
        ]}
      />
    );
  // nothing seen in all the years: the figures are true, and another area is the way on
  const never =
    whole !== undefined &&
    whole.series.every((point) => !point.count) &&
    !whole.current_month.count;
  // the period of the board and its file: on the board they stay in view with the bar of sections
  const tools = (
    <>
      {range && limits ? (
        <PeriodPicker
          label={title}
          range={range}
          limits={limits}
          record={record}
          presets={(data?.presets ?? []).map((preset) => ({
            id: preset.id,
            kind: preset.kind,
            from: preset.first_month,
            to: preset.last_month,
            label: periodTitle(
              t,
              lang,
              { from: preset.first_month, to: preset.last_month },
              context(limits),
            ),
          }))}
          onChange={board.setRange}
        />
      ) : null}
      {/* the file is the area and the period of the board, not of one card */}
      {data ? <ExportButton /> : null}
    </>
  );
  return (
    <>
      <div className="cal-head">
        <h1 id="h-cal">{t('calendar.title')}</h1>
        <button
          type="button"
          className="region-btn"
          id="cal-area"
          aria-haspopup="dialog"
          onClick={onRegion}
        >
          <Ph name="map-pin" />
          <span id="cal-area-name">
            <AreaName />
          </span>
          <Ph name="caret-down" />
        </button>
      </div>
      <div className="cal-slot" id="cal-slot" aria-hidden="true" ref={slotRef} data-map-slot />
      {/* the board of the period or area before stays, dimmed, until the answer for the new one comes */}
      <div
        className={`cal-body ${styles.body}`}
        aria-busy={stale || undefined}
        data-stale={stale || undefined}
        // the skeleton is cut at the bottom of the board: nothing to scroll to while it shows
        data-skeleton={(!data && !query.isError && waiting) || undefined}
      >
        {/* without the board (it is loading, or failed) the period keeps the top row to itself */}
        {/* the skeleton has the bar of the real board, with the period in it */}
        {data || waiting ? null : <div className={styles.top}>{tools}</div>}
        {query.isError ? (
          failure
        ) : data ? (
          <CalDash
            data={data}
            picked={picked}
            onPick={board.setPick}
            tools={tools}
            notice={never ? <EmptyNote text={t('empty.never')} actions={[pickArea]} /> : null}
          />
        ) : waiting ? (
          <BoardSkeleton tools={tools} label={t('calendar.loading')} />
        ) : (
          <EmptyNote wide icon="circle-dashed" text={t('card.noData')} actions={[pickArea]} />
        )}
      </div>
    </>
  );
}
