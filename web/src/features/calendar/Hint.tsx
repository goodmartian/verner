import { useId, useState } from 'react';
import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import styles from './CalDash.module.css';

/** A small question mark that says more on hover, focus or tap, so the card itself stays short. */
export function Hint({ text }: { text: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      className={styles.hint}
      onMouseEnter={() => {
        setOpen(true);
      }}
      onMouseLeave={() => {
        setOpen(false);
      }}
    >
      <button
        type="button"
        aria-label={t('dash.hint.label')}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onClick={() => {
          setOpen((now) => !now);
        }}
        onFocus={() => {
          setOpen(true);
        }}
        onBlur={() => {
          setOpen(false);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false);
        }}
      >
        <Ph name="question" />
      </button>
      {open ? (
        <span className={styles.hintText} id={id} role="tooltip">
          {text}
        </span>
      ) : null}
    </span>
  );
}
