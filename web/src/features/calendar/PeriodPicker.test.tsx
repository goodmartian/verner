import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderI18n } from '../../test/render';
import { PeriodPicker } from './PeriodPicker';

const LIMITS = { from: '2003-01', to: '2027-03' };
const PRESETS = [
  { id: '2025', kind: 'year', label: '2025', from: '2025-01', to: '2025-12' },
  { id: '2024', kind: 'year', label: '2024', from: '2024-01', to: '2024-12' },
  {
    id: 'forecast',
    kind: 'forecast',
    label: 'Forecast, next 6 months',
    from: '2026-10',
    to: '2027-03',
  },
];
const RECORD = { from: '2003-01', to: '2026-09' };

function setup(range = { from: '2026-10', to: '2027-03' }) {
  const onChange = vi.fn();
  renderI18n(
    <PeriodPicker
      label="Forecast, Oct 2026 – Mar 2027"
      range={range}
      limits={LIMITS}
      forecast={{ from: '2026-10', to: '2027-03' }}
      record={RECORD}
      presets={PRESETS}
      onChange={onChange}
    />,
  );
  return onChange;
}

const open = () => userEvent.click(screen.getByRole('button', { name: /Forecast, Oct 2026/ }));
const grid = () => screen.getByRole('dialog', { name: 'Period' });

describe('PeriodPicker', () => {
  it('shows the period on its button and opens a menu with presets, years left to the grid', async () => {
    setup();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await open();
    const chips = [...grid().querySelectorAll('.pp-chip')];
    // short words on the buttons, the whole period as their names; no year presets
    expect(chips.map((item) => item.textContent)).toEqual(['All years', 'Forecast']);
    expect(chips.map((item) => item.getAttribute('aria-label'))).toEqual([
      'All years, 2003–2026',
      'Forecast, next 6 months',
    ]);
    expect(within(grid()).queryByRole('button', { name: '2025' })).not.toBeInTheDocument();
    expect(within(grid()).getByRole('button', { name: 'Forecast, next 6 months' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(within(grid()).getByRole('button', { name: 'All years, 2003–2026' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('explains the forecast in the hint while the focus is on its button', async () => {
    setup();
    await open();
    const chip = within(grid()).getByRole('button', { name: 'Forecast, next 6 months' });
    expect(chip).toHaveAccessibleDescription(
      'Forecast, next 6 months: an estimate from past years, not a measurement',
    );
    act(() => {
      chip.focus();
    });
    expect(screen.getByRole('status')).toHaveTextContent('estimate');
    act(() => {
      chip.blur();
    });
    expect(screen.getByRole('status')).toHaveTextContent('Click the first month, then the last');
  });

  it('leads back to all the years in one press', async () => {
    const onChange = setup({ from: '2024-01', to: '2024-12' });
    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'All years, 2003–2026' }));
    expect(onChange).toHaveBeenCalledWith(null);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('presses all the years, and only them, while all of them are shown', async () => {
    setup(RECORD);
    await open();
    const pressed = [...grid().querySelectorAll('.pp-chip[aria-pressed="true"]')];
    expect(pressed.map((item) => item.getAttribute('aria-label'))).toEqual([
      'All years, 2003–2026',
    ]);
  });

  it('opens the month grid on the year the period ends in', async () => {
    setup({ from: '2025-01', to: '2025-12' });
    await userEvent.click(screen.getByRole('button', { name: /Forecast, Oct 2026/ }));
    expect(within(grid()).getByRole('button', { name: 'Choose a year' })).toHaveTextContent('2025');
  });

  it('picks a preset and closes', async () => {
    const onChange = setup({ from: '2025-01', to: '2025-12' });
    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'Forecast, next 6 months' }));
    expect(onChange).toHaveBeenCalledWith({ from: '2026-10', to: '2027-03' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  const yearGrid = () => within(screen.getByRole('group', { name: 'Choose a year' }));

  it('opens the years of the data from the year in the header', async () => {
    setup();
    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'Choose a year' }));
    expect(
      yearGrid()
        .getAllByRole('button')
        .map((item) => item.textContent),
    ).toEqual(Array.from({ length: 25 }, (_, i) => String(2003 + i)));
    expect(within(grid()).getByRole('button', { name: 'Years' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    // 2027 has only its months of the data, all of them in the period; 2026 has only its last three
    expect(yearGrid().getByRole('button', { name: '2027' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(yearGrid().getByRole('button', { name: '2026' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(yearGrid().getByRole('button', { name: '2027' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(within(grid()).getByRole('button', { name: 'Choose a year' })).toHaveTextContent(
      '2003–2027',
    );
    expect(within(grid()).getByRole('button', { name: 'Previous year' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Click the first year, then the last');
  });

  it('switches between months and years', async () => {
    setup();
    await open();
    expect(within(grid()).getByRole('button', { name: 'Months' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await userEvent.click(within(grid()).getByRole('button', { name: 'Years' }));
    expect(yearGrid().getAllByRole('button')).toHaveLength(25);
    await userEvent.click(within(grid()).getByRole('button', { name: 'Months' }));
    expect(screen.queryByRole('group', { name: 'Choose a year' })).not.toBeInTheDocument();
    expect(within(grid()).getByTitle('2027-02, forecast')).toBeInTheDocument();
  });

  it('picks a span of years in two clicks, in either order, and closes', async () => {
    const onChange = setup();
    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'Years' }));
    await userEvent.click(yearGrid().getByRole('button', { name: '2005' }));
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.hover(yearGrid().getByRole('button', { name: '2007' }));
    expect(yearGrid().getByRole('button', { name: '2006' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await userEvent.click(yearGrid().getByRole('button', { name: '2010' }));
    expect(onChange).toHaveBeenLastCalledWith({ from: '2005-01', to: '2010-12' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'Years' }));
    await userEvent.click(yearGrid().getByRole('button', { name: '2010' }));
    await userEvent.click(yearGrid().getByRole('button', { name: '2005' }));
    expect(onChange).toHaveBeenLastCalledWith({ from: '2005-01', to: '2010-12' });
  });

  it('picks one year with two clicks on it, cut to the months of the data', async () => {
    const onChange = setup();
    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'Years' }));
    await userEvent.click(yearGrid().getByRole('button', { name: '2008' }));
    await userEvent.click(yearGrid().getByRole('button', { name: '2008' }));
    expect(onChange).toHaveBeenLastCalledWith({ from: '2008-01', to: '2008-12' });
    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'Years' }));
    await userEvent.click(yearGrid().getByRole('button', { name: '2027' }));
    await userEvent.click(yearGrid().getByRole('button', { name: '2027' }));
    expect(onChange).toHaveBeenLastCalledWith({ from: '2027-01', to: '2027-03' });
  });

  it('picks a whole year from the months, cut to the months of the data, and closes', async () => {
    const onChange = setup();
    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'All of 2027' }));
    expect(onChange).toHaveBeenLastCalledWith({ from: '2027-01', to: '2027-03' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps the first month through a change of year and of view, until the menu closes', async () => {
    const onChange = setup({ from: '2005-01', to: '2005-12' });
    await open();
    await userEvent.click(within(grid()).getByTitle('2005-03'));
    await userEvent.click(within(grid()).getByRole('button', { name: 'Next year' }));
    await userEvent.click(within(grid()).getByRole('button', { name: 'Years' }));
    await userEvent.click(within(grid()).getByRole('button', { name: 'Months' }));
    expect(screen.getByRole('status')).toHaveTextContent('Now the last month');
    for (let i = 0; i < 4; i += 1) {
      await userEvent.click(within(grid()).getByRole('button', { name: 'Next year' }));
    }
    await userEvent.click(within(grid()).getByTitle('2010-08'));
    expect(onChange).toHaveBeenLastCalledWith({ from: '2005-03', to: '2010-08' });

    await open();
    await userEvent.click(within(grid()).getByTitle('2005-03'));
    await userEvent.keyboard('{Escape}');
    await open();
    expect(screen.getByRole('status')).toHaveTextContent('Click the first month, then the last');
  });

  it('takes the first month and then the last, whichever comes first', async () => {
    const onChange = setup({ from: '2026-01', to: '2026-12' });
    await open();
    expect(screen.getByRole('status')).toHaveTextContent('Click the first month, then the last');
    await userEvent.click(within(grid()).getByTitle('2026-05'));
    expect(screen.getByRole('status')).toHaveTextContent('Now the last month');
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(within(grid()).getByTitle('2026-02'));
    expect(onChange).toHaveBeenCalledWith({ from: '2026-02', to: '2026-05' });
  });

  it('picks a quarter and a whole year', async () => {
    const onChange = setup({ from: '2025-01', to: '2025-12' });
    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'Q3' }));
    expect(onChange).toHaveBeenLastCalledWith({ from: '2025-07', to: '2025-09' });
    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'All of 2025' }));
    expect(onChange).toHaveBeenLastCalledWith({ from: '2025-01', to: '2025-12' });
  });

  it('turns months outside the data off and marks forecast months', async () => {
    setup();
    await open();
    expect(within(grid()).getByTitle('2027-04')).toBeDisabled();
    expect(within(grid()).getByTitle('2027-02, forecast')).toBeEnabled();
  });

  it('goes through the years of the grid', async () => {
    setup();
    await open();
    await userEvent.click(within(grid()).getByRole('button', { name: 'Previous year' }));
    expect(within(grid()).getByRole('button', { name: 'Choose a year' })).toHaveTextContent('2026');
  });

  it('steps by the length of the period with its own arrows, and stops at the end of the data', async () => {
    const onChange = setup({ from: '2025-01', to: '2025-12' });
    await userEvent.click(screen.getByRole('button', { name: 'Earlier' }));
    expect(onChange).toHaveBeenCalledWith({ from: '2024-01', to: '2024-12' });
    await userEvent.click(screen.getByRole('button', { name: 'Later' }));
    expect(onChange).toHaveBeenCalledWith({ from: '2026-01', to: '2026-12' });
  });

  it('turns the arrow off when there is nothing further', () => {
    setup({ from: '2027-01', to: '2027-03' });
    expect(screen.getByRole('button', { name: 'Later' })).toBeDisabled();
  });

  it('has no step from the whole record: the one month ahead would not lead back', () => {
    renderI18n(
      <PeriodPicker
        label="Jan 2003 – Nov 2026"
        range={{ from: '2003-01', to: '2026-11' }}
        limits={{ from: '2003-01', to: '2026-12' }}
        record={{ from: '2003-01', to: '2026-11' }}
        presets={PRESETS}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Later' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Earlier' })).toBeDisabled();
  });

  it('closes on Escape and gives focus back to the button', async () => {
    setup();
    await open();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Forecast, Oct 2026/ })).toHaveFocus();
  });
});
