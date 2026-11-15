import { afterEach, describe, expect, it, vi } from 'vitest';
import { COUNTRY_ID, makeConfig } from '../test/configFixtures';
import { apiError, json, mockApi } from '../test/mockApi';
import { api, ApiError, call, callEmpty } from './client';
import { codeKey, errorKey } from './errors';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('call', () => {
  it('returns the data of a good answer', async () => {
    mockApi({
      'GET /api/health': () => json(200, { status: 'ok', database: 'ok', schema_revision: '1' }),
    });
    expect(await call(api.GET('/api/health'))).toEqual({
      status: 'ok',
      database: 'ok',
      schema_revision: '1',
    });
  });

  it('turns an error answer into an ApiError with its status, code and fields', async () => {
    mockApi({
      'POST /api/export': () =>
        apiError(422, 'validation_error', [{ loc: ['body', 'code'], message: 'too short' }]),
    });
    const failure = await call(
      api.POST('/api/export', { body: { area: { id: COUNTRY_ID } } }),
    ).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 422, code: 'validation_error' });
    expect((failure as ApiError).hasField('code')).toBe(true);
    expect((failure as ApiError).hasField('name')).toBe(false);
  });

  it('keeps how long the server asks to wait before asking again', async () => {
    mockApi({
      'GET /api/health': () =>
        new Response(JSON.stringify({ error: { code: 'rate_limited', message: 'slow' } }), {
          status: 429,
          headers: { 'Content-Type': 'application/json', 'Retry-After': '1800' },
        }),
    });
    await expect(call(api.GET('/api/health'))).rejects.toMatchObject({
      status: 429,
      retryAfter: 1800,
    });
    mockApi({ 'GET /api/health': () => apiError(429, 'rate_limited') });
    await expect(call(api.GET('/api/health'))).rejects.toMatchObject({ retryAfter: null });
  });

  it('reports no answer as "network"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    await expect(call(api.GET('/api/health'))).rejects.toMatchObject({
      status: 0,
      code: 'network',
    });
  });

  it('preserves the covered-country names on error responses', async () => {
    const countries = makeConfig().countries;
    mockApi({
      'GET /api/regions': () =>
        json(409, {
          error: {
            code: 'not_covered',
            message: 'Outside coverage',
            covered_countries: countries,
          },
        }),
    });
    await expect(call(api.GET('/api/regions'))).rejects.toMatchObject({
      status: 409,
      code: 'not_covered',
      coveredCountries: countries,
    });
  });

  it('keeps HTTP refusals with empty or plain response bodies', async () => {
    for (const body of [null, 'Too many rows']) {
      mockApi({ 'POST /api/export': () => new Response(body, { status: 413 }) });
      await expect(
        call(api.POST('/api/export', { body: { area: { id: COUNTRY_ID } } })),
      ).rejects.toMatchObject({ status: 413, code: 'payload_too_large' });
    }
  });
});

describe('callEmpty', () => {
  it('accepts an answer without a body', async () => {
    mockApi({ 'DELETE /api/chats/c1': () => new Response(null, { status: 204 }) });
    await expect(
      callEmpty(api.DELETE('/api/chats/{chat_id}', { params: { path: { chat_id: 'c1' } } })),
    ).resolves.toBeUndefined();
  });
});

describe('error texts', () => {
  it('has a text for every code the server can answer', () => {
    for (const code of [
      'invalid_code',
      'unauthorized',
      'forbidden',
      'origin_not_allowed',
      'not_found',
      'conflict',
      'chat_busy',
      'payload_too_large',
      'validation_error',
      'rate_limited',
      'chat_quota',
      'chat_banned',
      'internal_error',
      'upstream_error',
      'unavailable',
    ]) {
      expect(codeKey(code), code).not.toBe('error.unknown');
    }
  });

  it('falls back for a code it does not know and for a caught non-answer', () => {
    expect(codeKey('something_new')).toBe('error.unknown');
    expect(errorKey(new Error('x'))).toBe('error.network');
    expect(errorKey(new ApiError(429, 'rate_limited', 'x'))).toBe('error.rate_limited');
  });
});
