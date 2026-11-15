import type { LandCover } from '../../api/types';

type Class = LandCover['classes'][number];
type Grid = Pick<LandCover, 'width' | 'height' | 'data' | 'classes'>;

const rgb = (color: string) =>
  [1, 3, 5].map((offset) => Number.parseInt(color.slice(offset, offset + 2), 16));

/** The grid painted as a picture, one pixel a cell, the classes in their colours; class 0 is left clear. */
export function coverImage(cover: Grid): string {
  const canvas = document.createElement('canvas');
  canvas.width = cover.width;
  canvas.height = cover.height;
  const context = canvas.getContext('2d');
  if (!context) return '';
  const image = context.createImageData(cover.width, cover.height);
  const colors = new Map(cover.classes.map((item) => [item.id, rgb(item.color)]));
  for (let cell = 0; cell < cover.width * cover.height; cell += 1) {
    const color = colors.get(cover.data.charCodeAt(cell) - 48);
    if (color) image.data.set([color[0] ?? 0, color[1] ?? 0, color[2] ?? 0, 255], cell * 4);
  }
  context.putImageData(image, 0, 0);
  return canvas.toDataURL();
}

/** The classes the grid really has more than a hundredth of, the widest first, for the key. */
export function coverKey(cover: Grid): Class[] {
  const counts = new Map<number, number>();
  for (let cell = 0; cell < cover.data.length; cell += 1) {
    const id = cover.data.charCodeAt(cell) - 48;
    counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return cover.classes
    .filter((item) => item.id !== 0 && (counts.get(item.id) ?? 0) > cover.data.length * 0.01)
    .sort((a, b) => (counts.get(b.id) ?? 0) - (counts.get(a.id) ?? 0));
}

const NBSP = '\u00a0';

/** The few classes that make up the ground under the fire, as a line: «Forest 62 %, scrub 21 %». Classes under 1 % are left out, three at most. */
export function coverSummary(
  cover: Pick<LandCover, 'classes' | 'shares'>,
  name: (names: Class['name']) => string,
  lang: string,
): string {
  const whole = new Intl.NumberFormat(lang, { maximumFractionDigits: 0 });
  return cover.shares
    .filter((item) => item.share_pct >= 1)
    .slice(0, 3)
    .flatMap((item, index) => {
      const found = cover.classes.find((one) => one.id === item.id);
      if (!found) return [];
      const text = name(found.name);
      const label =
        index === 0
          ? text.charAt(0).toLocaleUpperCase(lang) + text.slice(1)
          : text.toLocaleLowerCase(lang);
      return [`${label} ${whole.format(item.share_pct)}${NBSP}%`];
    })
    .join(', ');
}
