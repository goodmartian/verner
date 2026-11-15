import { ApiError } from '../../api/client';
import { useApiErrorText } from '../../api/useApiErrorText';
import { placeZone, usePlaceZone } from '../../config/usePlaceZone';
import { useI18n } from '../../i18n/context';
import { formatWhen } from '../../lib/format';
import { Ph } from '../../ui/Ph';
import { useFiresState } from './context';
import { useDeletePlan, useOpenPlan, usePlans } from './queries';

/** What an error of the plans says: a full shelf and a closed storage have words of their own. */
export function usePlansErrorText() {
  const { t } = useI18n();
  const errorText = useApiErrorText();
  return (error: unknown): string =>
    error instanceof ApiError && error.code === 'conflict' ? t('plans.limit') : errorText(error);
}

/** The plans this browser has kept; one is opened as it was made, with the fire as it was then. */
export function SavedPlans() {
  const { t, lang } = useI18n();
  const errorText = usePlansErrorText();
  const fires = useFiresState();
  const zone = usePlaceZone();
  const plans = usePlans();
  const remove = useDeletePlan();
  const open = useOpenPlan();

  if (plans.isError) {
    return (
      <p className="note" role="status">
        {errorText(plans.error)}
      </p>
    );
  }
  if (!plans.data?.length) return null;
  return (
    <section className="block" aria-labelledby="h-saved" id="saved-plans">
      <h2 id="h-saved">{t('plans.title')}</h2>
      {plans.data.map((plan) => (
        <div key={plan.id} className="hist-row">
          <button
            type="button"
            className="menu-item hist-item"
            onClick={() => {
              open.mutate(plan.id, { onSuccess: fires.openRecord });
            }}
          >
            <span>
              <b>{plan.title || t('plan.defaultTitle', { place: plan.near })}</b>
              <small>
                {t('plan.crews')}: {plan.crews}, {t('plan.hours', { n: plan.hours })},{' '}
                {formatWhen(lang, plan.created_at, placeZone(plan, zone)) || (
                  <span className="skel" aria-busy="true" />
                )}
              </small>
            </span>
          </button>
          <button
            type="button"
            className="icon-btn"
            aria-label={`${t('plans.delete')}: ${plan.title || plan.near}`}
            onClick={() => {
              remove.mutate(plan.id);
            }}
          >
            <Ph name="trash" />
          </button>
        </div>
      ))}
      {open.isError || remove.isError ? (
        <p className="note" role="alert">
          {errorText(open.error ?? remove.error)}
        </p>
      ) : null}
    </section>
  );
}
