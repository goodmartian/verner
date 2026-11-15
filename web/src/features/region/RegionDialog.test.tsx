import { COUNTRIES } from '../../test/regionFixtures';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderI18n } from '../../test/render';
import { RegionDialog } from './RegionDialog';
import { fold } from './search';

function setup(value: string | null = null) {
  const onPick = vi.fn();
  const onClose = vi.fn();
  renderI18n(
    <RegionDialog open onClose={onClose} countries={COUNTRIES} value={value} onPick={onPick} />,
  );
  return { onPick, onClose };
}

describe('RegionDialog', () => {
  it('starts with the countries', () => {
    setup();
    expect(screen.getByRole('dialog', { name: 'Country' })).toBeInTheDocument();
    expect(
      within(screen.getByRole('listbox'))
        .getAllByRole('option')
        .map((b) => b.querySelector('b')?.textContent),
    ).toEqual(['Argentina', 'Brazil', 'Chile']);
  });

  it('picks a country without provinces at once', async () => {
    const { onPick, onClose } = setup();
    await userEvent.click(screen.getByRole('option', { name: 'Brazil' }));
    expect(onPick).toHaveBeenCalledWith(COUNTRIES[1]?.id);
    expect(onClose).toHaveBeenCalled();
  });

  it('opens a second step for a country with provinces, with a visible way back to all countries', async () => {
    setup();
    await userEvent.click(screen.getByRole('option', { name: /^Argentina/ }));
    expect(screen.getByRole('dialog', { name: 'Argentina' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'All countries' })).toHaveTextContent(
      'All countries',
    );
    expect(screen.getByRole('option', { name: 'Whole country' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Salta' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'All countries' }));
    expect(screen.getByRole('dialog', { name: 'Country' })).toBeInTheDocument();
  });

  it('picks a province, or the whole country', async () => {
    const { onPick } = setup();
    await userEvent.click(screen.getByRole('option', { name: /^Argentina/ }));
    await userEvent.click(screen.getByRole('option', { name: 'Corrientes' }));
    expect(onPick).toHaveBeenLastCalledWith(COUNTRIES[0]?.provinces?.[0]?.id);

    await userEvent.click(screen.getByRole('option', { name: /^Argentina/ }));
    await userEvent.click(screen.getByRole('option', { name: 'Whole country' }));
    expect(onPick).toHaveBeenLastCalledWith(COUNTRIES[0]?.id);
  });

  it('searches names in every language, without case and accents', async () => {
    setup();
    await userEvent.type(screen.getByRole('searchbox', { name: 'Country or region' }), 'бразил');
    expect(screen.getByRole('option', { name: 'Brazil' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Chile' })).not.toBeInTheDocument();
  });

  it('searches the provinces on the second step and says when nothing is found', async () => {
    setup();
    await userEvent.click(screen.getByRole('option', { name: /^Argentina/ }));
    const search = screen.getByRole('searchbox', { name: 'Country or region' });
    await userEvent.type(search, 'cordoba');
    expect(screen.getByRole('option', { name: 'Córdoba' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Whole country' })).not.toBeInTheDocument();
    await userEvent.clear(search);
    await userEvent.type(search, 'zzz');
    expect(screen.getByText('Nothing found')).toBeInTheDocument();
  });

  it('opens on the provinces of the country when a province is the current choice', () => {
    setup(COUNTRIES[0]?.provinces?.[1]?.id);
    expect(screen.getByRole('dialog', { name: 'Argentina' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Córdoba' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('button', { name: 'All countries' })).toBeInTheDocument();
  });

  it('marks what is chosen now', () => {
    setup(COUNTRIES[1]?.id);
    expect(screen.getByRole('option', { name: 'Brazil' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('option', { name: 'Chile' })).toHaveAttribute('aria-selected', 'false');
  });

  it('closes on Escape also from the second step', async () => {
    const { onClose } = setup();
    await userEvent.click(screen.getByRole('option', { name: /^Argentina/ }));
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });
});

describe('fold', () => {
  it('drops case, accents and the Russian ё', () => {
    expect(fold(' Córdoba ')).toBe('cordoba');
    expect(fold('Берёза')).toBe('береза');
  });
});
