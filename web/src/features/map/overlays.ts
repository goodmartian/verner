/** A tile of the overlays in the layers menu: what it is called, the colours of its legend as the picture, whether it is on. */
export interface OverlayCard {
  id: string;
  label: string;
  gradient: string;
  on: boolean;
}

/** The picture of a tile: the colours of the bands of a legend, corner to corner. */
export const gradientOf = (colors: readonly string[]): string =>
  `linear-gradient(135deg, ${colors.join(', ')})`;
