import { useEffect, useRef, useState, type RefObject } from 'react';

/** How near the bottom counts as at it, in pixels. */
export const NEAR = 40;

export const isNearBottom = (
  box: Pick<HTMLElement, 'scrollHeight' | 'scrollTop' | 'clientHeight'>,
) => box.scrollHeight - box.scrollTop - box.clientHeight <= NEAR;

const scrollToEnd = (element: HTMLElement) => {
  element.scrollTop = element.scrollHeight;
};

/**
 * Keeps a scrolling box at its bottom while its content grows, but only if the person is at the bottom already: a
 * person who has scrolled up is left alone, and `atBottom` tells that a way back is wanted. No smooth scrolling and no
 * scrolling for each piece of text: the box follows when it is measured to have grown. When `resetKey` changes (a
 * question was asked, a chat was opened) it goes to the bottom whatever the person was doing.
 */
export function useStickToBottom(box: RefObject<HTMLElement | null>, resetKey: unknown) {
  const [atBottom, setAtBottom] = useState(true);
  const pinned = useRef(true);

  useEffect(() => {
    const element = box.current;
    if (!element) return;
    let frame = 0;
    const follow = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (pinned.current) scrollToEnd(element);
      });
    };
    const onScroll = () => {
      const near = isNearBottom(element);
      pinned.current = near;
      setAtBottom(near);
    };
    const resize = new ResizeObserver(follow);
    const watch = () => {
      resize.disconnect();
      for (const child of element.children) resize.observe(child);
    };
    // the children come and go with the messages; the text inside them grows without anything being resized
    const mutation = new MutationObserver((records) => {
      if (records.some((record) => record.type === 'childList' && record.target === element))
        watch();
      follow();
    });
    watch();
    mutation.observe(element, { childList: true, subtree: true, characterData: true });
    element.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutation.disconnect();
      element.removeEventListener('scroll', onScroll);
    };
  }, [box]);

  useEffect(() => {
    pinned.current = true;
    if (box.current) scrollToEnd(box.current);
  }, [box, resetKey]);

  /** Goes to the bottom and stays there: the way down. */
  const toBottom = () => {
    const element = box.current;
    if (!element) return;
    pinned.current = true;
    setAtBottom(true);
    scrollToEnd(element);
  };

  return { atBottom, toBottom };
}
