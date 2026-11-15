import { usePlaceZone } from '../../config/usePlaceZone';
import { useState } from 'react';
import { ApiError } from '../../api/client';
import { useApiErrorText } from '../../api/useApiErrorText';
import type { FireDetail, FirePlan, PlanCrew } from '../../api/types';
import { useI18n } from '../../i18n/context';
import { localName } from '../../i18n/lang';
import type { MessageKey } from '../../i18n/en';
import { Ph } from '../../ui/Ph';
import { Tiles, type TileData } from '../../ui/Tiles';
import { Hint } from '../calendar/Hint';
import { useFiresState } from './context';
import {
  crewEntry,
  crewIssues,
  crewKeys,
  distanceText,
  crewTask,
  goingCrews,
  planClock,
  planCopy,
  planReport,
  reviewRows,
} from './planText';
import { planSignature } from './planSignature';
import { useLandCover, useSavePlan } from './queries';
import { usePlansErrorText } from './SavedPlans';
import { compass, formatPass } from './text';
import { toRequest, useBuildPlan, useShownFire } from './usePlan';
import { Segments } from '../../ui/Segments';

type Filter = 'all' | 'block' | 'risk';

/** The server cannot plan this fire: a plain answer, not a failure. */
const isUnavailable = (error: unknown) =>
  error instanceof ApiError && error.code === 'plan_unavailable';

const decimal = (lang: string, n: number, digits = 1) =>
  new Intl.NumberFormat(lang === 'en' ? 'en-GB' : lang, { maximumFractionDigits: digits }).format(
    n,
  );

interface PlanDockProps {
  wide: boolean;
  onWide: () => void;
  onClose: () => void;
}

/** The work plan beside the map: the facts, what the planner objects to, a card per crew, the report. */
export function PlanDock({ wide, onWide, onClose }: PlanDockProps) {
  const fires = useFiresState();
  const detail = useShownFire();
  const plan = fires.plan;
  if (!plan || !detail) return null;
  return <Dock plan={plan} detail={detail} wide={wide} onWide={onWide} onClose={onClose} />;
}

interface DockProps extends PlanDockProps {
  plan: FirePlan;
  detail: FireDetail;
}

function Dock({ plan, detail, wide, onWide, onClose }: DockProps) {
  const { t, lang } = useI18n();
  const errorText = useApiErrorText();
  const fires = useFiresState();
  const { build, override, pending, error } = useBuildPlan();
  const [filter, setFilter] = useState<Filter>('all');
  const [note, setNote] = useState('');
  const signature = planSignature(plan);
  const isSaved = fires.saved === signature;
  const { setSaved } = fires;
  const save = useSavePlan();
  const plansError = usePlansErrorText();
  const keep = () => {
    save.mutate(
      {
        fireId: detail.summary.id,
        title: t('plan.defaultTitle', { place: detail.summary.nearest_place.name }),
        request: toRequest(plan.pass_index, fires.brief),
      },
      {
        onSuccess: () => {
          setSaved(signature);
        },
      },
    );
  };

  const zone = usePlaceZone(detail);
  const report = planReport(t, lang, plan, detail, zone);
  const rows = reviewRows(t, lang, plan, detail.pass_time, zone);
  const blocked = plan.crews.filter((crew) => crew.status === 'block');
  const risky = plan.crews.filter(
    (crew) =>
      crew.status !== 'block' && crewIssues(plan, crew).some((issue) => issue.level === 'risk'),
  );
  const shown: Filter =
    (filter === 'block' && blocked.length === 0) || (filter === 'risk' && risky.length === 0)
      ? 'all'
      : filter;
  const filters = [
    { value: 'all' as const, label: t('pl.fAll'), n: plan.crews.length },
    { value: 'block' as const, label: t('pl.fBlock'), n: blocked.length },
    { value: 'risk' as const, label: t('pl.fRisk'), n: risky.length },
  ].filter((item, index) => index === 0 || item.n > 0);
  const kindOf = (crew: PlanCrew): Filter =>
    crew.status === 'block'
      ? 'block'
      : crewIssues(plan, crew).some((issue) => issue.level === 'risk')
        ? 'risk'
        : 'all';

  const said = (text: string) => {
    setNote(text);
    window.setTimeout(() => {
      setNote('');
    }, 2500);
  };
  const copy = (text: string) => {
    navigator.clipboard.writeText(text).then(
      () => {
        said(t('pl.copied'));
      },
      () => {
        said(t('pl.copyFail'));
      },
    );
  };

  const wind = (plan.wind.from_deg + 180) % 360;
  const leaveIn = plan.report.leave_in_h;

  const facts: TileData[] = [
    {
      key: 'until',
      label: t('plan.until'),
      big: planClock(lang, plan, plan.hours, zone),
      sub: t('pl.window', { h: plan.hours }),
    },
    {
      key: 'leave',
      label: t('plan.leave'),
      big: leaveIn === null ? '—' : planClock(lang, plan, leaveIn, zone),
      sub: leaveIn === null ? t('pl.hzNone') : undefined,
    },
    {
      key: 'wind',
      label: t('plan.wind'),
      big: (
        <>
          <Ph name="arrow-up" style={{ transform: `rotate(${String(Math.round(wind))}deg)` }} />
          {decimal(lang, plan.wind.speed_kmh, 0)} {t('pl.kmh')}
        </>
      ),
      sub: t(`dirFrom.${String(compass(plan.wind.from_deg / 45))}` as MessageKey),
    },
    {
      key: 'head',
      label: t('plan.head'),
      big: `${decimal(lang, plan.report.spread_km_per_h)} ${t('pl.kmh')}`,
      sub: t(`pl.to.${String(compass(wind / 45))}` as MessageKey),
    },
  ];

  return (
    <section className="dock" id="dock" aria-labelledby="dock-title">
      <header className="dock-head">
        <button
          type="button"
          className="icon-btn"
          id="dock-back"
          aria-label={t('pl.back')}
          onClick={onClose}
        >
          <Ph name="arrow-left" />
        </button>
        <div className="dock-t">
          <h2 id="dock-title">{t('pl.artTitle', { n: detail.summary.nearest_place.name })}</h2>
        </div>
        <div className="dock-act">
          <button
            type="button"
            className="icon-btn"
            id="dock-save"
            aria-label={t(isSaved ? 'pl.saved' : 'pl.save')}
            disabled={isSaved || save.isPending}
            onClick={keep}
          >
            <Ph name={isSaved ? 'check' : 'floppy-disk'} />
          </button>
          <button
            type="button"
            className="icon-btn"
            id="dock-copy"
            aria-label={t('pl.copyPlan')}
            onClick={() => {
              copy(planCopy(t, lang, plan, detail, zone));
            }}
          >
            <Ph name="copy" />
          </button>
          <button
            type="button"
            className="icon-btn"
            id="dock-max"
            aria-expanded={wide}
            aria-label={t(wide ? 'common.shrink' : 'common.expand')}
            onClick={onWide}
          >
            <Ph name={wide ? 'arrows-in-line-horizontal' : 'arrows-out-line-horizontal'} />
          </button>
        </div>
      </header>
      <div className="dock-body">
        <Tiles items={facts} id="plan-facts" />
        <p className="wx-src">{t('plan.windAt', { time: formatPass(lang, plan.wind.at, zone) })}</p>
        <ul className="iss-list" id="plan-warn">
          {rows.map((row, index) => (
            <li key={`${row.title}-${String(index)}`} className={`iss ${row.level}`}>
              <Ph name={row.icon} />
              <span>
                <b>{row.title}</b>
                {row.sub ? <small>{row.sub}</small> : null}
              </span>
              {row.rebuild ? (
                <button
                  type="button"
                  className="btn btn-secondary iss-btn"
                  disabled={pending}
                  onClick={() => {
                    void build().catch(() => undefined);
                  }}
                >
                  {t('pl.replan')}
                </button>
              ) : row.keys.length > 0 ? (
                <button
                  type="button"
                  className="btn btn-secondary iss-btn"
                  aria-pressed={row.forced}
                  disabled={pending}
                  onClick={() => {
                    void override(row.keys, !row.forced).catch(() => undefined);
                  }}
                >
                  {t(row.forced ? 'pl.unforce' : 'pl.force')}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        {plan.straight_line_only && !plan.issues.some((issue) => issue.kind === 'noland') ? (
          <p className="note" role="status">
            {t('issue.noland')}
          </p>
        ) : null}
        {goingCrews(plan).length === 0 ? <p className="note">{t('plan.none')}</p> : null}
        {filters.length > 1 ? (
          <Segments
            id="crew-filter"
            className="crew-filter"
            label={t('pl.crewsLabel')}
            items={filters.map((item) => [item.value, `${item.label} ${String(item.n)}`] as const)}
            value={shown}
            onChange={setFilter}
          />
        ) : null}
        <ol
          className="crews"
          id="crews"
          onMouseLeave={() => {
            fires.setCrewHi(0);
          }}
        >
          {plan.crews.map((crew) => (
            <CrewCard
              key={crew.number}
              crew={crew}
              plan={plan}
              hidden={shown !== 'all' && shown !== kindOf(crew)}
              kind={kindOf(crew)}
              walkLimitMin={plan.hours * 60}
              busy={pending}
              onForce={(keys, on) => {
                void override(keys, on).catch(() => undefined);
              }}
              onCopy={copy}
            />
          ))}
        </ol>
        {save.isError ? (
          <p className="note" role="alert">
            {plansError(save.error)}
          </p>
        ) : null}
        {error ? (
          <p className="note" role={isUnavailable(error) ? 'status' : 'alert'}>
            {errorText(error)}
          </p>
        ) : null}
        <div className="report" id="report">
          {(
            [
              ['pl.hSit', report.situation],
              ['pl.hTask', report.task],
              ['pl.hSafe', report.safety],
            ] as const
          ).map(([heading, text]) => (
            <section key={heading}>
              <h3>
                {t(heading)}
                {heading === 'pl.hSit' ? <Hint text={t('pl.hintGrowth')} /> : null}
              </h3>
              <p>{text}</p>
            </section>
          ))}
        </div>
        <div className="dock-foot">
          <ul className="map-key">
            <li>
              <i className="k k-attack" />
              <span>{t('key.attack')}</span>
            </li>
            <li>
              <i className="k k-escape" />
              <span>{t('key.escape')}</span>
            </li>
            <li>
              <i className="k k-fc" />
              <span>{t('key.forecast')}</span>
            </li>
            <li>
              <i className="k k-safe" />
              <span>{t('key.safe')}</span>
            </li>
          </ul>
          <p className="note" id="r-note" role="status">
            {note}
          </p>
        </div>
      </div>
    </section>
  );
}

interface CrewCardProps {
  crew: PlanCrew;
  plan: FirePlan;
  hidden: boolean;
  kind: Filter;
  walkLimitMin: number;
  busy: boolean;
  onForce: (keys: readonly string[], on: boolean) => void;
  onCopy: (text: string) => void;
}

function CrewCard({
  crew,
  plan,
  hidden,
  kind,
  walkLimitMin,
  busy,
  onForce,
  onCopy,
}: CrewCardProps) {
  const { t, lang } = useI18n();
  const fires = useFiresState();
  const zone = usePlaceZone(useShownFire());
  const detail = useShownFire();
  const legend = useLandCover(fires.fireId, fires.pass).data?.classes;
  const [lng, lat] = [crew.entry[0] ?? 0, crew.entry[1] ?? 0];
  const coordinates = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  const km = (m: number) => `${decimal(lang, m / 1000)} ${t('pl.km')}`;
  const keys = crewKeys(plan, crew);
  const held = crew.held.map((name) => t(`pl.k_${name}` as MessageKey).toLowerCase());
  const hazard =
    crew.distance_to_active_m !== null
      ? {
          value: t('pl.hzFire', { d: distanceText(t, lang, crew.distance_to_active_m) }),
          title: t('pl.activeSub'),
          warn: crew.distance_to_active_m < 500,
        }
      : crew.leave_in_h !== null
        ? {
            value: t('pl.hzHead', { tm: planClock(lang, plan, crew.leave_in_h, zone) }),
            title: t('pl.workUntilSub', { tm: planClock(lang, plan, crew.leave_in_h, zone) }),
            warn: crew.leave_in_h <= plan.hours,
          }
        : { value: t('pl.hzNone'), title: t('plan.free'), warn: false };
  const escapeRisk = !crew.safe_on_burned_ground || crew.escape_threatened_in_h !== null;

  return (
    <li
      className={`crew-card${crew.status === 'block' ? ' is-block' : ''}`}
      data-crew={crew.number}
      data-kind={kind}
      hidden={hidden}
      onMouseEnter={() => {
        fires.setCrewHi(crew.number);
      }}
    >
      <button
        type="button"
        className="crew-n"
        aria-label={t('pl.showCrew', { n: crew.number })}
        onClick={() => {
          fires.focusCrew(crew.number);
        }}
        onFocus={() => {
          fires.setCrewHi(crew.number);
        }}
        onBlur={() => {
          fires.setCrewHi(0);
        }}
      >
        {crew.number}
      </button>
      <div className="crew-main">
        <div className="crew-t">
          <b>{crewTask(t, crew)}</b>
          <span>{crewEntry(t, plan, crew, detail?.summary.center ?? crew.entry)}</span>
        </div>
        {crew.status !== 'ok' || keys.length > 0 ? (
          <div className="crew-st">
            {crew.status === 'block' ? (
              <span className="pill block">
                <Ph name="prohibit" />
                {t('pl.leftOut')}: {held.join(', ')}
              </span>
            ) : crew.status === 'forced' ? (
              <span className="pill forced">
                <Ph name="user-check" />
                {t('pl.forced')}
              </span>
            ) : null}
            {keys.length > 0 ? (
              <button
                type="button"
                className="btn btn-secondary iss-btn"
                aria-pressed={crew.status === 'forced'}
                disabled={busy}
                onClick={() => {
                  onForce(keys, crew.status === 'block');
                }}
              >
                {t(crew.status === 'block' ? 'pl.force' : 'pl.unforce')}
              </button>
            ) : null}
          </div>
        ) : null}
        <dl className="crew-m">
          <div>
            <dt>{t('pl.route')}</dt>
            <dd>{km(crew.length_m)}</dd>
          </div>
          <div className={crew.long_walk || crew.walk_min > walkLimitMin ? 'risk' : ''}>
            <dt>{t('pl.walk')}</dt>
            <dd>
              {decimal(lang, crew.walk_min, 0)} {t('pl.min')}
            </dd>
          </div>
          <div className={hazard.warn ? 'warn' : ''} title={hazard.title}>
            <dt>{t('pl.hazard')}</dt>
            <dd>{hazard.value}</dd>
          </div>
        </dl>
        {legend && crew.land?.length ? (
          <div className="crew-lc">
            <span className="lc-bar" aria-hidden="true">
              {crew.land.map((part) => (
                <i
                  key={part.id}
                  style={{
                    flex: part.share_pct.toFixed(0),
                    background: legend.find((item) => item.id === part.id)?.color,
                  }}
                />
              ))}
            </span>
            <small>
              {crew.land
                .map((part) => {
                  const found = legend.find((item) => item.id === part.id);
                  return found
                    ? `${localName(found.name, lang).toLowerCase()} ${decimal(lang, Math.round(part.share_pct), 0)} %`
                    : '';
                })
                .filter(Boolean)
                .join(', ')}
            </small>
          </div>
        ) : null}
        <p className={`crew-esc${escapeRisk ? ' risk' : ''}`}>
          <span>{t('pl.escape')}</span>{' '}
          {t(crew.safe_on_burned_ground ? 'pl.escBurned' : 'pl.escBehind', {
            m: decimal(lang, Math.round(crew.safe_distance_m / 50) * 50, 0),
          })}
        </p>
      </div>
      <div className="crew-act">
        <button
          type="button"
          className="icon-btn"
          aria-label={t('pl.copyCoords')}
          onClick={() => {
            onCopy(coordinates);
          }}
        >
          <Ph name="copy" />
        </button>
        <a
          className="icon-btn mobile-only"
          target="_blank"
          rel="noopener noreferrer"
          href={`https://www.google.com/maps/dir/?api=1&destination=${lat.toFixed(5)},${lng.toFixed(5)}&travelmode=driving`}
          aria-label={t('pl.navEntry')}
        >
          <Ph name="navigation-arrow" />
        </a>
      </div>
    </li>
  );
}
