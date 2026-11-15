import { useI18n } from '../../i18n/context';

/** Which of the places where one band meets the next get a value written under the strip: a few, spread along it. */
export function tickIndexes(places: number, wanted = 4): number[] {
  if (places <= wanted) return Array.from({ length: places }, (_, index) => index);
  const step = (places - 1) / (wanted - 1);
  return Array.from({ length: wanted }, (_, index) => Math.round(index * step));
}

/** A layer's key: its name and unit and the bands of its legend. */
export interface KeyRow {
  id: string;
  title: string;
  unit: string;
  /** How a value that opens a band is written under the strip; plain numbers when absent. */
  format?: (value: number) => string;
  bands: readonly { id: number; low: number; color: string }[];
}

interface LayerKeyProps {
  /** The layers on the map, in the order they are listed. */
  rows: readonly KeyRow[];
  /** What to say instead of the strips when the data has not the hour or the day on screen. */
  missing?: string | null;
  /** The classes of the vegetation around the open fire, when it is on the map. */
  cover?: readonly { id: number; name: string; color: string }[] | null;
}

/** What the colours on the map stand for, small: a strip of the bands of each layer, the dots of the vegetation. */
export function LayerKey({ rows, missing, cover }: LayerKeyProps) {
  const { t, lang } = useI18n();
  const number = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
  if (rows.length === 0 && !cover) return null;
  return (
    <div className="wx-key" role="group" aria-label={t('wx.legend')}>
      {rows.map((row) => (
        <section key={row.id}>
          <h3>
            {row.title} <small>{row.unit}</small>
          </h3>
          {missing ? (
            <p>{missing}</p>
          ) : (
            <div className="wx-strip">
              <span>
                {row.bands.map((band) => (
                  <i key={band.id} style={{ background: band.color }} />
                ))}
              </span>
              {tickIndexes(row.bands.length - 1).map((index) => {
                const band = row.bands[index + 1];
                return band ? (
                  <b
                    key={band.id}
                    style={{ left: `${String(((index + 1) / row.bands.length) * 100)}%` }}
                  >
                    {row.format ? row.format(band.low) : number.format(band.low)}
                  </b>
                ) : null;
              })}
            </div>
          )}
        </section>
      ))}
      {cover ? (
        <section>
          <h3>{t('fires.cover')}</h3>
          <ul className="wx-dots">
            {cover.map((item) => (
              <li key={item.id}>
                <i style={{ background: item.color }} />
                {item.name}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
