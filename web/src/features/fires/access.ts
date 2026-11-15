import type { AccessRoute } from '../../api/types';
import type { I18n } from '../../i18n/context';
import { LOCALES, type Lang } from '../../i18n/lang';

/**
 * The way in as a line: «77 min by road, 31 km from Las Lomitas, on foot 4.4 km». The start is
 * a fire station or, when none was found, the nearest place: the words say which, so a place is
 * never taken for a station.
 */
export function accessText(t: I18n['t'], lang: Lang, route: AccessRoute): string {
  const number = (n: number, digits: number) =>
    new Intl.NumberFormat(LOCALES[lang], { maximumFractionDigits: digits }).format(n);
  const from = t(route.origin_kind === 'station' ? 'fire.accessStation' : 'fire.accessPlace', {
    name: route.station_name,
  });
  const road = t('fire.accessRoad', {
    min: number(Math.round(route.drive_min), 0),
    km: number(route.drive_km, 0),
    from,
  });
  return route.walk_km >= 0.1
    ? `${road}${t('fire.accessWalk', { km: number(route.walk_km, 1) })}`
    : road;
}

/** Credits of several answers as one text; a sentence the answers share (the places of GeoNames) is said once. */
export function joinCredits(credits: readonly (string | null | undefined)[]): string | null {
  const sentences = credits.flatMap((text) => (text ? text.split(/(?<=\.)\s+/) : []));
  return [...new Set(sentences)].join(' ') || null;
}
