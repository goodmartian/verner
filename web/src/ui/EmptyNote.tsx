import { Ph, type PhName } from './Ph';

/** A way out of a place with nothing to show: where to go, and the button that takes the person there. */
export interface EmptyAction {
  label: string;
  run: () => void;
}

/**
 * A place with nothing to show: a plain sentence of what is missing and one or two buttons to a place that has it.
 * In a list it is a row of the list (`as="li"`); elsewhere it is a status the screen reader says.
 * When it is all there is in its place (the whole board, the whole list) it is `wide`: the icon of the reason over the
 * sentence, in the middle of the place with room around it. Elsewhere (over the figures, in the menu of layers) it stays a line.
 */
export function EmptyNote({
  text,
  actions = [],
  as: Tag = 'div',
  icon,
  wide = false,
}: {
  text: string;
  actions?: readonly EmptyAction[];
  as?: 'div' | 'li';
  /** The reason in a picture, shown only when the note is `wide`. */
  icon?: PhName;
  wide?: boolean;
}) {
  return (
    <Tag
      className="empty-note"
      data-wide={wide || undefined}
      role={Tag === 'div' ? 'status' : undefined}
    >
      {wide && icon ? <Ph name={icon} className="empty-icon" /> : null}
      <p>{text}</p>
      {actions.length > 0 ? (
        <span className="empty-acts">
          {actions.map((action) => (
            <button
              key={action.label}
              type="button"
              className="btn btn-secondary"
              onClick={action.run}
            >
              {action.label}
            </button>
          ))}
        </span>
      ) : null}
    </Tag>
  );
}
