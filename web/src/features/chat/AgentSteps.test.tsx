import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render';
import { AgentSteps } from './AgentSteps';

const steps = [
  { id: '1', label: 'Reading the calendar', status: 'done' as const },
  { id: '2', label: 'Reading the fires', status: 'running' as const },
];

describe('steps of the assistant', () => {
  it('lists the steps while it works', () => {
    renderApp(<AgentSteps steps={steps} folded={false} />);
    expect(screen.getByText('Reading the calendar')).toBeInTheDocument();
    expect(screen.getAllByText('Reading the fires').length).toBeGreaterThan(0);
  });
  it('folds to one line that opens again once the answer comes', async () => {
    renderApp(<AgentSteps steps={steps} folded />);
    expect(screen.queryByText('Reading the calendar')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '2 steps' }));
    expect(screen.getByText('Reading the calendar')).toBeInTheDocument();
  });
});
