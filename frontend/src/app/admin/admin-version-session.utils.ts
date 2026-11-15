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

const FIREBASE_SESSION_KEY = 'firebase_session';
const USER_DETAILS_KEY = 'USER_DETAILS';

export interface JwtIdentity {
  sub: string | null;
  email: string | null;
}

export function isWatchedSessionStorageKey(key: string | null): boolean {
  return (
    key === null || key === FIREBASE_SESSION_KEY || key === USER_DETAILS_KEY
  );
}

export function isLoginRouteUrl(rawUrl: string | null | undefined): boolean {
  if (!rawUrl) return false;
  const pathOnly = rawUrl.split(/[?#;]/, 1)[0].trim();
  const firstSegment = pathOnly.split('/').find(seg => seg.length > 0);
  return firstSegment?.toLowerCase() === 'login';
}

export function decodeJwtIdentity(token: string): JwtIdentity | null {
  try {
    if (typeof token !== 'string') return null;
    const parts = token.split('.');
    if (parts.length !== 3 || parts.some(part => !part)) return null;
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64.padEnd(
      base64.length + ((4 - (base64.length % 4)) % 4),
      '=',
    );
    const bytes = Uint8Array.from(atob(padded), ch => ch.charCodeAt(0));
    // eslint-disable-next-line n/no-unsupported-features/node-builtins
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
      return null;
    const payload = parsed as Record<string, unknown>;
    const rawSub = payload['sub'];
    const rawEmail = payload['email'];
    return {
      sub: typeof rawSub === 'string' && rawSub.trim() ? rawSub.trim() : null,
      email:
        typeof rawEmail === 'string' && rawEmail.trim()
          ? rawEmail.trim().toLowerCase()
          : null,
    };
  } catch {
    return null;
  }
}

function parseJsonObject(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export function hasStoredSessionToken(
  storage: Pick<Storage, 'getItem'> | null | undefined,
): boolean {
  if (!storage) return false;
  try {
    const token = parseJsonObject(storage.getItem(FIREBASE_SESSION_KEY))?.[
      'token'
    ];
    return typeof token === 'string' && token.trim().length > 0;
  } catch {
    return false;
  }
}

function readStoredClaims(
  storage: Pick<Storage, 'getItem'> | null | undefined,
) {
  if (!storage) return null;
  try {
    const session = parseJsonObject(storage.getItem(FIREBASE_SESSION_KEY));
    const user = parseJsonObject(storage.getItem(USER_DETAILS_KEY));
    const token = session?.['token'];
    const identity =
      typeof token === 'string' ? decodeJwtIdentity(token) : null;
    const rawEmail = user?.['email'];
    const userEmail =
      typeof rawEmail === 'string' && rawEmail.trim()
        ? rawEmail.trim().toLowerCase()
        : null;
    return {
      tokenSub: identity?.sub ?? null,
      tokenEmail: identity?.email ?? null,
      userEmail,
    };
  } catch {
    return null;
  }
}

export function hasSessionAccountMismatch(
  storage: Pick<Storage, 'getItem'> | null | undefined,
): boolean {
  const claims = readStoredClaims(storage);
  return (
    claims !== null &&
    claims.tokenEmail !== null &&
    claims.userEmail !== null &&
    claims.tokenEmail !== claims.userEmail
  );
}

export function readBrowserSessionOwner(
  storage: Pick<Storage, 'getItem'> | null | undefined,
): string | null {
  const claims = readStoredClaims(storage);
  if (!claims) return null;
  if (claims.tokenEmail) return `email:${claims.tokenEmail}`;
  if (claims.tokenSub) return `sub:${claims.tokenSub}`;
  return claims.userEmail ? `email:${claims.userEmail}` : null;
}
