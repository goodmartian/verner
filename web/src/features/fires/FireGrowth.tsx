import type { CSSProperties } from 'react';
import { usePlaceZone } from '../../config/usePlaceZone';
import type { FireDetail } from '../../api/types';
import { useI18n } from '../../i18n/context';
import { localName } from '../../i18n/lang';
import { useAskPop } from '../../ui/AskPop';
import { detectionsWord } from '../calendar/text';
import { useFiresList } from './queries';
import { useFireAsk } from './useFireAsk';
import { coverSummary } from './cover';
import { useAccessRoute, useLandCover } from './queries';
import { accessText } from './access';
import { useFiresState } from './context';
import styles from './FireGrowth.module.css';
import { areaText, formatPass } from './text';

/** What the fire did over the satellite passes: a bar per pass with the times at its ends, two lines of facts. */
export function FireGrowth({ detail }: { detail: FireDetail }) {
  const { t, lang } = useI18n();
  const zone = usePlaceZone(detail);
  const passes = useFiresList().data?.passes;
  const growth = detail.summary.growth;
  const tallest = Math.max(1, ...growth.map((item) => item.pass_detections));
  const timeOf = (index: number | undefined) => {
    const time = index === undefined ? undefined : passes?.[index]?.time;
    return time ? formatPass(lang, time, zone) : '';
  };
  const first = growth[0];
  const last = growth.at(-1);
  const seen = growth.filter((item) => item.pass_detections > 0).length;
  // a bar, and a line of facts, open the card of their figure
  const pop = useAskPop();
  const ground = useLandCover(detail.summary.id, useFiresState().pass).data;
  const burnsOn = ground ? coverSummary(ground, (names) => localName(names, lang), lang) : '';
  const route = useAccessRoute(detail.summary.id, useFiresState().pass).data;
  const way = route ? accessText(t, lang, route) : '';
  const ask = useFireAsk(
    detail.summary.nearest_place.name,
    formatPass(lang, detail.pass_time, zone),
  );
  const row = (title: string, value: string) => ({
    role: 'button',
    tabIndex: 0,
    ...pop.bind(ask(title, value), { keys: true }),
  });
  return (
    <section className="block" aria-labelledby="h-growth">
      <h2 id="h-growth">{t('fire.growth')}</h2>
      <div className={styles.bars}>
        {growth.map((item) => {
          const when = timeOf(item.pass_index);
          const count = `${String(item.pass_detections)} ${detectionsWord(t, lang, item.pass_detections)}`;
          const info = ask(`${t('fire.growth')}, ${when}`, count, areaText(t, lang, item.area_ha));
          return (
            <button
              type="button"
              key={item.pass_index}
              aria-label={`${when}: ${count}`}
              {...pop.bind(info)}
              className={
                item.pass_index > detail.pass_index
                  ? styles.later
                  : item.pass_index === detail.pass_index
                    ? styles.now
                    : undefined
              }
              style={{ '--h': (item.pass_detections / tallest).toFixed(2) } as CSSProperties}
            />
          );
        })}
      </div>
      <p className={styles.times}>
        <span>{timeOf(first?.pass_index)}</span>
        <span>{timeOf(last?.pass_index)}</span>
      </p>
      <div className={styles.metrics}>
        <div {...row(t('fire.first'), formatPass(lang, detail.summary.first_detection_at, zone))}>
          <span className={styles.k}>{t('fire.first')}</span>
          <span className={styles.v}>
            {formatPass(lang, detail.summary.first_detection_at, zone)}
          </span>
        </div>
        <div {...row(t('fire.seen'), `${String(seen)} / ${String(growth.length)}`)}>
          <span className={styles.k}>{t('fire.seen')}</span>
          <span className={styles.v}>{`${String(seen)} / ${String(growth.length)}`}</span>
        </div>
        {burnsOn ? (
          <div {...row(t('fire.burnsOn'), burnsOn)}>
            <span className={styles.k}>{t('fire.burnsOn')}</span>
            <span className={styles.v}>{burnsOn}</span>
          </div>
        ) : null}
        {way ? (
          <div {...row(t('fire.access'), way)}>
            <span className={styles.k}>{t('fire.access')}</span>
            <span className={styles.v}>{way}</span>
          </div>
        ) : null}
      </div>
      {pop.card}
    </section>
  );
}
