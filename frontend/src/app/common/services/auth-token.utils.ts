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

import {Observable, of, throwError} from 'rxjs';
import {catchError, defaultIfEmpty, finalize, map} from 'rxjs/operators';
import {GoogleIdTokenPayload} from './gis.types';

export const UNAUTHORIZED_ORG_DETAIL =
  'User is not authorized to access this application.';

const CLOCK_SKEW_TOLERANCE_MS = 2 * 60 * 1000;
// eslint-disable-next-line no-control-regex
const CONTROL_CHAR_REGEX = /[\u0000-\u001f\u007f]/;
const SESSION_HANDLED_SYMBOL = Symbol('csSessionHandled');

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

export class AuthRenewalError extends Error {
  readonly rejectedToken?: string;

  constructor(message: string, rejectedToken?: string | null) {
    super(message);
    this.name = 'AuthRenewalError';
    const token =
      typeof rejectedToken === 'string' && rejectedToken
        ? rejectedToken
        : undefined;
    // Keep any rejected token non-enumerable so error logs never leak bearer tokens.
    Object.defineProperty(this, 'rejectedToken', {
      value: token,
      enumerable: false,
      configurable: true,
    });
  }
}

export class SessionSupersededError extends AuthRenewalError {
  constructor(
    message = 'Session renewal was superseded.',
    failedToken?: string | null,
  ) {
    super(message, failedToken);
    this.name = 'SessionSupersededError';
    markSessionHandled(this);
  }
}

function isBrandedTarget(
  error: unknown,
): error is object & Record<symbol, unknown> {
  return error !== null && typeof error === 'object';
}

export function toAuthRenewalError(
  error: unknown,
  rejectedToken?: string | null,
): Error {
  const alreadyHandled = isSessionHandledError(error);
  if (error instanceof SessionSupersededError) {
    if (error.rejectedToken || !rejectedToken) {
      return error;
    }
    return new SessionSupersededError(error.message, rejectedToken);
  }
  if (error instanceof AccountMismatchError) {
    return error;
  }
  if (error instanceof AuthRenewalError) {
    if (error.rejectedToken || !rejectedToken) {
      return error;
    }
    const wrapped = new AuthRenewalError(error.message, rejectedToken);
    return alreadyHandled ? markSessionHandled(wrapped) : wrapped;
  }
  if (error instanceof Error && !rejectedToken) {
    return error;
  }
  const message =
    error instanceof Error
      ? error.message
      : typeof error === 'string' && error
        ? error
        : 'Session renewal failed.';
  const wrapped = new AuthRenewalError(message, rejectedToken);
  return alreadyHandled ? markSessionHandled(wrapped) : wrapped;
}

/**
 * Brands an error after session-expiry handling so downstream callers still
 * clean up loading state without emitting a duplicate error snackbar.
 */
export function markSessionHandled<T>(error: T): T {
  if (
    isBrandedTarget(error) &&
    Object.isExtensible(error) &&
    !(SESSION_HANDLED_SYMBOL in error)
  ) {
    Object.defineProperty(error, SESSION_HANDLED_SYMBOL, {
      value: true,
      configurable: true,
    });
  }
  return error;
}

export function isSessionHandledError(error: unknown): boolean {
  return isBrandedTarget(error) && Boolean(error[SESSION_HANDLED_SYMBOL]);
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

function isSafeInternalSegment(path: string): boolean {
  return (
    path.startsWith('/') &&
    !path.startsWith('//') &&
    !path.includes('\\') &&
    !CONTROL_CHAR_REGEX.test(path)
  );
}

function parseInternalUrlCandidate(url: string | null | undefined): {
  trimmed: string;
  rawPathname: string;
  decodedPathname: string | null;
} | null {
  if (typeof url !== 'string') return null;
  const trimmed = url.trim();
  if (!isSafeInternalSegment(trimmed)) {
    return null;
  }
  const pathEnd = trimmed.search(/[?#;(]/);
  const rawPathname = pathEnd === -1 ? trimmed : trimmed.slice(0, pathEnd);
  return {
    trimmed,
    rawPathname,
    decodedPathname: decodePathnameSafely(rawPathname),
  };
}

/**
 * Checks whether `url` targets `/login` (including `/login/e2e`, subpaths,
 * matrix/query parameters, and percent-encoded variants), safely ignoring
 * malformed percent sequences.
 */
export function isLoginPath(url: string | null | undefined): boolean {
  const parsed = parseInternalUrlCandidate(url);
  if (!parsed) return false;
  if (
    parsed.decodedPathname !== null &&
    !isSafeInternalSegment(parsed.decodedPathname)
  ) {
    return false;
  }
  return isNormalizedLoginPathname(
    parsed.decodedPathname ?? parsed.rawPathname,
  );
}

/**
 * Validates an internal app URL (including `'/'` for guarded Home recovery,
 * plus query strings and fragments), rejecting external/protocol-relative URLs,
 * control characters, malformed path encodings, and `/login` routes.
 */
export function sanitizeReturnUrl(
  url: string | null | undefined,
): string | null {
  const parsed = parseInternalUrlCandidate(url);
  if (
    !parsed ||
    parsed.decodedPathname === null ||
    !isSafeInternalSegment(parsed.decodedPathname) ||
    isNormalizedLoginPathname(parsed.decodedPathname)
  ) {
    return null;
  }
  return parsed.trimmed;
}

export interface RouteGuardAuthSession {
  isLoggedIn(): boolean;
  hasRenewableSession(): boolean;
  getValidIdentityPlatformToken$(): Observable<string>;
  onSessionRenewalFailed(targetUrl?: string, error?: Error): void;
  redirectToLogin(targetUrl?: string): void;
}

export interface RouteGuardLoadingIndicator {
  show(): void;
  hide(): void;
}

/**
 * Shared route-guard flow: allows active sessions immediately, waits for one
 * silent renewal with a loading indicator when a renewable expired session is
 * stored, and delegates role authorization once authenticated.
 */
export function canActivateWithSilentRenewal(
  authService: RouteGuardAuthSession,
  loadingService: RouteGuardLoadingIndicator,
  targetUrl: string,
  authorize: () => boolean,
): Observable<boolean> | boolean {
  if (authService.isLoggedIn()) {
    return authorize();
  }
  if (authService.hasRenewableSession()) {
    loadingService.show();
    return authService.getValidIdentityPlatformToken$().pipe(
      defaultIfEmpty(null),
      map(token => {
        if (!token) {
          authService.redirectToLogin(targetUrl);
          return false;
        }
        return authorize();
      }),
      catchError(error => {
        authService.onSessionRenewalFailed(
          targetUrl,
          toAuthRenewalError(error),
        );
        return of(false);
      }),
      finalize(() => loadingService.hide()),
    );
  }
  authService.redirectToLogin(targetUrl);
  return false;
}

export interface UnauthorizedRenewalClient {
  renewAfterUnauthorized$(rejectedToken: string): Observable<string>;
  onSessionRenewalFailed(targetUrl?: string, error?: Error): void;
}

/**
 * Shared 401 token renewal and failure handling for HTTP and streaming callers:
 * tags the rejected token non-enumerably, skips console logging on expected
 * supersede errors, and runs session-expiry handling before rethrowing.
 */
export function renewAfterUnauthorizedWithHandling$(
  authService: UnauthorizedRenewalClient,
  rejectedToken: string,
  logContext: string,
): Observable<string> {
  return authService.renewAfterUnauthorized$(rejectedToken).pipe(
    catchError(renewError => {
      const renewalError = toAuthRenewalError(renewError, rejectedToken);
      if (!(renewalError instanceof SessionSupersededError)) {
        console.error(logContext, renewalError.message);
      }
      authService.onSessionRenewalFailed(undefined, renewalError);
      return throwError(() => markSessionHandled(renewalError));
    }),
  );
}
