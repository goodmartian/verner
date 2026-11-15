import { useState, type CSSProperties } from 'react';
import { areaId } from '../../config/context';
import { useI18n } from '../../i18n/context';
import { localName } from '../../i18n/lang';
import { regionLabel } from '../../i18n/regionLabel';
import { Ph } from '../../ui/Ph';
import { useBoard } from '../board/context';
import { useProvinces } from './queries';
import { formatChange, formatCount } from './text';
import styles from './CalDash.module.css';

/** The provinces of a country side by side: the biggest first, a click on a row opens it. */
export function Provinces() {
  const { t, lang } = useI18n();
  const board = useBoard();
  const [sort, setSort] = useState<'total' | 'ratio' | 'name'>('total');
  const [all, setAll] = useState(false);
  const { data: table, isPending } = useProvinces(sort);
  if (isPending) return <div className={`skel ${styles.provSkel}`} aria-busy="true" />;
  if (!table || table.rows.length === 0) return null;
  // the period is the whole archive: a share of the country; against the norm it would always be above it
  const whole = table.whole;
  const max = Math.max(1, ...table.rows.map((row) => row.total));
  const shown = all ? table.rows : table.rows.slice(0, 8);
  const rows = [
    ...shown,
    ...table.rows.filter((row) => !shown.includes(row) && row.id === areaId(board.area)),
  ];
  const th = (key: typeof sort, label: string) => (
    <th scope="col">
      <button
        type="button"
        aria-pressed={sort === key}
        onClick={() => {
          setSort(key);
        }}
      >
        {label}
        {sort === key ? <Ph name="arrow-down" /> : null}
      </button>
    </th>
  );
  return (
    <div className={styles.card}>
      <div className="prov" id="prov">
        <h3>{regionLabel(table, lang, 'other', t('regions.title'))}</h3>
        <table>
          <thead>
            <tr>
              {th('name', regionLabel(table, lang, 'one', t('regions.name')))}
              {th('total', t('regions.detections'))}
              {th('ratio', whole ? t('regions.share') : t('regions.vsNormal'))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                aria-current={row.id === areaId(board.area)}
                tabIndex={0}
                onClick={() => {
                  if (row.id !== areaId(board.area)) board.setArea(row.id);
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    if (row.id !== areaId(board.area)) board.setArea(row.id);
                  }
                }}
              >
                <td>{localName(row.names, lang)}</td>
                <td className="pv">
                  <span className="pbar">
                    <i style={{ '--w': (row.total / max).toFixed(3) } as CSSProperties} />
                    <span>{formatCount(lang, row.total, table.approximate)}</span>
                  </span>
                </td>
                <td className={!whole && (row.ratio ?? 0) > 1.1 ? 'up' : undefined}>
                  {whole
                    ? `${String(Math.round(row.share * 100))} %`
                    : row.ratio !== null
                      ? formatChange(lang, row.ratio)
                      : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {table.rows.length > 8 ? (
          <button
            type="button"
            className="btn btn-secondary prov-more"
            onClick={() => {
              setAll(!all);
            }}
          >
            {all ? t('regions.fewer') : t('regions.all', { n: table.rows.length })}
          </button>
        ) : null}
      </div>
    </div>
  );
}
