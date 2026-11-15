import { ApiError, errorFromResponse } from '../../api/client';
import type { ChatEvent, ChatQuestion } from '../../api/types';

const KNOWN = new Set(['start', 'step', 'text', 'widget', 'action', 'done', 'error']);

function toEvent(name: string, raw: string): ChatEvent | null {
  if (!KNOWN.has(name)) return null;
  try {
    return { event: name, data: JSON.parse(raw) as unknown } as ChatEvent;
  } catch {
    return null;
  }
}

/** Reads a server-sent event stream and yields its events as they complete. */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const flush = function* (block: string) {
    let name = 'message';
    const data: string[] = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) name = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
    }
    const event = data.length ? toEvent(name, data.join('\n')) : null;
    if (event) yield event;
  };
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
      let end = buffer.indexOf('\n\n');
      while (end !== -1) {
        yield* flush(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        end = buffer.indexOf('\n\n');
      }
    }
    if (buffer.trim()) yield* flush(buffer);
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}

/** Asks a question in a chat (`new` starts one) and streams the answer. */
export async function* askChat(
  chatId: string,
  question: ChatQuestion,
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  let response: Response;
  try {
    response = await fetch(`/api/chats/${chatId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(question),
      signal,
    });
  } catch (error) {
    if (signal.aborted) return;
    throw new ApiError(0, 'network', error instanceof Error ? error.message : 'No answer');
  }
  if (!response.ok || !response.body) {
    // the same reading as every other call: a refusal of the chat keeps its Retry-After
    throw errorFromResponse(response, await response.json().catch(() => null));
  }
  yield* readEvents(response.body);
}
