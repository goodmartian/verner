import type { ReactNode } from 'react';
import { useI18n } from '../../i18n/context';
import { Tiles as TileGrid } from '../../ui/Tiles';
import dash from './CalDash.module.css';
import styles from './AreaCalendarBoard.module.css';

const SECTIONS = 7;
const MONTHS = Array.from({ length: 12 }, (_, index) => index);
// as many years as the first screen shows; the rest is below the fold and cut off
const YEARS = Array.from({ length: 9 }, (_, index) => index);

/**
 * The first screen of the board before its answer: the bar, the headline, the four figures and the calendar card,
 * built from the board's own classes so nothing moves when the answer comes. The pieces are pale and still;
 * the whole of it breathes as one, a single opacity animation.
 */
export function BoardSkeleton({ tools, label }: { tools: ReactNode; label: string }) {
  const { t } = useI18n();
  return (
    <div className={`${dash.dash} ${styles.loading}`} role="status" aria-busy="true">
      <span className="visually-hidden">{label}</span>
      <div className={dash.sticky}>
        <div className={dash.tools}>
          {tools}
          <span className={`${styles.bar} ${styles.button} ${styles.file}`} aria-hidden="true" />
        </div>
        <div className={`${dash.nav} ${styles.pulse}`} aria-hidden="true">
          {Array.from({ length: SECTIONS }, (_, index) => (
            <span key={index} className={`${styles.bar} ${styles.tab}`} />
          ))}
        </div>
      </div>
      <div className={`${dash.block} ${styles.pulse}`} aria-hidden="true">
        <div className={dash.lead}>
          <span className={`${styles.bar} ${styles.headline}`} />
          <span className={`${styles.bar} ${dash.leadAsk} ${styles.button} ${styles.ask}`} />
        </div>
        <div className={styles.figures}>
          <TileGrid
            items={[
              ['count', t('regions.detections')],
              ['usual', t('dash.tile.usual')],
              ['against', t('dash.tile.against')],
              ['rank', t('kpi.rank')],
            ].map(([key, name]) => ({
              key: key ?? '',
              label: name ?? '',
              big: <span className={`${styles.bar} ${styles.figure}`} />,
              sub: ' ',
            }))}
          />
        </div>
      </div>
      <div className={`${dash.block} ${styles.pulse}`} aria-hidden="true">
        <div className={dash.card}>
          <div className={dash.cardHead}>
            <span className={`${styles.bar} ${styles.title}`} />
            <span className={`${styles.bar} ${styles.key}`} />
          </div>
          <p className={dash.sentence}>
            <span className={`${styles.bar} ${styles.line}`} />
          </p>
          <div className={dash.grid}>
            <span />
            {MONTHS.map((month) => (
              <span key={month} className={`${styles.bar} ${styles.month}`} />
            ))}
            <span className={dash.sum} />
            {YEARS.map((year) => (
              <div key={year} className={dash.row}>
                <span className={`${styles.bar} ${styles.year}`} />
                {MONTHS.map((month) => (
                  <span key={month} className={`${dash.cell} ${styles.cell}`} />
                ))}
                <span className={dash.sum}>
                  <span className={`${styles.bar} ${styles.total}`} />
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
