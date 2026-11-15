import { isLang, LANG_STORAGE_KEY } from '../i18n/lang';
import { translate } from '../i18n/translate';
import { readStored } from '../lib/storage';
import styles from './ConfigError.module.css';

/** The app cannot start without the config: say so in the language the person chose, and offer to ask again. */
export function ConfigError({ onRetry }: { onRetry: () => void }) {
  const stored = readStored(LANG_STORAGE_KEY);
  const lang = isLang(stored) ? stored : 'en';
  return (
    <main className={styles.screen}>
      <p role="alert">{translate(lang, 'error.network')}</p>
      <button type="button" className="btn btn-secondary" onClick={onRetry}>
        {translate(lang, 'chat.retry')}
      </button>
    </main>
  );
}
