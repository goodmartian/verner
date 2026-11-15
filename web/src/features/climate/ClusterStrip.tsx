import { usePlaceZone } from '../../config/usePlaceZone';
import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import { useBoard } from '../board/context';
import { formatCount } from '../calendar/text';
import { formatDayShort, formatPass } from '../fires/text';
import { StripCell } from '../weather/StripCells';
import { useClimateArea, useDayFires } from './queries';

/** The cluster of fires of a day along the top of the map: when it was seen, how big, and . */
export function ClusterStrip() {
  const { t, lang } = useI18n();
  const board = useBoard();
  const day = useDayFires(board.day, useClimateArea(board.area)).data;
  const cluster = day?.fires.find((item) => item.id === board.cluster) ?? null;
  const zone = usePlaceZone(cluster);
  if (!cluster || !board.day) return null;
  return (
    <div className="fire-strip month-strip cluster-strip">
      <span className="fs-name">
        <b>{cluster.province ?? `${cluster.lat.toFixed(2)}, ${cluster.lon.toFixed(2)}`}</b>
        <small>{t('clim.fireOf', { date: formatDayShort(lang, board.day) })}</small>
      </span>
      <StripCell
        value={formatCount(lang, cluster.detections)}
        label={t('fire.detections')}
        drop="lo"
      />
      <StripCell
        value={t('fire.mw', { n: formatCount(lang, cluster.frp_mw) })}
        label={t('fire.strip.power')}
        drop="lo"
      />
      <StripCell
        value={
          formatPass(lang, cluster.first_detection_at, zone) || (
            <span className="skel" aria-busy="true" />
          )
        }
        label={t('clim.first')}
      />
      <button
        type="button"
        className="icon-btn"
        aria-label={t('fire.back')}
        onClick={() => {
          board.setCluster(null);
        }}
      >
        <Ph name="x" />
      </button>
    </div>
  );
}
