export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

const GAP = 14;
const EDGE = 8;

const holds = (box: Box, point: { x: number; y: number }) =>
  point.x >= box.left && point.x <= box.right && point.y >= box.top && point.y <= box.bottom;

const meets = (a: Box, b: Box) =>
  a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

/** The corner of the card that sits at the given point: `flipX` the right one, `flipY` the lower one. */
export interface TipPlace {
  left: number;
  top: number;
  flipX: boolean;
  flipY: boolean;
}

/**
 * Where the card of the pointer goes in an area `width` by `height`: below and right of the pointer,
 * else below and left, above and right, above and left — the first that stays inside the area and clear of the `blocked` boxes
 * (the strip of the fire, the player, the tools) and off the pointer. When none is clear the first. `size` is the most the card can take.
 */
export function placeTip(
  point: { x: number; y: number },
  size: { width: number; height: number },
  area: { width: number; height: number },
  blocked: readonly Box[],
): TipPlace {
  const sides = [
    [false, false],
    [true, false],
    [false, true],
    [true, true],
  ] as const;
  const places = sides.map(([flipX, flipY]): TipPlace => {
    const left = flipX ? point.x - GAP : point.x + GAP;
    const top = flipY ? point.y - GAP : point.y + GAP;
    return {
      flipX,
      flipY,
      left: flipX
        ? Math.min(Math.max(left, size.width + EDGE), area.width - EDGE)
        : Math.max(EDGE, Math.min(left, area.width - size.width - EDGE)),
      top: flipY
        ? Math.min(Math.max(top, size.height + EDGE), area.height - EDGE)
        : Math.max(EDGE, Math.min(top, area.height - size.height - EDGE)),
    };
  });
  const boxOf = (place: TipPlace): Box => ({
    left: place.flipX ? place.left - size.width : place.left,
    top: place.flipY ? place.top - size.height : place.top,
    right: place.flipX ? place.left : place.left + size.width,
    bottom: place.flipY ? place.top : place.top + size.height,
  });
  // a place that has been moved in from the edge may have come to lie over the pointer itself: that is not a place
  const clear = places.find(
    (place) => !holds(boxOf(place), point) && blocked.every((other) => !meets(boxOf(place), other)),
  );
  return clear ?? places[0] ?? { left: EDGE, top: EDGE, flipX: false, flipY: false };
}
