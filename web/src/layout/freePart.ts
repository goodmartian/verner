export const GAP = 12;

/** A panel as it stands when it is open: where it ends, and how low it reaches. */
export interface PanelBox {
  right: number;
  bottom: number;
}

interface Window {
  width: number;
  height: number;
  /** height of the strip at the bottom where the toolbar, the player and the line of the chat stand */
  strip: number;
}

export interface FreePart {
  /** the middle of the part of the map the panels leave free */
  centre: number;
  /** its width, without the gaps */
  room: number;
}

/** The strip along the bottom is everything that stands there: the line of the chat, the toolbar and the open player, a gap between them. */
export function stripHeight(parts: { foot: number; tools: number; player: number }): number {
  return (
    parts.foot +
    (parts.tools > 0 ? parts.tools + GAP : 0) +
    (parts.player > 0 ? parts.player + GAP : 0)
  );
}

/**
 * The part of the map that the panels leave free along the bottom of the window. Only a panel that reaches the strip
 * where the tools stand takes room from them: a short list ends above it and is no hindrance, a panel of the chat
 * runs the whole height and always is one. The boxes are the open ones, not the ones a panel is still sliding through.
 */
export function freePart(win: Window, panels: readonly PanelBox[]): FreePart {
  const top = win.height - win.strip - GAP * 2;
  const edge = Math.max(
    0,
    ...panels.filter((panel) => panel.bottom > top).map((panel) => panel.right + GAP),
  );
  if (edge === 0) return { centre: win.width / 2, room: win.width - GAP * 2 };
  const room = win.width - GAP - edge;
  return { centre: edge + room / 2, room };
}
