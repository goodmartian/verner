import { COUNTRY_ID } from '../../test/configFixtures';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PLAN } from '../../test/fireFixtures';
import { renderApp } from '../../test/render';
import { useBoard, type AiMap } from '../board/context';
import type { FirePlan } from '../../api/types';
import { useChat } from './useChat';

const shape = (id: string) => ({ id, kind: 'point', label_at: [1, 1], position: [1, 1] });
const message = (seq: number, actions: unknown[]) => ({
  seq,
  role: 'assistant',
  text: 'done',
  widgets: [],
  actions,
  created_at: '2026-10-30T10:00:00Z',
});

function stubHistory(widgets: unknown[] = []) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : String(input);
      const headers = { 'Content-Type': 'application/json' };
      if (!url.includes('/api/chats/c1')) {
        const none = { error: { code: 'unauthorized', message: 'x' } };
        return Promise.resolve(new Response(JSON.stringify(none), { status: 401, headers }));
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            id: 'c1',
            messages: [
              { ...message(0, []), widgets },
              message(1, [{ type: 'draw', shapes: [shape('A1'), shape('A2')], replace: false }]),
              message(2, [{ type: 'set_area', area: COUNTRY_ID }]),
              message(3, [{ type: 'draw', shapes: [shape('A3')], replace: true }]),
            ],
          }),
          { status: 200, headers },
        ),
      );
    }),
  );
}

function Harness({ map, onPlan }: { map: AiMap; onPlan?: (plan: FirePlan) => void }) {
  const { bindAi } = useBoard();
  useEffect(() => {
    bindAi(map);
  }, [bindAi, map]);
  const chat = useChat(vi.fn(), onPlan);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          void chat.open('c1');
        }}
      >
        open
      </button>
      <button type="button" onClick={chat.reset}>
        new
      </button>
      <output aria-label="count">{chat.messages.length}</output>
    </>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('a plan in a chat of the history', () => {
  it('does not move the map: the button of its card does', async () => {
    stubHistory([{ type: 'work_plan', data: PLAN }]);
    const onPlan = vi.fn();
    const map: AiMap = { draw: vi.fn(), clear: vi.fn(), show: vi.fn() };
    renderApp(<Harness map={map} onPlan={onPlan} />);
    await userEvent.click(screen.getByRole('button', { name: 'open' }));
    await vi.waitFor(() => {
      expect(screen.getByLabelText('count').textContent).toBe('4');
    });
    expect(onPlan).not.toHaveBeenCalled();
  });
});

describe('the drawings of a chat of the history', () => {
  it('are drawn again, as the chat drew them: in order, a "replace" putting out what went before', async () => {
    stubHistory();
    const calls: string[] = [];
    const map: AiMap = {
      draw: (shapes, replace) => {
        calls.push(`${replace ? 'replace' : 'add'}:${shapes.map((item) => item.id).join(',')}`);
      },
      clear: () => {
        calls.push('clear');
      },
      show: vi.fn(),
    };
    renderApp(<Harness map={map} />);
    await userEvent.click(screen.getByRole('button', { name: 'open' }));
    await vi.waitFor(() => {
      expect(screen.getByLabelText('count').textContent).toBe('4');
    });
    // what was on the map goes first; the actions that are not drawings are not its business
    expect(calls).toEqual(['clear', 'add:A1,A2', 'replace:A3']);
  });

  it('are taken off the map when a new chat is started', async () => {
    const calls: string[] = [];
    const map: AiMap = {
      draw: vi.fn(),
      clear: () => {
        calls.push('clear');
      },
      show: vi.fn(),
    };
    renderApp(<Harness map={map} />);
    await userEvent.click(screen.getByRole('button', { name: 'new' }));
    expect(calls).toEqual(['clear']);
  });
});
