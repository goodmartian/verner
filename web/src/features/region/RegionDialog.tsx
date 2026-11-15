import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useI18n } from '../../i18n/context';
import { localName } from '../../i18n/lang';
import { regionLabel } from '../../i18n/regionLabel';
import type { Names, TypeLabel } from '../../config/types';
import { Ph } from '../../ui/Ph';
import { fold } from './search';

export interface RegionItem {
  id: string;
  names: Names;
  typeLabel?: TypeLabel;
  /** How many fires are in the region now. */
  firesNow?: number;
  kind?: string;
  /** The country of a region, named under it in search results. */
  countryId?: string;
}

export interface CountryItem extends RegionItem {
  /** A country with provinces opens a second step; any other is chosen at once. */
  provinces?: readonly RegionItem[];
}

interface RegionDialogProps {
  open: boolean;
  onClose: () => void;
  countries: readonly CountryItem[];
  /** The chosen country or province. */
  value: string | null;
  onPick: (id: string) => void | Promise<void>;
  /** Each region says how many fires it has: shown on the fires screen. */
  showFires?: boolean;
  /** Areas drawn on the map that the calendar can show, listed first on the country step. */
  areas?: readonly { id: string; name: string }[];
  results?: readonly RegionItem[];
  onSearch?: (query: string, country?: string) => void;
  searchNote?: string;
}

/** Two steps: the country, then (for a country with provinces) the whole country or one province. */
export function RegionDialog({
  open,
  onClose,
  countries,
  value,
  onPick,
  showFires = false,
  areas = [],
  results,
  onSearch,
  searchNote,
}: RegionDialogProps) {
  const { t, lang } = useI18n();
  // opens on the step of the current choice: a province shows the provinces of its country
  const [country, setCountry] = useState<CountryItem | null>(
    () =>
      countries.find((item) => item.provinces?.some((province) => province.id === value)) ?? null,
  );
  const [query, setQuery] = useState('');
  const search = useRef<HTMLInputElement>(null);

  const items: readonly RegionItem[] = country?.provinces ?? countries;
  const shown = useMemo(() => {
    const needle = fold(query);
    return (
      results ??
      items.filter((item) => Object.values(item.names).some((name) => fold(name).includes(needle)))
    );
  }, [items, query, results]);

  useEffect(() => {
    if (open) onSearch?.(query, country?.id);
  }, [open, query, country?.id, onSearch]);

  const close = useCallback(() => {
    setCountry(null);
    setQuery('');
    onClose();
  }, [onClose]);
  const pick = async (id: string) => {
    try {
      await onPick(id);
      close();
    } catch {
      // The container displays the failed selection; keep the dialog open to retry.
    }
  };
  const choose = (item: CountryItem) => {
    if (item.provinces) {
      setCountry(item);
      setQuery('');
    } else {
      void pick(item.id);
    }
  };

  useEffect(() => {
    if (open) search.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    document.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('keydown', key);
    };
  }, [open, close]);

  if (!open) return null;
  const nameOf = (id: string) => {
    const found = countries.find((candidate) => candidate.id === id);
    return found ? localName(found.names, lang) : undefined;
  };
  const item = (id: string, name: string, more: boolean, firesNow = 0, note = '') => (
    <button
      key={id}
      type="button"
      className="menu-item region-item"
      role="option"
      aria-selected={value === id}
      onClick={() => {
        const full =
          countries.find((candidate) => candidate.id === id) ??
          results?.find((candidate) => candidate.id === id);
        if (more && full) choose({ provinces: [], ...full });
        else void pick(id);
      }}
    >
      <span>
        <b>{name}</b>
        {note ? <small>{note}</small> : null}
      </span>
      <span className="cnt">
        {showFires && firesNow > 0 ? t('fires.count', { n: firesNow }) : ''}
      </span>
      <Ph name={more ? 'caret-right' : 'check'} className={more ? undefined : 'ph-check'} />
    </button>
  );
  return createPortal(
    <div
      className="scrim"
      id="region-dlg"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="h-region">
        <header className="dlg-head">
          {country ? (
            <button
              type="button"
              className="btn btn-secondary"
              id="region-back"
              onClick={() => {
                setCountry(null);
                setQuery('');
              }}
            >
              <Ph name="caret-left" />
              {t('region.allCountries')}
            </button>
          ) : null}
          <h2 id="h-region">{country ? localName(country.names, lang) : t('region.country')}</h2>
          <button
            type="button"
            className="icon-btn"
            id="region-x"
            aria-label={t('common.close')}
            onClick={close}
          >
            <Ph name="x" />
          </button>
        </header>
        <p className="dlg-sub">
          {country
            ? regionLabel(
                { type_label: country.provinces?.find((item) => item.typeLabel)?.typeLabel },
                lang,
                'other',
                t('region.regions'),
              )
            : t('region.sub')}
        </p>
        <div className="search">
          <Ph name="magnifying-glass" />
          <label htmlFor="region-q" className="visually-hidden">
            {t('region.search')}
          </label>
          <input
            ref={search}
            id="region-q"
            type="search"
            autoComplete="off"
            placeholder={t('region.search')}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
          />
        </div>
        <div className="dlg-list" id="region-list" role="listbox" aria-labelledby="h-region">
          {!country
            ? areas
                .filter((area) => fold(area.name).includes(fold(query)))
                .map((area) => item(area.id, area.name, false))
            : null}
          {country && !query ? item(country.id, t('region.whole'), false, country.firesNow) : null}
          {shown.map((entry) =>
            item(
              entry.id,
              localName(entry.names, lang),
              countries.find((c) => c.id === entry.id)?.provinces !== undefined ||
                (!country && entry.kind === 'country'),
              entry.firesNow,
              countries.find((c) => c.id === entry.id)?.provinces && !country
                ? t('region.fullData')
                : [
                    entry.typeLabel?.[lang]?.one,
                    !country && entry.kind !== 'country' && entry.countryId
                      ? nameOf(entry.countryId)
                      : undefined,
                  ]
                    .filter(Boolean)
                    .join(' · '),
            ),
          )}
          {searchNote ? (
            <p className="note" role="status">
              {searchNote}
            </p>
          ) : shown.length === 0 ? (
            <p className="note">{t('region.notFound')}</p>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  );
}
