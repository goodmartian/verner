import { describe, expect, it } from 'vitest';
import { freePart, stripHeight } from './freePart';

// 1440 by 900; the foot (player and tools) is 60 high, so the strip starts at 816
const win = { width: 1440, height: 900, strip: 60 };
const shortList = { right: 401, bottom: 182 };
const longList = { right: 401, bottom: 888 };
const chatPanel = { right: 401, bottom: 888 };
const wideChatPanel = { right: 617, bottom: 888 };

describe('freePart', () => {
  it('centres on the window while the list is short and nothing else is open', () => {
    expect(freePart(win, [shortList])).toEqual({ centre: 720, room: 1416 });
  });

  it('centres on the map beside a long list', () => {
    expect(freePart(win, [longList])).toEqual({ centre: 920.5, room: 1015 });
  });

  it('centres on the map beside the panel of the chat even when the list above it is short', () => {
    expect(freePart(win, [shortList, chatPanel])).toEqual({ centre: 920.5, room: 1015 });
  });

  it('follows the wide panel of the chat', () => {
    expect(freePart(win, [shortList, wideChatPanel])).toEqual({ centre: 1028.5, room: 799 });
  });

  it('takes the panel that reaches farthest', () => {
    expect(freePart(win, [longList, wideChatPanel]).centre).toBe(1028.5);
  });
});

describe('the strip along the bottom', () => {
  it('is the line of the chat, the toolbar and the player with a gap between them', () => {
    expect(stripHeight({ foot: 70, tools: 46, player: 0 })).toBe(128);
    expect(stripHeight({ foot: 70, tools: 46, player: 82 })).toBe(222);
    expect(stripHeight({ foot: 70, tools: 0, player: 0 })).toBe(70);
  });

  it('makes a list that ends under the top of the open player a hindrance to it', () => {
    // the list ends at 715 and the player starts at 636: with only the toolbar and the chat in the strip the list is "short"
    const list = { right: 401, bottom: 715 };
    const without = freePart(
      { width: 1440, height: 900, strip: stripHeight({ foot: 70, tools: 46, player: 0 }) },
      [list],
    );
    expect(without.centre).toBe(720);
    const strip = stripHeight({ foot: 70, tools: 46, player: 82 });
    expect(freePart({ width: 1440, height: 900, strip }, [list])).toEqual({
      centre: 920.5,
      room: 1015,
    });
  });
});
