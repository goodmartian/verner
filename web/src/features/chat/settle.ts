/** Counts the places `mark` stands in `text`, not overlapping. */
const count = (text: string, mark: string) => text.split(mark).length - 1;

const removeLast = (text: string, mark: string, from = text.length) => {
  const at = text.lastIndexOf(mark, from);
  return at === -1 ? text : text.slice(0, at) + text.slice(at + mark.length);
};

/** Whether the star at `at` stands first on its line and is followed by a space: the bullet of a list. */
const beginsItem = (text: string, at: number) =>
  text.slice(text.lastIndexOf('\n', at - 1) + 1, at).trim() === '' && /\s/.test(text[at + 1] ?? '');

/**
 * The text of an answer that is still coming, without its unclosed marks: `**Многолетн` is shown as `Многолетн`, with
 * no asterisks, until the closing ones come and the words turn bold. Only the last paragraph can be open.
 */
export function settle(text: string): string {
  const cut = text.lastIndexOf('\n\n') + 2;
  const head = text.slice(0, cut > 1 ? cut : 0);
  let tail = text.slice(head.length);
  if (count(tail, '`') % 2 === 1) tail = removeLast(tail, '`');
  if (count(tail, '**') % 2 === 1) tail = removeLast(tail, '**');
  // single stars open and close an emphasis; the one that begins a list item is not a mark
  const stars = [...tail.matchAll(/(?<!\*)\*(?!\*)/g)].filter(
    (found) => !beginsItem(tail, found.index),
  );
  if (stars.length % 2 === 1) {
    const last = stars.at(-1);
    if (last) tail = tail.slice(0, last.index) + tail.slice(last.index + 1);
  }
  // a link that is not yet whole shows its words only
  tail = tail.replace(/\[([^\]]*)\]\([^)]*$/, '$1').replace(/\[([^\]]*)$/, '$1');
  return head + tail;
}

const LIST_ITEM = /^\s*(?:[-*+]|\d+[.)])\s/;

/**
 * The paragraphs of a text, the unit that is drawn once and kept: a blank line parts them, except that the items of a
 * list that has blank lines between them stay in one block (or a numbered list would count from one again).
 */
export function splitBlocks(text: string): string[] {
  const blocks: string[] = [];
  for (const part of text.split(/\n{2,}/)) {
    const last = blocks.at(-1);
    if (
      last !== undefined &&
      LIST_ITEM.test(part) &&
      LIST_ITEM.test(last.split('\n').at(-1) ?? '')
    ) {
      blocks[blocks.length - 1] = `${last}\n\n${part}`;
    } else {
      blocks.push(part);
    }
  }
  return blocks;
}
