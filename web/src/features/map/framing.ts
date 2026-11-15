export interface MapPadding {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

// what is left of the map's width and height for the region, at least
const MIN_SHARE = 0.4;

/** The room taken around the map, scaled down when the window is too small to leave the region a share of it. */
export function fitPadding(padding: MapPadding, width: number, height: number): MapPadding {
  const down = (taken: number, size: number) => {
    const room = size * (1 - MIN_SHARE);
    return taken > room ? room / taken : 1;
  };
  const vertical = down(padding.top + padding.bottom, height);
  const horizontal = down(padding.left + padding.right, width);
  return {
    top: Math.floor(padding.top * vertical),
    bottom: Math.floor(padding.bottom * vertical),
    left: Math.floor(padding.left * horizontal),
    right: Math.floor(padding.right * horizontal),
  };
}
