import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '../test/render';
import { Guard } from './Guard';

describe('Guard', () => {
  it('holds the failure of one block and leaves its neighbours in place, and tries again on the button', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    let broken = true;
    function Card() {
      if (broken) throw new Error('boom');
      return <p>the card</p>;
    }
    renderApp(
      <>
        <p>a neighbour</p>
        <Guard>
          <Card />
        </Guard>
        <p>another neighbour</p>
      </>,
    );
    expect(screen.getByText('a neighbour')).toBeInTheDocument();
    expect(screen.getByText('another neighbour')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('This block did not load');
    broken = false;
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('the card')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
