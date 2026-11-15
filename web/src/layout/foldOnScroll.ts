/** The board has to leave the top by this much before the chat line folds into a pill. */
export const FOLD_AT = 16;
/** It opens again only back at the very top: the gap between the two keeps it from flickering at one edge. */
export const OPEN_AT = 4;

/**
 * Whether the line of the folded chat stands as a pill over a board scrolled this far. Only the scroll is decided here;
 * focus, text, attachments and a running answer keep the full line in the stylesheet.
 */
export function folded(was: boolean, top: number): boolean {
  return was ? top > OPEN_AT : top > FOLD_AT;
}
