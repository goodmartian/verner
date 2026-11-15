import type { MessageKey } from '../i18n/en';
import { ApiError } from './client';

const TEXT: Record<string, MessageKey> = {
  network: 'error.network',
  invalid_code: 'error.invalid_code',
  unauthorized: 'error.unauthorized',
  forbidden: 'error.forbidden',
  origin_not_allowed: 'error.forbidden',
  not_found: 'error.not_found',
  conflict: 'error.conflict',
  chat_busy: 'error.chat_busy',
  payload_too_large: 'error.payload_too_large',
  validation_error: 'error.validation_error',
  invalid_area: 'error.invalid_area',
  invalid_period: 'error.invalid_period',
  rate_limited: 'error.rate_limited',
  chat_quota: 'error.chat_quota',
  chat_banned: 'error.chat_banned',
  export_quota: 'error.export_quota',
  export_day_cap: 'error.export_day_cap',
  export_busy: 'error.export_busy',
  internal_error: 'error.internal_error',
  upstream_error: 'error.upstream_error',
  unavailable: 'error.unavailable',
  not_covered: 'error.not_covered',
  grid_unavailable: 'area.unavailable',
  grid_contract_error: 'area.unavailable',
  plan_unavailable: 'error.plan_unavailable',
  storage_unavailable: 'plans.unavailable',
  // an answer that was cut off, or that said nothing for too long
  interrupted: 'error.no_answer',
  silence: 'error.no_answer',
};

/** The message that tells a person what an error `code` means. */
export function codeKey(code: string): MessageKey {
  return TEXT[code] ?? 'error.unknown';
}

/** The same for a caught error; anything that is not an answer of the server counts as no answer. */
export function errorKey(error: unknown): MessageKey {
  return codeKey(error instanceof ApiError ? error.code : 'network');
}
