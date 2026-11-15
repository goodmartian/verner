import { act, fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PLAN } from '../../test/fireFixtures';
import { renderApp } from '../../test/render';
import { useBoard } from '../board/context';
import type { LngLat } from '../map/draw/geometry';
import { AiPanel } from './AiPanel';
import { SILENCE_MS, useChat, type ChatMessage } from './useChat';

const encoder = new TextEncoder();
const event = (name: string, data: unknown) =>
  encoder.encode(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
const DONE = { chat_id: 'c1' };

/** A stream of the chunks, closed after them: the way a good answer ends, or a bad one is cut. */
const closed = (...chunks: Uint8Array[]) =>
  new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk);
        controller.close();
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  );

/** A stream that stays open until the request is cancelled, with the chunks it was given sent as they are asked for. */
function open(signal: AbortSignal | null | undefined, ...chunks: Uint8Array[]) {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
        for (const chunk of chunks) c.enqueue(chunk);
        signal?.addEventListener('abort', () => {
          c.error(new DOMException('cancelled', 'AbortError'));
        });
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  );
  return {
    response,
    send: (chunk: Uint8Array) => {
      controller.enqueue(chunk);
    },
  };
}

interface Call {
  url: string;
  body: { text: string };
  signal: AbortSignal | null | undefined;
}

/** Answers the chat with what `answers` gives, one after another; anything else is nothing. */
function stubChat(answers: ((call: Call) => Response)[]) {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : String(input);
      if (!/\/api\/chats\/[^/]+\/messages/.test(url)) {
        return Promise.resolve(
          new Response(JSON.stringify({ error: { code: 'not_found', message: 'x' } }), {
            status: 404,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      }
      const call: Call = {
        url,
        body: JSON.parse(typeof init?.body === 'string' ? init.body : '{}') as { text: string },
        signal: init?.signal,
      };
      calls.push(call);
      const answer = answers[calls.length - 1];
      return Promise.resolve(answer ? answer(call) : closed(event('done', DONE)));
    }),
  );
  return calls;
}

function Chat() {
  const chat = useChat(vi.fn());
  const last = chat.messages.at(-1);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          void chat.send('Hello');
        }}
      >
        ask
      </button>
      <button
        type="button"
        onClick={() => {
          if (last) chat.retry(last.id);
        }}
      >
        retry
      </button>
      <button type="button" onClick={chat.stop}>
        stop
      </button>
      <output aria-label="stoppable">{String(chat.stoppable)}</output>
      <output aria-label="busy">{String(chat.busy)}</output>
      <output aria-label="last">
        {last ? `${last.status}:${last.errorCode ?? ''}:${last.text}` : ''}
      </output>
      <output aria-label="ids">{chat.messages.map((message) => message.id).join()}</output>
      <output aria-label="count">{chat.messages.length}</output>
    </>
  );
}

const state = (name: string) => screen.getByLabelText(name).textContent;

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function FactChat() {
  const chat = useChat(vi.fn());
  return (
    <button
      type="button"
      onClick={() => {
        void chat.send(
          'Why?',
          [
            {
              kind: 'fact',
              label: 'By year',
              value: '2020: 398',
              area: 'Argentina',
              period: '2020',
            },
          ],
          { tab: 'calendar', areaName: 'Argentina', month: '2026-11' },
        );
      }}
    >
      ask fact
    </button>
  );
}

const CORNERS: LngLat[] = [
  [20, 9],
  [21, 9],
  [21, 10],
];

function DrawnChat() {
  const chat = useChat(() => undefined);
  const board = useBoard();
  return (
    <>
      <button
        type="button"
        onClick={() => {
          board.setDrawn([
            { id: 'U1', points: CORNERS, role: 'area' },
            { id: 'U2', points: [...CORNERS], role: 'safe_zone' },
          ]);
          board.showDrawn(CORNERS);
        }}
      >
        draw
      </button>
      <button
        type="button"
        onClick={() => {
          void chat.send('How many here?');
        }}
      >
        ask drawn
      </button>
    </>
  );
}

describe('an area drawn on the map', () => {
  it('goes with the question by its name, and the one the calendar shows is named', async () => {
    const calls = stubChat([]);
    renderApp(<DrawnChat />);
    await userEvent.click(screen.getByRole('button', { name: 'draw' }));
    await userEvent.click(screen.getByRole('button', { name: 'ask drawn' }));
    await vi.waitFor(() => {
      expect(calls).toHaveLength(1);
    });
    const body = calls[0]?.body as {
      text: string;
      board: { area: null; drawn_area: string; areas: unknown[] };
    };
    expect(body.board.area).toBeNull();
    expect(body.board.drawn_area).toBe('U1');
    expect(body.board.areas).toEqual([
      { id: 'U1', polygon: CORNERS, role: 'area' },
      { id: 'U2', polygon: CORNERS, role: 'safe_zone' },
    ]);
  });
});

describe('a figure of the board in the question', () => {
  it('goes in the board of the request, and the text stays what the person wrote', async () => {
    const calls = stubChat([]);
    renderApp(<FactChat />);
    await userEvent.click(screen.getByRole('button', { name: 'ask fact' }));
    await vi.waitFor(() => {
      expect(calls).toHaveLength(1);
    });
    const body = calls[0]?.body as {
      text: string;
      attachments: unknown[];
      board: { tab: string; area_name: string; month: string; facts: string[] };
    };
    expect(body.text).toBe('Why?');
    expect(body.attachments).toEqual([]);
    expect(body.board).toMatchObject({
      tab: 'calendar',
      area_name: 'Argentina',
      month: '2026-11',
      facts: ['By year: 2020: 398 (Argentina, 2020)'],
    });
  });
});

describe('an answer that is cut off', () => {
  it('is an error when the connection closes without `done`, and the indicator goes at once', async () => {
    stubChat([
      () => closed(event('step', { tool: 'period_stats' }), event('text', { text: 'Part' })),
    ]);
    renderApp(<Chat />);
    await userEvent.click(screen.getByRole('button', { name: 'ask' }));
    await vi.waitFor(() => {
      expect(state('last')).toBe('error:interrupted:Part');
    });
    expect(state('busy')).toBe('false');
  });

  it('is good when `done` came', async () => {
    stubChat([() => closed(event('text', { text: 'Whole' }), event('done', DONE))]);
    renderApp(<Chat />);
    await userEvent.click(screen.getByRole('button', { name: 'ask' }));
    await vi.waitFor(() => {
      expect(state('last')).toBe('done::Whole');
    });
  });

  it('asks the same question again in the same chat, in place of the failed answer', async () => {
    const calls = stubChat([
      () => closed(event('text', { text: 'Fine' }), event('done', DONE)),
      () => closed(event('step', { tool: 'forecast' })),
      // the third is the one that is asked again
      () => closed(event('text', { text: 'Now fine' }), event('done', DONE)),
    ]);
    renderApp(<Chat />);
    await userEvent.click(screen.getByRole('button', { name: 'ask' }));
    await vi.waitFor(() => {
      expect(state('last')).toBe('done::Fine');
    });
    await userEvent.click(screen.getByRole('button', { name: 'ask' }));
    await vi.waitFor(() => {
      expect(state('last')).toBe('error:interrupted:');
    });
    expect(state('count')).toBe('4');
    await userEvent.click(screen.getByRole('button', { name: 'retry' }));
    await vi.waitFor(() => {
      expect(state('last')).toBe('done::Now fine');
    });
    // the failed pair was taken out and asked again: four messages, not six
    expect(state('count')).toBe('4');
    expect(calls).toHaveLength(3);
    expect(calls[2]?.body.text).toBe('Hello');
    // the chat made by the first answer is the one asked
    expect(calls[2]?.url).toContain('/api/chats/c1/messages');
  });
});

describe('a plan the assistant makes', () => {
  it('goes to the map at once, once, as the plan itself', async () => {
    stubChat([
      () =>
        closed(
          event('widget', { type: 'work_plan', data: PLAN }),
          event('widget', { type: 'file', data: { id: 'f1' } }),
          event('done', DONE),
        ),
    ]);
    const onPlan = vi.fn();
    function Ask() {
      const chat = useChat(vi.fn(), onPlan);
      return (
        <button
          type="button"
          onClick={() => {
            void chat.send('Plan');
          }}
        >
          ask
        </button>
      );
    }
    renderApp(<Ask />);
    await userEvent.click(screen.getByRole('button', { name: 'ask' }));
    await vi.waitFor(() => {
      expect(onPlan).toHaveBeenCalledTimes(1);
    });
    expect(onPlan).toHaveBeenCalledWith(PLAN);
  });
});

describe('an answer that says nothing', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  });

  const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
  const ask = () => {
    fireEvent.click(screen.getByRole('button', { name: 'ask' }));
    return tick(0);
  };

  it('is given up after a minute: the error shows and the request is cancelled', async () => {
    const calls = stubChat([(call) => open(call.signal).response]);
    renderApp(<Chat />);
    await ask();
    await tick(SILENCE_MS - 1000);
    expect(state('busy')).toBe('true');
    await tick(1500);
    expect(state('last')).toBe('error:silence:');
    expect(state('busy')).toBe('false');
    expect(calls[0]?.signal?.aborted).toBe(true);
  });

  it('starts counting again at each event', async () => {
    let stream: ReturnType<typeof open> | undefined;
    stubChat([
      (call) => {
        stream = open(call.signal, event('step', { tool: 'period_stats' }));
        return stream.response;
      },
    ]);
    renderApp(<Chat />);
    await ask();
    await tick(50_000);
    stream?.send(event('text', { text: 'still here' }));
    await tick(50_000);
    // a hundred seconds since the start, but only fifty since the last word
    expect(state('busy')).toBe('true');
    await tick(11_000);
    expect(state('last')).toBe('error:silence:still here');
  });

  it('stops on request: what came stays as the answer, with no error', async () => {
    let stream: ReturnType<typeof open> | undefined;
    stubChat([
      (call) => {
        stream = open(call.signal, event('text', { text: 'Half an' }));
        return stream.response;
      },
    ]);
    renderApp(<Chat />);
    await ask();
    expect(state('stoppable')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'stop' }));
    await tick(0);
    expect(state('last')).toBe('done::Half an');
    expect(state('busy')).toBe('false');
    expect(state('stoppable')).toBe('false');
  });

  it('drops an answer that had said nothing when it is stopped, and keeps the question', async () => {
    stubChat([(call) => open(call.signal).response]);
    renderApp(<Chat />);
    await ask();
    fireEvent.click(screen.getByRole('button', { name: 'stop' }));
    await tick(0);
    expect(state('count')).toBe('1');
    expect(state('busy')).toBe('false');
  });

  it('keeps every message under its own id through two questions and a stop', async () => {
    stubChat([
      () => closed(event('text', { text: 'One.' }), event('done', DONE)),
      (call) => open(call.signal, event('text', { text: 'Two' })).response,
    ]);
    renderApp(<Chat />);
    await ask();
    await ask();
    fireEvent.click(screen.getByRole('button', { name: 'stop' }));
    await tick(0);
    const ids = state('ids').split(',');
    expect(ids).toHaveLength(4);
    expect(new Set(ids).size).toBe(4);
  });

  it('goes on in the same chat after a stopped answer: the chat has its id from the first event', async () => {
    const calls = stubChat([
      (call) => open(call.signal, event('start', { chat_id: 'chat-1' })).response,
      () => closed(event('done', DONE)),
    ]);
    renderApp(<Chat />);
    await ask();
    fireEvent.click(screen.getByRole('button', { name: 'stop' }));
    await tick(0);
    await ask();
    expect(calls[0]?.url).toContain('/api/chats/new/messages');
    expect(calls[1]?.url).toContain('/api/chats/chat-1/messages');
  });

  it('does not run on after the answer is over', async () => {
    const calls = stubChat([() => closed(event('done', DONE))]);
    renderApp(<Chat />);
    await ask();
    await tick(SILENCE_MS * 2);
    expect(state('last')).toBe('done::');
    expect(calls[0]?.signal?.aborted).toBe(false);
  });
});

describe('the steps of an answer', () => {
  const panel = (steps: string[], answer: Partial<ChatMessage> = {}) =>
    renderApp(
      <AiPanel
        variant="panel"
        onVariant={vi.fn()}
        onSettings={vi.fn()}
        rootRef={vi.fn()}
        wide={false}
        onWide={vi.fn()}
        messages={[
          {
            id: 1,
            role: 'user',
            text: 'Q',
            steps: [],
            widgets: [],
            actions: [],
            status: 'done',
            at: 0,
            attachments: [],
          },
          {
            id: 2,
            role: 'assistant',
            text: '',
            steps,
            widgets: [],
            actions: [],
            status: 'streaming',
            at: 0,
            attachments: [],
            ...answer,
          },
        ]}
        busy
        onSend={vi.fn()}
        onRetry={vi.fn()}
        onOpenChat={vi.fn()}
        onDeleteChat={vi.fn()}
        onNewChat={vi.fn()}
        attachments={[]}
        onAttachments={vi.fn()}
        dockOpen={false}
        canPlan={false}
        onPlan={vi.fn()}
        addable={[]}
        suggestions={[]}
        focusKey={0}
        foot={createRef()}
      />,
    );

  const CARD = {
    type: 'file',
    data: {
      id: 'f1',
      name: 'verner_monthly.csv',
      mime: 'text/csv',
      size: 2048,
      rows: 12,
      kind: 'monthly',
    },
  } as const;

  it('keeps the cards of an answer back while the answer is coming', () => {
    // the card came with the tool, before the first word: it waits for the words
    panel(['prepare_file'], { widgets: [CARD], text: 'Here is' });
    expect(screen.queryByText('Detections by month')).not.toBeInTheDocument();
  });

  it('shows the cards under the words once the answer is over', () => {
    panel(['prepare_file'], { widgets: [CARD], text: 'Here is the file.', status: 'done' });
    const words = screen.getByText('Here is the file.');
    const card = screen.getByText('Detections by month');
    expect(words.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('keeps one step as its own line when the answer is over, with nothing to unfold', () => {
    panel(['prepare_file'], { text: 'Done.', status: 'done' });
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /steps/ })).not.toBeInTheDocument();
  });

  it.each([
    ['fire_weather', 'Reading the weather at the fire'],
    ['weather_in_area', 'Reading the weather of the area'],
    ['place_weather', 'Reading the weather at the place'],
    ['month_weather', 'Reading the weather of the month'],
  ])('says what %s is doing', (tool, text) => {
    panel(['period_stats', tool]);
    // the running step is the last one; the steps before it are listed as done
    expect(screen.getAllByText(text).length).toBeGreaterThan(0);
  });

  it('says "Reading the data" for a tool it does not know, and does not break', () => {
    panel(['period_stats', 'a_tool_of_tomorrow']);
    expect(screen.getAllByText('Reading the data').length).toBeGreaterThan(0);
  });

  it('shows the error of a cut answer with the way to ask again', async () => {
    const onRetry = vi.fn();
    renderApp(
      <AiPanel
        variant="panel"
        onVariant={vi.fn()}
        onSettings={vi.fn()}
        rootRef={vi.fn()}
        wide={false}
        onWide={vi.fn()}
        messages={[
          {
            id: 1,
            role: 'user',
            text: 'Q',
            steps: [],
            widgets: [],
            actions: [],
            status: 'done',
            at: 0,
            attachments: [],
          },
          {
            id: 2,
            role: 'assistant',
            text: '',
            steps: [],
            widgets: [],
            actions: [],
            status: 'error',
            errorCode: 'interrupted',
            at: 0,
            attachments: [],
          },
        ]}
        busy={false}

        onSend={vi.fn()}
        onRetry={onRetry}
        onOpenChat={vi.fn()}
        onDeleteChat={vi.fn()}
        onNewChat={vi.fn()}
        attachments={[]}
        onAttachments={vi.fn()}
        dockOpen={false}
        canPlan={false}
        onPlan={vi.fn()}
        addable={[]}
        suggestions={[]}
        focusKey={0}
        foot={createRef()}
      />,
    );
    expect(screen.getByText('Could not get an answer.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledWith(2);
  });
});
