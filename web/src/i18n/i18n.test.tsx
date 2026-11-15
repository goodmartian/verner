import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderI18n } from '../test/render';
import { useI18n } from './context';
import { en } from './en';
import { MESSAGES } from './translate';
import { makeConfig, BROWSER_LANGUAGES } from '../test/configFixtures';
import { resolveLang } from './lang';
import { regionLabel } from './regionLabel';

function Probe() {
  const { t, lang, locale, setPref } = useI18n();
  const filled = t('kpi.rankValue', { n: 20, of: 23 });
  return (
    <>
      <p>{t('tabs.fires')}</p>
      <p data-testid="lang">{lang}</p>
      <p data-testid="locale">{locale}</p>
      <p data-testid="filled">{filled}</p>
      <button
        type="button"
        onClick={() => {
          setPref('ru');
        }}
      >
        ru
      </button>
    </>
  );
}

afterEach(() => {
  document.documentElement.lang = '';
  vi.restoreAllMocks();
});

describe('resolveLang', () => {
  it('takes the explicit choice', () => {
    expect(resolveLang('es', ['ru-RU'], makeConfig().languages)).toBe('es');
  });

  it('follows the system language by its first two letters', () => {
    expect(resolveLang('auto', BROWSER_LANGUAGES, makeConfig().languages)).toBe('fr');
  });

  it('falls back to English', () => {
    expect(resolveLang('auto', ['zz-ZZ'], makeConfig().languages)).toBe('en');
  });
});

describe('messages', () => {
  it.each(Object.entries(MESSAGES))(
    '%s says everything English says, in its own words',
    (_, messages) => {
      expect(Object.keys(messages).sort()).toEqual(Object.keys(en).sort());
      for (const [key, text] of Object.entries(messages)) {
        expect(text, key).not.toBe('');
        const placeholders = (value: string) =>
          [...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
        expect(placeholders(text), key).toEqual(placeholders(en[key as keyof typeof en]));
      }
    },
  );
});

describe('I18nProvider', () => {
  it('auto-picks French from navigator.languages only when config enables it, with its locale', () => {
    localStorage.removeItem('senda-lang');
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(BROWSER_LANGUAGES);
    renderI18n(<Probe />);
    expect(screen.getByText('Feux')).toBeInTheDocument();
    expect(screen.getByTestId('locale')).toHaveTextContent('fr-CA');
  });

  it('respects the configured set when the stored language is no longer enabled', () => {
    localStorage.setItem('senda-lang', 'ru');
    const config = makeConfig();
    renderI18n(<Probe />, {
      ...config,
      languages: config.languages.filter((item) => item.code === 'fr'),
    });
    expect(screen.getByTestId('lang')).toHaveTextContent('fr');
  });
  it('switches the language, remembers it and sets the page language', async () => {
    renderI18n(<Probe />);
    await userEvent.click(screen.getByRole('button', { name: 'ru' }));
    expect(screen.getByText('Пожары')).toBeInTheDocument();
    expect(screen.getByTestId('lang')).toHaveTextContent('ru');
    expect(document.documentElement.lang).toBe('ru');
    expect(localStorage.getItem('senda-lang')).toBe('ru');
  });

  it('starts with the remembered language', () => {
    localStorage.setItem('senda-lang', 'es');
    renderI18n(<Probe />);
    expect(screen.getByText('Incendios')).toBeInTheDocument();
  });

  it('puts values into the {places} of a message', () => {
    renderI18n(<Probe />);
    expect(screen.getByTestId('filled')).toHaveTextContent('20 of 23');
  });
});

describe('region type words', () => {
  it('uses the API label and its requested form, otherwise the generic word', () => {
    expect(
      regionLabel(
        { type_label: { fr: { one: 'district', other: 'districts' } } },
        'fr',
        'other',
        'régions',
      ),
    ).toBe('districts');
    expect(
      regionLabel(
        { type_label: { fr: { one: 'district', other: 'districts' } } },
        'fr',
        'one',
        'régions',
      ),
    ).toBe('district');
    expect(regionLabel({}, 'fr', 'other', 'régions')).toBe('régions');
  });
});
