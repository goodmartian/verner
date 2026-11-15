import { usePlaceZone } from '../../config/usePlaceZone';
import { useEffect, useState } from 'react';
import { useI18n } from '../../i18n/context';
import { Ph, type PhName } from '../../ui/Ph';
import type { PlanTurn } from '../chat/useChat';
import { MAX_CREWS, useFiresState, type Hours } from './context';
import { crewsText, planClock, planReport, planSteps } from './planText';
import { useShownFire } from './usePlan';
import { Segments } from '../../ui/Segments';

const HOURS: readonly Hours[] = [1, 3, 6];

/** How many marks of a kind are near the open fire, as the plan counts them. */
export function useMarkCounts() {
  const { brief } = useFiresState();
  return {
    entries: brief.marks.filter((mark) => mark.kind === 'entry').length,
    hots: brief.marks.filter((mark) => mark.kind === 'hot').length,
  };
}

/** Plan mode over the field: what the plan is for and the marks put on the map, each with a way to take it off. */
export function PlanChips() {
  const { t } = useI18n();
  const fires = useFiresState();
  const detail = useShownFire();
  const { entries, hots } = useMarkCounts();
  const chip = (icon: PhName, text: string, label: string, onRemove: () => void, own = '') => (
    <span className={`att ${own}`} title={text}>
      <Ph name={icon} />
      <span>{text}</span>
      <button type="button" className="icon-btn" aria-label={label} onClick={onRemove}>
        <Ph name="x" />
      </button>
    </span>
  );
  return (
    <div className="pm-chips" id="pm">
      {chip(
        'path',
        t('pl.planMode', { n: detail?.summary.nearest_place.name ?? '' }),
        t('pl.cancel'),
        () => {
          fires.setPlanning(false);
        },
        'pm-chip',
      )}
      {entries > 0
        ? chip('sign-in', t('pl.entries', { n: entries }), t('pl.remove'), () => {
            fires.clearMarks('entry');
          })
        : null}
      {hots > 0
        ? chip('target', t('pl.hots', { n: hots }), t('pl.remove'), () => {
            fires.clearMarks('hot');
          })
        : null}
      {fires.brief.area
        ? chip('polygon', t('pl.workArea'), t('pl.remove'), () => {
            fires.setArea(null);
          })
        : null}
    </div>
  );
}

/** Plan mode in the row of the field: how many crews and for how long. */
export function PlanFields() {
  const { t, lang } = useI18n();
  const { brief, setCrews, setHours } = useFiresState();
  return (
    <div className="pm-fields" id="pm-fields">
      <div
        className="stepper"
        role="group"
        aria-label={t('pl.crewsLabel')}
        data-tip={t('pl.crewsTip', { n: brief.crews })}
      >
        <button
          type="button"
          className="icon-btn"
          id="cr-dec"
          aria-label={t('plan.fewer')}
          disabled={brief.crews <= 1}
          onClick={() => {
            setCrews(brief.crews - 1);
          }}
        >
          <Ph name="minus" />
        </button>
        <b id="cr-n">{crewsText(t, lang, brief.crews)}</b>
        <button
          type="button"
          className="icon-btn"
          id="cr-inc"
          aria-label={t('plan.more')}
          disabled={brief.crews >= MAX_CREWS}
          onClick={() => {
            setCrews(brief.crews + 1);
          }}
        >
          <Ph name="plus" />
        </button>
      </div>
      <Segments
        id="win-seg"
        label={t('pl.windowLabel')}
        tip={t('pl.windowTip', { h: brief.hours })}
        items={HOURS.map((hours) => [hours, `${String(hours)} ${t('pl.h')}`] as const)}
        value={brief.hours}
        onChange={setHours}
      />
    </div>
  );
}

/** The task as it travels with the question: crews, window and the marks put on the map. */
export function PlanAsk({ turn }: { turn: PlanTurn }) {
  const { t, lang } = useI18n();
  const chip = (icon: PhName, text: string, own = '') => (
    <span className={`bchip ${own}`}>
      <Ph name={icon} />
      {text}
    </span>
  );
  return (
    <div className="bchips">
      {chip('users-three', crewsText(t, lang, turn.crews))}
      {chip('clock', t('pl.window', { h: turn.hours }))}
      {turn.entries > 0 ? chip('sign-in', t('pl.entries', { n: turn.entries }), 'entry') : null}
      {turn.hots > 0 ? chip('target', t('pl.hots', { n: turn.hots }), 'hot') : null}
      {turn.area ? chip('polygon', t('pl.workArea')) : null}
    </div>
  );
}

interface PlanAnswerProps {
  turn: PlanTurn;
  status: 'streaming' | 'done' | 'error';
  /** When the question was asked, for the time the planner has been at work. */
  startedAt: number;
  onOpen: () => void;
}

/** The answer to a plan: the steps, what was found, and the card that opens the plan. */
export function PlanAnswer({ turn, status, startedAt, onOpen }: PlanAnswerProps) {
  const { t, lang } = useI18n();
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (status !== 'streaming') return;
    const timer = window.setInterval(() => {
      setElapsed(Math.round((Date.now() - startedAt) / 1000));
    }, 500);
    return () => {
      window.clearInterval(timer);
    };
  }, [status, startedAt]);

  const zone = usePlaceZone(turn.fire);
  const { plan } = turn;
  // the planner gave up: the note under the answer says why, no spinner is left turning
  if (!plan && status !== 'streaming') return null;
  if (!plan) {
    return (
      <details className="agent">
        <summary className="agent-h">
          <Ph name="circle-notch" className="spin" />
          <span className="shimmer">{t('pl.working')}</span>
          <small>
            {elapsed} {t('pl.s')}
          </small>
          <Ph name="caret-right" className="chev" />
        </summary>
      </details>
    );
  }
  const report = planReport(t, lang, plan, turn.fire, zone);
  const steps = planSteps(
    t,
    lang,
    plan,
    turn.fire,
    {
      entries: turn.entries,
      hots: turn.hots,
    },
    zone,
  );
  const out = plan.crews.filter((crew) => crew.status === 'block').length;
  const risks = new Set(plan.issues.filter((issue) => issue.level === 'risk').map((i) => i.kind))
    .size;
  const leave = plan.report.leave_in_h;
  const warnings = plan.issues.filter((issue) => issue.level !== 'info').length;
  const lines = [
    plan.crews.every((crew) => crew.status === 'block')
      ? t('plan.none')
      : t('pl.done', { c: crewsText(t, lang, plan.crews.length, true) }),
    ...(out > 0 || risks > 0
      ? [
          [
            out > 0 ? t('pl.reviewOut', { n: out }) : '',
            risks > 0 ? t('pl.reviewRisk', { n: risks }) : '',
            t('pl.reviewCheck'),
          ]
            .filter(Boolean)
            .join(' '),
        ]
      : []),
    report.situation,
    report.safety,
  ];
  return (
    <>
      <details className="agent">
        <summary className="agent-h">
          <Ph name="check-circle" />
          <span>{t('pl.worked')}</span>
          <small>
            {Math.max(1, turn.seconds)} {t('pl.s')}
          </small>
          <Ph name="caret-right" className="chev" />
        </summary>
        <ol className="steps">
          {steps.map((step) => (
            <li key={step.label} className="step done">
              <Ph name="check-circle" />
              <div>
                <span>{step.label}</span>
                <small>{step.result}</small>
              </div>
            </li>
          ))}
        </ol>
      </details>
      {lines.map((line) => (
        <p key={line}>{line}</p>
      ))}
      <button type="button" className="artifact" onClick={onOpen}>
        <span className="art-ic">
          <Ph name="table" />
        </span>
        <span className="art-t">
          <b>{t('pl.artTitle', { n: turn.fire.summary.nearest_place.name })}</b>
          <small>
            {[
              crewsText(t, lang, plan.crews.length),
              leave === null ? '' : t('pl.artLeave', { u: planClock(lang, plan, leave, zone) }),
              warnings > 0 ? t('pl.artWarn', { w: warnings }) : '',
            ]
              .filter(Boolean)
              .join(', ')}
          </small>
        </span>
        <Ph name="caret-right" />
      </button>
    </>
  );
}
