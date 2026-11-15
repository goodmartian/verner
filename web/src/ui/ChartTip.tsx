import styles from './ChartTip.module.css';

/** Width of the card; a chart keeps it inside its own box with `tipLeft`. */
const WIDTH = 148;

/** Where the card stands: right of the point, kept inside a box of the given width. */
export const tipLeft = (at: number, box: number) => Math.min(box - WIDTH, Math.max(0, at + 12));

/**
 * The card that names the figure under the pointer of a chart: the first line is the name, the others say what it is.
 * It stands at the top of its box, or at `top`; with `above` its bottom edge is there.
 */
export function ChartTip({
  left,
  top,
  above,
  lines,
}: {
  left: number;
  top?: number;
  above?: boolean;
  lines: readonly string[];
}) {
  const [name, ...rest] = lines;
  return (
    <div
      className={styles.tip}
      data-above={above ? 'on' : undefined}
      style={{ left, top }}
      role="status"
    >
      <b>{name}</b>
      {rest.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </div>
  );
}
