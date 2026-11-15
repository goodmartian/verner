import { COUNTRY_ID } from '../../test/configFixtures';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiError } from '../../test/mockApi';
import type { ChatEvent } from '../../api/types';
import { askChat, readEvents } from './stream';

function streamOf(...chunks: string[]) {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(events: AsyncGenerator<ChatEvent>) {
  const all: ChatEvent[] = [];
  for await (const event of events) all.push(event);
  return all;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('readEvents', () => {
  it('reads each event once it is complete, even when cut in the middle', async () => {
    const events = await collect(
      readEvents(
        streamOf(
          'event: step\ndata: {"tool":"period_stats"}\n\nevent: te',
          'xt\ndata: {"text":"Hello"}\n\nevent: done\ndata: {"chat_id":"c1"}\n\n',
        ),
      ),
    );
    expect(events).toEqual([
      { event: 'step', data: { tool: 'period_stats' } },
      { event: 'text', data: { text: 'Hello' } },
      { event: 'done', data: { chat_id: 'c1' } },
    ]);
  });

  it('understands CRLF line ends', async () => {
    const events = await collect(
      readEvents(streamOf('event: text\r\ndata: {"text":"plain"}\r\n\r\n')),
    );
    expect(events).toEqual([{ event: 'text', data: { text: 'plain' } }]);
  });

  it('skips a piece that is not JSON', async () => {
    expect(await collect(readEvents(streamOf('event: text\ndata: plain\n\n')))).toEqual([]);
  });

  it('skips events it does not know and comments', async () => {
    const events = await collect(
      readEvents(
        streamOf(
          ': ping\n\nevent: mystery\ndata: 1\n\nevent: error\ndata: {"code":"upstream_error","message":"x"}\n\n',
        ),
      ),
    );
    expect(events).toEqual([{ event: 'error', data: { code: 'upstream_error', message: 'x' } }]);
  });

  it('reads an event that ends the stream without a blank line', async () => {
    const events = await collect(readEvents(streamOf('event: text\ndata: {"text":"last"}')));
    expect(events).toEqual([{ event: 'text', data: { text: 'last' } }]);
  });
});

describe('askChat', () => {
  it('posts the question to the chat and streams the answer', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(streamOf('event: text\ndata: {"text":"Hi"}\n\n'), {
        headers: { 'Content-Type': 'text/event-stream' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const events = await collect(
      askChat('new', { text: 'Hello?', board: { area: COUNTRY_ID } }, new AbortController().signal),
    );
    expect(events).toEqual([{ event: 'text', data: { text: 'Hi' } }]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/chats/new/messages');
    expect(init.method).toBe('POST');
    expect(init.body).toBe(JSON.stringify({ text: 'Hello?', board: { area: COUNTRY_ID } }));
  });

  it("throws the server's error when the answer is not a stream", async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(apiError(429, 'rate_limited')));
    await expect(
      collect(askChat('new', { text: 'x' }, new AbortController().signal)),
    ).rejects.toMatchObject({
      status: 429,
      code: 'rate_limited',
    });
  });

  it('keeps how long a refused question has to wait', async () => {
    const refused = new Response(JSON.stringify({ error: { code: 'chat_banned', message: 'x' } }), {
      status: 429,
      headers: { 'Content-Type': 'application/json', 'Retry-After': '600' },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(refused));
    await expect(
      collect(askChat('new', { text: 'x' }, new AbortController().signal)),
    ).rejects.toMatchObject({ status: 429, code: 'chat_banned', retryAfter: 600 });
  });

  it('reports no answer as "network"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    await expect(
      collect(askChat('new', { text: 'x' }, new AbortController().signal)),
    ).rejects.toMatchObject({
      code: 'network',
    });
  });
});
