import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import { useFiresState } from './context';
import { useFire } from './queries';
import { whereText } from './text';

/** The chosen fire along the top of the map: its name and place, and a cross to close it. The numbers are in the tiles of the panel, at every width. */
export function FireStrip() {
  const { t, lang } = useI18n();
  const state = useFiresState();
  const open = useFire(state.fireId, state.pass);
  const detail = state.fireId ? (state.record?.fire ?? open.data) : undefined;
  if (!detail) return null;
  return (
    <div className="fire-strip">
      <div className="fs-cells">
        <span className="fs-name">
          <b>{detail.summary.nearest_place.name}</b>
          <small>{whereText(t, lang, detail.summary.nearest_place)}</small>
        </span>
      </div>
      <button
        type="button"
        className="icon-btn"
        aria-label={t('fire.back')}
        onClick={() => {
          state.select(null);
        }}
      >
        <Ph name="x" />
      </button>
    </div>
  );
}
