import {
  useEffect,
  useLayoutEffect,
  useRef,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from 'react';
import { createPortal } from 'react-dom';
import { cx } from '../lib/cx';

interface PopupMenuProps {
  /** The button it opens from; the menu hangs under it, or over it when the button is in the lower half. */
  anchor: RefObject<HTMLElement | null>;
  open: boolean;
  onClose: () => void;
  className?: string;
  /** Which edge of the button the menu lines up with. */
  align?: 'start' | 'end';
  /** Forces the menu above (true) or below (false) the button. */
  up?: boolean;
  role?: string;
  label?: string;
  id?: string;
  children: ReactNode;
}

/** A menu in the stylesheet's `.menu`: set at the button's edge, closed by a click elsewhere or Escape. */
export function PopupMenu({
  anchor,
  open,
  onClose,
  className,
  align = 'start',
  up,
  role = 'menu',
  label,
  id,
  children,
}: PopupMenuProps) {
  const box = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const menu = box.current;
    const rect = anchor.current?.getBoundingClientRect();
    if (!open || !menu || !rect) return;
    const width = menu.offsetWidth;
    const above = up ?? rect.top > innerHeight / 2;
    const left = align === 'end' ? rect.right - width : rect.left;
    menu.style.left = `${String(Math.round(Math.max(8, Math.min(innerWidth - width - 8, left))))}px`;
    menu.style.top = above ? 'auto' : `${String(Math.round(rect.bottom + 6))}px`;
    menu.style.bottom = above ? `${String(Math.round(innerHeight - rect.top + 6))}px` : 'auto';
    // it opens out of the corner that touches its button
    menu.style.transformOrigin = `${align === 'end' ? 'right' : 'left'} ${above ? 'bottom' : 'top'}`;
  }, [open, anchor, align, up]);

  useEffect(() => {
    if (!open) return;
    const down = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!box.current?.contains(target) && !anchor.current?.contains(target)) onClose();
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('pointerdown', down);
    document.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('pointerdown', down);
      document.removeEventListener('keydown', key);
    };
  }, [open, anchor, onClose]);

  if (!open) return null;
  const style: CSSProperties = {};
  return createPortal(
    <div
      ref={box}
      id={id}
      className={cx('menu', className)}
      role={role}
      aria-label={label}
      style={style}
    >
      {children}
    </div>,
    document.body,
  );
}
