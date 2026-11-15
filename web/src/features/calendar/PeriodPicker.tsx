import { useId, useRef, useState } from 'react';
import { useI18n } from '../../i18n/context';
import { cx } from '../../lib/cx';
import { Ph } from '../../ui/Ph';
import { PopupMenu } from '../../ui/PopupMenu';
import { Segments } from '../../ui/Segments';
import {
  monthAt,
  monthIndex,
  sameRange,
  step,
  yearOf,
  type Month,
  type MonthRange,
} from './months';
import { shortMonths } from './text';

export interface PeriodPreset extends MonthRange {
  id: string;
  /** "year" presets stay off the list: a whole year is picked in the grid. */
  kind?: string;
  label: string;
}

interface PeriodPickerProps {
  /** The chosen period, written out: "Forecast, Oct 2026 – Mar 2027". */
  label: string;
  range: MonthRange;
  /** The first and the last month that can be chosen. */
  limits: MonthRange;
  /** Months that are a forecast, not what the satellites saw. */
  forecast?: MonthRange;
  /** The record the satellites have seen, first month to the current one: a period that holds all of it has nowhere to step. */
  record?: MonthRange;
  presets: readonly PeriodPreset[];
  /** `null` is the whole record, whatever months it reaches by then. */
  onChange: (range: MonthRange | null) => void;
}

const isIn = (month: Month, range: MonthRange) =>
  monthIndex(month) >= monthIndex(range.from) && monthIndex(month) <= monthIndex(range.to);

/**
 * A ready period: a short word on the button, the whole period as its name and tip. A `note` explains the period: it
 * is the tip and the description of the button, and goes to `onNote` while the pointer or the focus is on it.
 */
function PresetChip({
  text,
  full,
  note,
  pressed,
  onClick,
  onNote,
}: {
  text: string;
  full: string;
  note?: string;
  pressed: boolean;
  onClick: () => void;
  onNote: (note: string | null) => void;
}) {
  const id = useId();
  const show = note
    ? () => {
        onNote(note);
      }
    : undefined;
  const hide = note
    ? () => {
        onNote(null);
      }
    : undefined;
  return (
    <>
      <button
        type="button"
        className="region-btn pp-chip"
        aria-label={full}
        aria-describedby={note ? id : undefined}
        title={note ?? full}
        aria-pressed={pressed}
        onClick={onClick}
        onMouseEnter={show}
        onFocus={show}
        onMouseLeave={hide}
        onBlur={hide}
      >
        {text}
      </button>
      {note ? (
        <span id={id} className="visually-hidden">
          {note}
        </span>
      ) : null}
    </>
  );
}

/** The period of the calendar: a button that says it, a menu to change it, arrows to step by its length. */
export function PeriodPicker({
  label,
  range,
  limits,
  forecast,
  record,
  presets,
  onChange,
}: PeriodPickerProps) {
  const { t, lang } = useI18n();
  const button = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  // the note of the ready period under the pointer or the focus, shown in place of the hint
  const [note, setNote] = useState<string | null>(null);
  // the grid opens on the year the period ends in
  const [year, setYear] = useState(() => yearOf(range.to));
  const [anchor, setAnchor] = useState<Month | null>(null);
  const [hover, setHover] = useState<Month | null>(null);
  // the right side shows the years of the data instead of the months of one year
  const [years, setYears] = useState(false);
  // the first year of a span of years, and the year under the pointer while the last is sought
  const [yearAnchor, setYearAnchor] = useState<number | null>(null);
  const [yearHover, setYearHover] = useState<number | null>(null);

  const monthNames = shortMonths(lang);

  // the whole record is no window to slide: a step from it would land on the one month ahead and could not come back
  const whole =
    record !== undefined &&
    monthIndex(range.from) <= monthIndex(record.from) &&
    monthIndex(range.to) >= monthIndex(record.to);
  const earlier = whole ? null : step(range, -1, limits);
  const later = whole ? null : step(range, 1, limits);
  const first = monthIndex(limits.from);
  const last = monthIndex(limits.to);
  const firstYear = yearOf(limits.from);
  const lastYear = yearOf(limits.to);

  const show = () => {
    setYear(yearOf(range.to));
    setAnchor(null);
    setHover(null);
    setYears(false);
    setYearAnchor(null);
    setYearHover(null);
    setOpen(true);
  };
  const close = () => {
    setOpen(false);
    setAnchor(null);
    setNote(null);
    setYearAnchor(null);
  };
  // January of the first year to December of the last, cut to the months of the data
  const yearsRange = (a: number, b: number): MonthRange => ({
    from: monthAt(Math.max(Math.min(a, b) * 12, first)),
    to: monthAt(Math.min(Math.max(a, b) * 12 + 11, last)),
  });
  const pick = (next: MonthRange | null) => {
    close();
    document.getElementById('pp-btn')?.focus();
    onChange(next);
  };

  // while the first month is chosen, the grid shows the span up to the one under the pointer
  const shown: MonthRange = anchor
    ? monthIndex(anchor) <= monthIndex(hover ?? anchor)
      ? { from: anchor, to: hover ?? anchor }
      : { from: hover ?? anchor, to: anchor }
    : range;
  // the same for the years: the span up to the year under the pointer, else the chosen period
  const shownYears: MonthRange =
    yearAnchor === null ? range : yearsRange(yearAnchor, yearHover ?? yearAnchor);

  const withinLimits = (index: number) => index >= first && index <= last;

  return (
    <div className="pp-bar" id="pp-bar">
      <button
        ref={button}
        type="button"
        className="pp-btn"
        id="pp-btn"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={open ? close : show}
      >
        <Ph name="calendar-blank" />
        <span id="pp-label">{label}</span>
        <Ph name="caret-down" />
      </button>
      <button
        type="button"
        className="icon-btn"
        id="pp-prev"
        aria-label={t('period.prev')}
        disabled={!earlier}
        onClick={() => {
          if (earlier) onChange(earlier);
        }}
      >
        <Ph name="caret-left" />
      </button>
      <button
        type="button"
        className="icon-btn"
        id="pp-next"
        aria-label={t('period.next')}
        disabled={!later}
        onClick={() => {
          if (later) onChange(later);
        }}
      >
        <Ph name="caret-right" />
      </button>
      <PopupMenu
        anchor={button}
        open={open}
        onClose={close}
        className="pp"
        role="dialog"
        label={t('period.label')}
        id="pp"
      >
        <div className="pp-cal">
          <div className="pp-top">
            <Segments
              label={t('period.label')}
              className="pp-mode"
              items={[
                [false, t('period.months')],
                [true, t('period.years')],
              ]}
              value={years}
              onChange={setYears}
            />
            {/* ready periods as short buttons: the full period is their name and tip */}
            <div className="pp-chips">
              {record ? (
                <PresetChip
                  text={t('period.allYears')}
                  full={t('period.titleWhole', { a: yearOf(record.from), b: yearOf(record.to) })}
                  pressed={!anchor && whole}
                  onClick={() => {
                    pick(null);
                  }}
                  onNote={setNote}
                />
              ) : null}
              {presets
                .filter((preset) => preset.kind !== 'year')
                .map((preset) => (
                  <PresetChip
                    key={preset.id}
                    text={preset.kind === 'forecast' ? t('dash.cal.forecast') : preset.label}
                    full={preset.label}
                    note={
                      preset.kind === 'forecast'
                        ? t('period.forecastNote', { period: preset.label })
                        : undefined
                    }
                    pressed={!anchor && sameRange(preset, range)}
                    onClick={() => {
                      pick({ from: preset.from, to: preset.to });
                    }}
                    onNote={setNote}
                  />
                ))}
            </div>
          </div>
          <div className="pp-yr">
            <button
              type="button"
              className="icon-btn"
              aria-label={t('period.prevYear')}
              disabled={years || year <= firstYear}
              onClick={() => {
                setYear(year - 1);
              }}
            >
              <Ph name="caret-left" />
            </button>
            <button
              type="button"
              className="pp-y"
              aria-label={t('period.chooseYear')}
              aria-pressed={years}
              onClick={() => {
                setYears(!years);
              }}
            >
              {years ? `${String(firstYear)}–${String(lastYear)}` : year}
            </button>
            <button
              type="button"
              className="icon-btn"
              aria-label={t('period.nextYear')}
              disabled={years || year >= lastYear}
              onClick={() => {
                setYear(year + 1);
              }}
            >
              <Ph name="caret-right" />
            </button>
          </div>
          {years ? (
            <>
              <div className="pp-years" role="group" aria-label={t('period.chooseYear')}>
                {Array.from({ length: lastYear - firstYear + 1 }, (_, i) => firstYear + i).map(
                  (each) => {
                    const span = yearsRange(each, each);
                    // a year counts as in the period only when all its months of the data are
                    const inside = isIn(span.from, shownYears) && isIn(span.to, shownYears);
                    return (
                      <button
                        key={each}
                        type="button"
                        className={cx(
                          'pp-m',
                          inside && 'in',
                          inside &&
                            (span.from === shownYears.from || span.to === shownYears.to) &&
                            'edge',
                          each === year && 'cur',
                        )}
                        aria-pressed={inside}
                        aria-current={each === year ? 'true' : undefined}
                        onMouseEnter={() => {
                          if (yearAnchor !== null) setYearHover(each);
                        }}
                        onClick={() => {
                          if (yearAnchor === null) {
                            setYearAnchor(each);
                            setYearHover(each);
                          } else {
                            pick(yearsRange(yearAnchor, each));
                          }
                        }}
                      >
                        {each}
                      </button>
                    );
                  },
                )}
              </div>
              <p className="pp-hint" role="status">
                {note ?? t('period.hintYears')}
              </p>
            </>
          ) : (
            <>
              <div className="pp-grid">
                {[0, 1, 2, 3].map((quarter) => {
                  const start = year * 12 + quarter * 3;
                  return [
                    <button
                      key={`q${String(quarter)}`}
                      type="button"
                      className="pp-q"
                      disabled={!withinLimits(start)}
                      onClick={() => {
                        pick({ from: monthAt(start), to: monthAt(Math.min(start + 2, last)) });
                      }}
                    >
                      {t('period.quarter')}
                      {quarter + 1}
                    </button>,
                    ...[0, 1, 2].map((offset) => {
                      const index = start + offset;
                      const month = monthAt(index);
                      const inside = isIn(month, shown);
                      const isForecast = forecast ? isIn(month, forecast) : false;
                      return (
                        <button
                          key={month}
                          type="button"
                          className={cx(
                            'pp-m',
                            inside && 'in',
                            (month === shown.from || month === shown.to) && 'edge',
                            isForecast && 'fc',
                          )}
                          disabled={!withinLimits(index)}
                          aria-pressed={inside}
                          title={isForecast ? `${month}, ${t('period.forecast')}` : month}
                          onMouseEnter={() => {
                            if (anchor) setHover(month);
                          }}
                          onClick={() => {
                            if (!anchor) {
                              setAnchor(month);
                              setHover(month);
                            } else {
                              pick(
                                monthIndex(anchor) <= index
                                  ? { from: anchor, to: month }
                                  : { from: month, to: anchor },
                              );
                            }
                          }}
                        >
                          {monthNames[((index % 12) + 12) % 12]}
                        </button>
                      );
                    }),
                  ];
                })}
              </div>
              <button
                type="button"
                className="menu-item pp-whole"
                onClick={() => {
                  pick({
                    from: monthAt(Math.max(year * 12, first)),
                    to: monthAt(Math.min(year * 12 + 11, last)),
                  });
                }}
              >
                {t('period.wholeYear', { y: year })}
              </button>
              <p className="pp-hint" role="status">
                {note ?? (anchor ? t('period.hintEnd') : t('period.hintStart'))}
              </p>
            </>
          )}
        </div>
      </PopupMenu>
    </div>
  );
}
