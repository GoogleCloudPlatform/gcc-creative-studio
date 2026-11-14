/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

const CLOCK_SKEW_TOLERANCE_MS = 2 * 60 * 1000;
// eslint-disable-next-line no-control-regex
const CONTROL_CHAR_REGEX = /[\u0000-\u001f\u007f]/;
const SESSION_HANDLED_SYMBOL = Symbol('csSessionHandled');
const FAILED_SESSION_TOKEN_SYMBOL = Symbol('csFailedSessionToken');
const handledFrozenErrors = new WeakSet<object>();
const failedTokenFrozenErrors = new WeakMap<object, string>();

export interface GoogleIdTokenPayload {
  sub?: string;
  email?: string;
  hd?: string;
  exp?: number;
  iat?: number;
  name?: string;
  [key: string]: unknown;
}

export interface GisCredentialResponse {
  credential?: string;
  select_by?: string;
}

export interface GisPromptMomentNotification {
  isNotDisplayed?: () => boolean;
  isSkippedMoment?: () => boolean;
  isDismissedMoment?: () => boolean;
  getDismissedReason?: () => string;
}

export interface GisButtonConfiguration {
  type?: 'standard' | 'icon';
  theme?: 'outline' | 'filled_blue' | 'filled_black';
  size?: 'large' | 'medium' | 'small';
  text?: 'signin_with' | 'signup_with' | 'continue_with' | 'signin';
  shape?: 'rectangular' | 'pill' | 'circle' | 'square';
  logo_alignment?: 'left' | 'center';
  width?: number | string;
  locale?: string;
  click_listener?: () => void;
}

export interface GisInitializeConfig {
  client_id: string;
  auto_select?: boolean;
  use_fedcm_for_prompt?: boolean;
  use_fedcm_for_button?: boolean;
  login_hint?: string;
  hd?: string;
  callback: (response: GisCredentialResponse) => void;
}

export interface GisIdApi {
  initialize: (config: GisInitializeConfig) => void;
  prompt: (
    momentListener?: (notification: GisPromptMomentNotification) => void,
  ) => void;
  renderButton?: (parent: HTMLElement, options: GisButtonConfiguration) => void;
  cancel: () => void;
  disableAutoSelect: () => void;
}

export class AccountMismatchError extends Error {
  constructor() {
    super('Renewed token belongs to a different Google account.');
    this.name = 'AccountMismatchError';
  }
}

export class GisPromptSuppressedError extends Error {
  constructor(message = 'Google One Tap prompt was suppressed.') {
    super(message);
    this.name = 'GisPromptSuppressedError';
  }
}

export class SessionSupersededError extends Error {
  constructor(
    message = 'Session renewal was superseded.',
    readonly failedToken?: string | null,
  ) {
    super(message);
    this.name = 'SessionSupersededError';
    markSessionHandled(this);
  }
}

export function attachFailedSessionToken<T>(
  error: T,
  token: string | null | undefined,
): T {
  if (
    typeof token === 'string' &&
    token &&
    error !== null &&
    (typeof error === 'object' || typeof error === 'function')
  ) {
    if (Object.isExtensible(error)) {
      if (!(FAILED_SESSION_TOKEN_SYMBOL in error)) {
        Object.defineProperty(error, FAILED_SESSION_TOKEN_SYMBOL, {
          value: token,
          configurable: true,
        });
      }
    } else {
      failedTokenFrozenErrors.set(error, token);
    }
  }
  return error;
}

export function getFailedSessionToken(error: unknown): string | null {
  if (
    error === null ||
    (typeof error !== 'object' && typeof error !== 'function')
  ) {
    return null;
  }
  if (error instanceof SessionSupersededError && error.failedToken) {
    return error.failedToken;
  }
  const token =
    (error as Record<symbol, unknown>)[FAILED_SESSION_TOKEN_SYMBOL] ??
    failedTokenFrozenErrors.get(error);
  return typeof token === 'string' && token ? token : null;
}

/**
 * Brands an error after session-expiry handling so downstream callers still
 * clean up loading state without emitting a duplicate error snackbar.
 */
export function markSessionHandled<T>(error: T): T {
  if (
    error !== null &&
    (typeof error === 'object' || typeof error === 'function')
  ) {
    if (Object.isExtensible(error)) {
      if (!(SESSION_HANDLED_SYMBOL in error)) {
        Object.defineProperty(error, SESSION_HANDLED_SYMBOL, {
          value: true,
          configurable: true,
        });
      }
    } else {
      handledFrozenErrors.add(error);
    }
  }
  return error;
}

export function isSessionHandledError(error: unknown): boolean {
  if (
    error === null ||
    (typeof error !== 'object' && typeof error !== 'function')
  ) {
    return false;
  }
  return (
    Boolean((error as Record<symbol, unknown>)[SESSION_HANDLED_SYMBOL]) ||
    handledFrozenErrors.has(error)
  );
}

export function decodeGoogleJwtPayload(token: string): GoogleIdTokenPayload {
  const base64Url = token.split('.')[1];
  if (!base64Url) {
    throw new Error('Invalid JWT token');
  }
  const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64.padEnd(
    base64.length + ((4 - (base64.length % 4)) % 4),
    '=',
  );
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  // eslint-disable-next-line n/no-unsupported-features/node-builtins
  const decoded = new TextDecoder().decode(bytes);
  const parsed: unknown = JSON.parse(decoded);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Invalid JWT token');
  }
  return parsed as GoogleIdTokenPayload;
}

/**
 * Resolves a freshly minted token's expiry in the client's `Date.now()` clock.
 * When `iat` is present and the client clock is skewed (>2 min fast or slow),
 * uses the server-issued TTL `(exp - iat)` anchored at `nowMs` so fast clocks
 * never renewal-loop and slow clocks renew before the server rejects the token.
 */
export function resolveSessionExpiry(
  token: string,
  nowMs = Date.now(),
): number {
  const payload = decodeGoogleJwtPayload(token);
  const exp = payload.exp;
  if (typeof exp !== 'number' || !Number.isFinite(exp) || exp <= 0) {
    throw new Error('JWT token missing valid exp claim');
  }
  const iat = payload.iat;
  if (
    typeof iat === 'number' &&
    Number.isFinite(iat) &&
    exp > iat &&
    Math.abs(nowMs - iat * 1000) > CLOCK_SKEW_TOLERANCE_MS
  ) {
    return nowMs + (exp - iat) * 1000;
  }
  return exp * 1000;
}

/**
 * Extracts `login_hint` (required for silent renewal) and optional `hd` from
 * the stored JWT. Returns `null` when no account constraint can be derived.
 */
export function extractSessionHints(
  token: string | null,
): {login_hint: string; hd?: string} | null {
  if (!token) return null;
  try {
    const payload = decodeGoogleJwtPayload(token);
    if (typeof payload.email !== 'string' || !payload.email.trim()) {
      return null;
    }
    const hints: {login_hint: string; hd?: string} = {
      login_hint: payload.email,
    };
    if (typeof payload.hd === 'string' && payload.hd) {
      hints.hd = payload.hd;
    }
    return hints;
  } catch {
    return null;
  }
}

/**
 * Verifies a silently renewed token belongs to the same Google account as the
 * active session (`sub` match, plus case-insensitive `email` match).
 */
export function isSameSessionAccount(
  previousToken: string | null,
  nextToken: string,
): boolean {
  if (!previousToken) return false;
  try {
    const prev = decodeGoogleJwtPayload(previousToken);
    const next = decodeGoogleJwtPayload(nextToken);
    const prevSub = typeof prev.sub === 'string' && prev.sub ? prev.sub : null;
    const nextSub = typeof next.sub === 'string' && next.sub ? next.sub : null;
    if (prevSub || nextSub) {
      if (!prevSub || !nextSub || prevSub !== nextSub) return false;
    }
    const prevEmail =
      typeof prev.email === 'string' && prev.email.trim()
        ? prev.email.trim().toLowerCase()
        : null;
    const nextEmail =
      typeof next.email === 'string' && next.email.trim()
        ? next.email.trim().toLowerCase()
        : null;
    if (prevEmail || nextEmail) {
      if (!prevEmail || !nextEmail || prevEmail !== nextEmail) return false;
    }
    if (!prevSub && !prevEmail) {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

function decodePathnameSafely(rawPathname: string): string | null {
  try {
    return decodeURIComponent(rawPathname);
  } catch {
    return null;
  }
}

function isNormalizedLoginPathname(pathname: string): boolean {
  const normalized = pathname.toLowerCase();
  return normalized === '/login' || normalized.startsWith('/login/');
}

/**
 * Checks whether `url` targets `/login` (including `/login/e2e`, subpaths,
 * matrix/query parameters, and percent-encoded variants), safely ignoring
 * malformed percent sequences.
 */
export function isLoginPath(url: string | null | undefined): boolean {
  if (typeof url !== 'string') return false;
  const trimmed = url.trim();
  if (
    !trimmed.startsWith('/') ||
    trimmed.startsWith('//') ||
    trimmed.includes('\\') ||
    CONTROL_CHAR_REGEX.test(trimmed)
  ) {
    return false;
  }
  const pathEnd = trimmed.search(/[?#;(]/);
  const rawPathname = pathEnd === -1 ? trimmed : trimmed.slice(0, pathEnd);
  const decodedPathname = decodePathnameSafely(rawPathname);
  if (
    decodedPathname !== null &&
    (!decodedPathname.startsWith('/') ||
      decodedPathname.startsWith('//') ||
      decodedPathname.includes('\\') ||
      CONTROL_CHAR_REGEX.test(decodedPathname))
  ) {
    return false;
  }
  return isNormalizedLoginPathname(decodedPathname ?? rawPathname);
}

/**
 * Validates an internal app URL (including `'/'` for guarded Home recovery,
 * plus query strings and fragments), rejecting external/protocol-relative URLs,
 * control characters, malformed path encodings, and `/login` routes.
 */
export function sanitizeReturnUrl(
  url: string | null | undefined,
): string | null {
  if (typeof url !== 'string') return null;
  const trimmed = url.trim();
  if (
    !trimmed.startsWith('/') ||
    trimmed.startsWith('//') ||
    trimmed.includes('\\') ||
    CONTROL_CHAR_REGEX.test(trimmed)
  ) {
    return null;
  }
  const pathEnd = trimmed.search(/[?#;(]/);
  const rawPathname = pathEnd === -1 ? trimmed : trimmed.slice(0, pathEnd);
  const decodedPathname = decodePathnameSafely(rawPathname);
  if (
    decodedPathname === null ||
    !decodedPathname.startsWith('/') ||
    decodedPathname.startsWith('//') ||
    decodedPathname.includes('\\') ||
    CONTROL_CHAR_REGEX.test(decodedPathname)
  ) {
    return null;
  }
  if (isNormalizedLoginPathname(decodedPathname)) {
    return null;
  }
  return trimmed;
}
