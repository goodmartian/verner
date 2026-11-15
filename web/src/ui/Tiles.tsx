import type { ReactNode } from 'react';
import { useAskPop, type AskInfo } from './AskPop';
import styles from './Tiles.module.css';

export interface TileData {
  key: string;
  label: string;
  big: ReactNode;
  sub?: string;
  tone?: 'more';
  /** The tile takes the whole row. */
  wide?: boolean;
  /** The card the tile opens on a rest of the pointer or a press: the figure and «Спросить ИИ». */
  ask?: AskInfo | null;
}

/** The figures of a board as tiles: the label, the number, the caption under it. */
export function Tiles({ items, id }: { items: readonly TileData[]; id?: string }) {
  const pop = useAskPop();
  return (
    <div className={styles.tiles} id={id}>
      {items.map((tile) => {
        const body = (
          <>
            <span>{tile.label}</span>
            <b
              key={typeof tile.big === 'object' ? undefined : String(tile.big)}
              data-tone={tile.tone}
            >
              {tile.big}
            </b>
            {tile.sub === undefined ? null : <small>{tile.sub}</small>}
          </>
        );
        const className = tile.wide ? `${styles.tile} ${styles.wide}` : styles.tile;
        return tile.ask ? (
          <button key={tile.key} type="button" className={className} {...pop.bind(tile.ask)}>
            {body}
          </button>
        ) : (
          <div key={tile.key} className={className}>
            {body}
          </div>
        );
      })}
      {pop.card}
    </div>
  );
}
