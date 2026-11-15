import { vi } from 'vitest';

type Handler = (request: Request) => Response | Promise<Response>;

export const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

export const apiError = (
  status: number,
  code: string,
  fields?: { loc: string[]; message: string }[],
) => json(status, { error: { code, message: code, fields: fields ?? null } });

/**
 * Replaces fetch with answers by "METHOD /path". Anything not listed is a 404 the server would
 * give, so a test never talks to a real address.
 */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { method: string; path: string; query: Record<string, string>; body: unknown }[] =
    [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request =
      input instanceof Request
        ? input
        : new Request(new URL(String(input), 'http://app.test'), init);
    const path = new URL(request.url).pathname;
    const key = `${request.method} ${path}`;
    const text = await request.clone().text();
    calls.push({
      method: request.method,
      path,
      query: Object.fromEntries(new URL(request.url).searchParams),
      body: text ? (JSON.parse(text) as unknown) : undefined,
    });
    return routes[key]?.(request) ?? apiError(404, 'not_found');
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}
