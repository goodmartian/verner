import type { FireDetail } from '../../api/types';
import { useI18n } from '../../i18n/context';
import { fireConditions, NONE, type Conditions } from './conditions';
import { useFireWeather, useWeatherLegend } from './queries';
import { useWeatherMoment } from './useMoment';

/** The weather at the open fire for the hour of the player (the present one while it is closed). */
export function useConditions(detail: FireDetail | undefined): Conditions {
  const { lang } = useI18n();
  const legend = useWeatherLegend().data;
  // the weather of every fire of the world is megabytes: it is asked for once a fire is open, not on the first screen
  const weather = useFireWeather(detail !== undefined, {
    ids: detail ? [detail.summary.id] : [],
  }).data;
  const moment = useWeatherMoment();
  if (!detail) return NONE;
  const series = weather?.fires.find((item) => item.fire_id === detail.summary.id);
  return fireConditions(detail, series, weather?.start ?? null, moment, legend, lang);
}
