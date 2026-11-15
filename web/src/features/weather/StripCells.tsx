import type { ReactNode } from 'react';

/** One cell of a strip along the top of the map: a value and what it is. */
export function StripCell({
  value,
  label,
  title,
  drop,
}: {
  value: ReactNode;
  /** One short word; what more there is to say goes in `title`, which shows when the pointer rests on the cell. */
  label: string;
  title?: string;
  drop?: 'rain' | 'dry' | 'lo' | 'xs';
}) {
  return (
    <span className={`fs-i${drop ? ` fs-${drop}` : ''}`} {...(title ? { title } : {})}>
      <b>{value}</b>
      <small>{label}</small>
    </span>
  );
}
