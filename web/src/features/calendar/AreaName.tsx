import { useI18n } from '../../i18n/context';
import { useAreaName } from './areas';

/** The name of the area on the board; a pale bar of its size stands in until the name has come, never the code. The bar has a name for a reader of the screen: what the button does. */
export function AreaName() {
  const { t } = useI18n();
  return (
    useAreaName() ?? (
      <>
        <span className="skel" aria-hidden="true" />
        <span className="visually-hidden">{t('region.choose')}</span>
      </>
    )
  );
}
