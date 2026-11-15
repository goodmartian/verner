import createClient from 'openapi-fetch';
import type { components, paths } from './schema';

type FieldError = components['schemas']['FieldError'];
type CoveredCountryName = Pick<components['schemas']['CoveredCountry'], 'id' | 'names'>;
/** Only the error fields consumed here; transport schemas may carry additional metadata. */
interface ReplyError {
  error: Pick<components['schemas']['ErrorBody'], 'code' | 'message' | 'fields'> & {
    covered_countries?: readonly CoveredCountryName[] | null;
  };
}

/** An error answered by the server, or `network` (status 0) when no answer came. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fields: readonly FieldError[] = [],
    /** Seconds the server asks to wait before asking again (`Retry-After`), when it did. */
    readonly retryAfter: number | null = null,
    readonly coveredCountries: readonly CoveredCountryName[] = [],
  ) {
    super(message);
  }

  /** Whether the server named this body field as the wrong one. */
  hasField(name: string): boolean {
    return this.fields.some((field) => field.loc.at(-1) === name);
  }
}

// the page's own origin; fetch is looked up per call so tests can replace it
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  fetch: (request) => globalThis.fetch(request),
});

interface Reply<T> {
  data?: T;
  error?: ReplyError;
  response: Response;
}

/** JSON error envelopes and bodyless/plain HTTP refusals share one typed boundary. */
export function errorFromResponse(response: Response, value: unknown): ApiError {
  const object = (item: unknown): item is Record<string, unknown> =>
    item !== null && typeof item === 'object';
  const body = object(value) && object(value.error) ? value.error : null;
  const fields: FieldError[] = [];
  if (Array.isArray(body?.fields))
    for (const field of body.fields) {
      if (
        object(field) &&
        Array.isArray(field.loc) &&
        field.loc.every((part: unknown) => typeof part === 'string' || typeof part === 'number') &&
        typeof field.message === 'string'
      )
        fields.push({ loc: field.loc, message: field.message });
    }
  const countries: CoveredCountryName[] = [];
  if (Array.isArray(body?.covered_countries))
    for (const country of body.covered_countries) {
      if (object(country) && typeof country.id === 'string' && object(country.names)) {
        const names: Record<string, string> = {};
        for (const [lang, name] of Object.entries(country.names))
          if (typeof name === 'string') names[lang] = name;
        countries.push({ ...country, id: country.id, names });
      }
    }
  const wait = Number(response.headers.get('Retry-After'));
  return new ApiError(
    response.status,
    typeof body?.code === 'string'
      ? body.code
      : response.status === 413
        ? 'payload_too_large'
        : 'unavailable',
    typeof body?.message === 'string' ? body.message : response.statusText,
    fields,
    Number.isFinite(wait) && wait > 0 ? wait : null,
    countries,
  );
}

export async function reply<T>(request: Promise<Reply<T>>): Promise<Reply<T>> {
  let reply: Reply<T>;
  try {
    reply = await request;
  } catch {
    throw new ApiError(0, 'network', 'No answer from the server');
  }
  if (reply.error || (!reply.response.ok && reply.response.status !== 304))
    throw errorFromResponse(reply.response, reply.error);
  return reply;
}

/** Waits for a call and returns its data; any error answer becomes an ApiError. */
export async function call<T>(request: Promise<Reply<T>>): Promise<T> {
  const { data } = await reply(request);
  if (data === undefined) throw new ApiError(0, 'network', 'Empty answer');
  return data;
}

/** Same for calls that answer with no body. */
export async function callEmpty(request: Promise<Reply<unknown>>): Promise<void> {
  await reply(request);
}
