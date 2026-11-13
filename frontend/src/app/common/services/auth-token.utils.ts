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

export interface GisInitializeConfig {
  client_id: string;
  auto_select?: boolean;
  use_fedcm_for_prompt?: boolean;
  login_hint?: string;
  hd?: string;
  callback: (response: GisCredentialResponse) => void;
}

export interface GisIdApi {
  initialize: (config: GisInitializeConfig) => void;
  prompt: (
    momentListener?: (notification: GisPromptMomentNotification) => void,
  ) => void;
  cancel: () => void;
  disableAutoSelect: () => void;
}

export class AccountMismatchError extends Error {
  constructor() {
    super('Renewed token belongs to a different Google account.');
    this.name = 'AccountMismatchError';
  }
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
      typeof prev.email === 'string' && prev.email
        ? prev.email.toLowerCase()
        : null;
    const nextEmail =
      typeof next.email === 'string' && next.email
        ? next.email.toLowerCase()
        : null;
    if (!prevSub && (!prevEmail || !nextEmail)) {
      return false;
    }
    if (prevEmail && nextEmail && prevEmail !== nextEmail) {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

/**
 * Validates an internal app URL (including `'/'` for guarded Home recovery,
 * plus query strings and fragments), rejecting external/protocol-relative URLs
 * and `/login` routes.
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
  const pathEnd = trimmed.search(/[?#]/);
  const pathname = pathEnd === -1 ? trimmed : trimmed.slice(0, pathEnd);
  if (pathname === '/login' || pathname.startsWith('/login/')) {
    return null;
  }
  return trimmed;
}
