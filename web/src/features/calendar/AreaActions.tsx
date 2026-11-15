import { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { ApiError } from '../../api/client';
import { exportMonths, exportTicket, type ExportKind } from '../../api/calendar';
import { useApiErrorText } from '../../api/useApiErrorText';
import { areaId } from '../../config/context';
import { useI18n } from '../../i18n/context';
import { saveFile, saveUrl } from '../../lib/saveFile';
import { Ph } from '../../ui/Ph';
import { PopupMenu } from '../../ui/PopupMenu';
import { useBoard } from '../board/context';
import { WORLD } from './areas';
import { useCalendar, useRange } from './queries';
import styles from './AreaActions.module.css';

/** The button of the file of the period: a menu that says what each file holds before it is asked for. */
export function ExportButton() {
  const { area, range } = useBoard();
  const waiting = useCalendar().isPending;
  return <Export key={JSON.stringify([area, range])} waiting={waiting} />;
}

const KINDS = [
  { kind: 'months', label: 'area.exportMonths', note: 'area.exportMonthsNote' },
  { kind: 'hotspots', label: 'area.exportHotspots', note: 'area.exportHotspotsNote' },
] as const satisfies readonly { kind: ExportKind; label: string; note: string }[];

function Export({ waiting }: { waiting: boolean }) {
  const { t } = useI18n();
  const board = useBoard();
  const { range } = useRange();
  const errorText = useApiErrorText();
  const button = useRef<HTMLButtonElement>(null);
  const items = useRef<Partial<Record<ExportKind, HTMLButtonElement | null>>>({});
  const [open, setOpen] = useState(false);
  const close = () => {
    setOpen(false);
    button.current?.focus();
  };
  const start = useMutation({
    mutationFn: async (kind: ExportKind) => {
      if (!board.area) throw new Error('No area');
      if (kind === 'months') {
        const file = await exportMonths(board.area, range);
        saveFile(file.blob, file.name);
      } else {
        // the file of every detection goes from the server to the disk: the page only asks for its address
        const ticket = await exportTicket(board.area, range);
        saveUrl(ticket.url, ticket.name);
      }
    },
    onSuccess: close,
    // the choice was off while it waited, and the focus left it: it comes back beside the note
    onError: (_error, kind) => {
      window.setTimeout(() => items.current[kind]?.focus());
    },
  });
  // the menu lives at the end of the page: the keyboard goes into it as it opens
  useEffect(() => {
    if (open) items.current.months?.focus();
  }, [open]);
  // a refusal stays in the menu, under the file it is about, and never in the bar
  const failed = start.error ? start.variables : null;
  return (
    <>
      <button
        ref={button}
        type="button"
        className={`btn btn-secondary ${styles.exportButton}`}
        aria-label={t('area.export')}
        title={t('area.export')}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={!board.area || waiting}
        onClick={() => {
          if (open) {
            close();
            return;
          }
          if (!start.isPending) start.reset();
          setOpen(true);
        }}
      >
        <Ph name="download-simple" />
        <span className={styles.exportText}>{t('area.export')}</span>
      </button>
      <PopupMenu
        anchor={button}
        open={open}
        onClose={close}
        className={styles.exportMenu}
        align="end"
        up={false}
        label={t('area.export')}
      >
        {KINDS.map(({ kind, label, note }) => {
          const busy = start.isPending && start.variables === kind;
          return [
            <button
              key={kind}
              ref={(node) => {
                items.current[kind] = node;
              }}
              type="button"
              role="menuitem"
              className={`menu-item ${styles.exportItem}`}
              disabled={start.isPending}
              aria-busy={busy || undefined}
              onClick={() => {
                start.mutate(kind);
              }}
            >
              <span className={styles.exportLines}>
                <span>{t(label)}</span>
                <span className="note">{t(note)}</span>
              </span>
              {busy ? <Ph name="circle-notch" className="spin" /> : null}
            </button>,
            failed === kind ? (
              <p key={`${kind}-error`} className={`note ${styles.exportError}`} role="alert">
                {start.error instanceof ApiError && start.error.status === 413
                  ? t(areaId(board.area) === WORLD ? 'area.exportWorldYear' : 'area.exportTooLarge')
                  : errorText(start.error)}
              </p>
            ) : null,
          ];
        })}
      </PopupMenu>
    </>
  );
}
