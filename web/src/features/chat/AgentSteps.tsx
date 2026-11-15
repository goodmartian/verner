import { useState } from 'react';
import { useI18n } from '../../i18n/context';
import { Ph } from '../../ui/Ph';
import styles from './AgentSteps.module.css';

export type StepStatus = 'pending' | 'running' | 'done' | 'error';

export interface Step {
  id: string;
  label: string;
  status: StepStatus;
}

/** A soft brightness wave runs through the letters of the step that is going on. */
function Wave({ text }: { text: string }) {
  return (
    <>
      <span className="visually-hidden">{text}</span>
      <span aria-hidden="true">
        {Array.from(text).map((char, index) => (
          <span
            key={index}
            className={styles.letter}
            style={{ animationDelay: `${index * 0.05}s` }}
          >
            {char}
          </span>
        ))}
      </span>
    </>
  );
}

/** The sign of a step in its own small round: a turning arc while it goes on, a check when done, a cross when it failed. */
function Mark({ status }: { status: StepStatus }) {
  // the mark of a step is new each time its status changes, so it eases in
  return (
    <span className={styles.mark} key={status} data-status={status}>
      {status === 'done' ? (
        <Ph name="check" />
      ) : status === 'error' ? (
        <Ph name="x" />
      ) : status === 'running' ? (
        <Ph name="circle-notch" />
      ) : (
        <i />
      )}
    </span>
  );
}

/**
 * The steps of the assistant as it works: each appears as it starts, the running one has the wave in its text, a done one
 * has a check, a failed one a cross. Once the answer comes the list folds to one line, "N steps", that opens again;
 * a single step stays as its own line, since a line that hides one line saves nothing.
 */
export function AgentSteps({ steps, folded }: { steps: readonly Step[]; folded: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  if (steps.length === 0) return null;
  const list = (
    <ol className={styles.list}>
      {steps.map((step, index) => (
        <li key={step.id} className={styles.step} data-status={step.status}>
          {index < steps.length - 1 ? (
            <span className={styles.rail} data-filled={step.status === 'done' ? 'on' : undefined} />
          ) : null}
          <Mark status={step.status} />
          <span className={styles.label}>
            {step.status === 'running' ? <Wave text={step.label} /> : step.label}
          </span>
        </li>
      ))}
    </ol>
  );
  if (!folded || steps.length === 1) return <div className={styles.steps}>{list}</div>;
  return (
    <div className={styles.steps}>
      <button
        type="button"
        className={styles.fold}
        aria-expanded={open}
        onClick={() => {
          setOpen((now) => !now);
        }}
      >
        <span className={styles.caret} data-open={open ? 'on' : undefined}>
          <Ph name="caret-right" />
        </span>
        {t('chat.steps', { n: steps.length })}
      </button>
      {open ? list : null}
    </div>
  );
}
