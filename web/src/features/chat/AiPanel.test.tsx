import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '../../test/render';
import { AiPanel } from './AiPanel';

function setup(props: Partial<Parameters<typeof AiPanel>[0]> = {}) {
  const handlers = {
    onVariant: vi.fn(),
    onSettings: vi.fn(),
    rootRef: vi.fn(),
    onWide: vi.fn(),
    onSend: vi.fn(),
    onRetry: vi.fn(),
    onOpenChat: vi.fn(),
    onDeleteChat: vi.fn(),
    onNewChat: vi.fn(),
    onAttachments: vi.fn(),
  };
  renderApp(
    <AiPanel
      variant="bar"
      wide={false}
      messages={[]}
      busy={false}
      attachments={[]}
      addable={[]}
      canPlan={false}
      onPlan={vi.fn()}
      dockOpen={false}
      suggestions={[]}
      focusKey={0}
      foot={createRef()}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe('AiPanel line', () => {
  it('keeps history and a new chat in the head of the panel, not in the line of the field', async () => {
    const { onNewChat } = setup({ variant: 'panel' });
    const head = screen.getByRole('banner');
    expect(within(head).getByRole('button', { name: 'Chat history' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Chat history' })).toHaveLength(1);
    await userEvent.click(within(head).getByRole('button', { name: 'New chat' }));
    expect(onNewChat).toHaveBeenCalled();
  });
  it('opens what can be added and puts it on the question', async () => {
    const onPick = vi.fn();
    setup({
      addable: [{ key: 'm', icon: 'calendar-dots', label: 'Month on the map: March 2025', onPick }],
    });
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Month on the map: March 2025' }));
    expect(onPick).toHaveBeenCalled();
  });
  it('shows Stop in place of Send while an answer is coming, and stops it', async () => {
    const onStop = vi.fn();
    setup({ busy: true, onStop });
    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(onStop).toHaveBeenCalled();
  });
  it('keeps Send, disabled, while a plan is being made and cannot be stopped', () => {
    setup({ busy: true });
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });
  it('leaves no measured height on an empty field, so the stylesheet keeps it one line in any view', async () => {
    setup();
    const field = screen.getByRole('textbox');
    expect(field.style.height).toBe('');
    await userEvent.type(field, 'Where did it burn{Shift>}{Enter}{/Shift}most');
    expect(field.style.height).not.toBe('');
    await userEvent.clear(field);
    expect(field.style.height).toBe('');
  });
});
