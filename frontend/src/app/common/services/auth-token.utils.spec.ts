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

import {
  decodeGoogleJwtPayload,
  extractSessionHints,
  isLoginPath,
  isSameSessionAccount,
  isSessionHandledError,
  markSessionHandled,
  resolveSessionExpiry,
  sanitizeReturnUrl,
} from './auth-token.utils';

function makeJwt(payload: unknown): string {
  const enc = (value: unknown) =>
    btoa(JSON.stringify(value))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
  return `${enc({alg: 'RS256'})}.${enc(payload)}.sig`;
}

describe('auth-token.utils', () => {
  describe('decodeGoogleJwtPayload', () => {
    it('throws for missing segments, invalid JSON, or non-object payloads', () => {
      expect(() => decodeGoogleJwtPayload('not-a-jwt')).toThrowError(
        'Invalid JWT token',
      );
      expect(() => decodeGoogleJwtPayload('a.!!!.c')).toThrow();
      expect(() => decodeGoogleJwtPayload(makeJwt(['array']))).toThrowError(
        'Invalid JWT token',
      );
    });
  });

  describe('resolveSessionExpiry', () => {
    it('uses server exp directly when clock skew is within 2 minutes', () => {
      const nowSec = 1_700_000_000;
      const token = makeJwt({iat: nowSec - 60, exp: nowSec + 3540});
      expect(resolveSessionExpiry(token, nowSec * 1000)).toBe(
        (nowSec + 3540) * 1000,
      );
    });

    it('re-anchors TTL at nowMs when clock skew exceeds 2 minutes', () => {
      const iatSec = 1_700_000_000;
      const token = makeJwt({iat: iatSec, exp: iatSec + 3600});
      const skewedNowMs = (iatSec + 10 * 60) * 1000;
      expect(resolveSessionExpiry(token, skewedNowMs)).toBe(
        skewedNowMs + 3_600_000,
      );
    });

    it('falls back to exp * 1000 when exp <= iat even with clock skew', () => {
      const iatSec = 1_700_000_000;
      const expSec = iatSec - 10;
      const token = makeJwt({iat: iatSec, exp: expSec});
      const skewedNowMs = (iatSec + 10 * 60) * 1000;
      expect(resolveSessionExpiry(token, skewedNowMs)).toBe(expSec * 1000);
    });

    it('throws for missing, zero, negative, or non-finite exp', () => {
      expect(() => resolveSessionExpiry(makeJwt({sub: '1'}))).toThrowError(
        'JWT token missing valid exp claim',
      );
      expect(() => resolveSessionExpiry(makeJwt({exp: 0}))).toThrowError(
        'JWT token missing valid exp claim',
      );
      expect(() => resolveSessionExpiry(makeJwt({exp: -10}))).toThrowError(
        'JWT token missing valid exp claim',
      );
      expect(() =>
        resolveSessionExpiry(makeJwt({exp: '1700000000'})),
      ).toThrowError('JWT token missing valid exp claim');
    });
  });

  describe('extractSessionHints', () => {
    it('extracts login_hint and optional hd, rejecting blank email or missing hd safely', () => {
      const withHd = makeJwt({email: 'user@corp.example', hd: 'corp.example'});
      expect(extractSessionHints(withHd)).toEqual({
        login_hint: 'user@corp.example',
        hd: 'corp.example',
      });

      const withoutHd = makeJwt({email: 'user@example.com'});
      expect(extractSessionHints(withoutHd)).toEqual({
        login_hint: 'user@example.com',
      });

      expect(extractSessionHints(makeJwt({email: '   '}))).toBeNull();
      expect(extractSessionHints(makeJwt({sub: '123'}))).toBeNull();
      expect(extractSessionHints(null)).toBeNull();
      expect(extractSessionHints('invalid')).toBeNull();
    });
  });

  describe('isSameSessionAccount', () => {
    it('requires symmetric sub and symmetric case-insensitive email', () => {
      const a = makeJwt({sub: 'sub-1', email: 'User@Example.com'});
      const aLower = makeJwt({sub: 'sub-1', email: 'user@example.com'});
      const aNoEmail = makeJwt({sub: 'sub-1'});
      const aNoSub = makeJwt({email: 'user@example.com'});
      const otherEmail = makeJwt({sub: 'sub-1', email: 'other@example.com'});
      const otherSub = makeJwt({sub: 'sub-2', email: 'user@example.com'});

      expect(isSameSessionAccount(a, aLower)).toBeTrue();
      expect(isSameSessionAccount(a, aNoEmail)).toBeFalse();
      expect(isSameSessionAccount(aNoEmail, a)).toBeFalse();
      expect(isSameSessionAccount(a, aNoSub)).toBeFalse();
      expect(isSameSessionAccount(aNoSub, a)).toBeFalse();
      expect(isSameSessionAccount(a, otherEmail)).toBeFalse();
      expect(isSameSessionAccount(a, otherSub)).toBeFalse();
      expect(
        isSameSessionAccount(aNoEmail, makeJwt({sub: 'sub-1'})),
      ).toBeTrue();
      expect(isSameSessionAccount(makeJwt({}), makeJwt({}))).toBeFalse();
      expect(isSameSessionAccount(null, a)).toBeFalse();
      expect(isSameSessionAccount('bad', a)).toBeFalse();
    });
  });

  describe('sanitizeReturnUrl and isLoginPath', () => {
    it('preserves valid internal URLs including query params with encoded slashes/newlines', () => {
      expect(sanitizeReturnUrl('/')).toBe('/');
      expect(sanitizeReturnUrl('  /gallery?test=1#top  ')).toBe(
        '/gallery?test=1#top',
      );
      expect(sanitizeReturnUrl('/gallery?q=a%2Fb%0Ac')).toBe(
        '/gallery?q=a%2Fb%0Ac',
      );
      expect(sanitizeReturnUrl('/login-help')).toBe('/login-help');
      expect(isLoginPath('/gallery?test=1')).toBeFalse();
      expect(isLoginPath('/login-help')).toBeFalse();
    });

    it('rejects external, protocol-relative, backslash, control chars, and malformed % encodings safely', () => {
      expect(sanitizeReturnUrl('https://evil.example/path')).toBeNull();
      expect(sanitizeReturnUrl('//evil.example/path')).toBeNull();
      expect(sanitizeReturnUrl('/\\evil.example')).toBeNull();
      expect(sanitizeReturnUrl('/gallery\n?a=1')).toBeNull();
      expect(sanitizeReturnUrl('/gallery%0Atest')).toBeNull();
      expect(sanitizeReturnUrl('/%2f/evil.example')).toBeNull();
      expect(sanitizeReturnUrl('/%ZZ')).toBeNull();
      expect(sanitizeReturnUrl('/login%E0%A4%A')).toBeNull();

      expect(isLoginPath('/%ZZ')).toBeFalse();
      expect(isLoginPath('/login%E0%A4%A')).toBeFalse();
      expect(isLoginPath('//evil.example/login')).toBeFalse();
      expect(isLoginPath(null)).toBeFalse();
    });

    it('detects and blocks all /login path variants case-insensitively', () => {
      const loginVariants = [
        '/login',
        '/LOGIN',
        '/login/e2e',
        '/login/subpath',
        '/login;foo=1',
        '/login(aux:side)',
        '/%6cogin',
        '/login?returnUrl=%2Fgallery%3Ftest%3D1',
      ];
      for (const variant of loginVariants) {
        expect(isLoginPath(variant)).withContext(variant).toBeTrue();
        expect(sanitizeReturnUrl(variant)).withContext(variant).toBeNull();
      }
    });
  });

  describe('markSessionHandled and isSessionHandledError', () => {
    it('brands errors non-enumerably and detects handled state safely', () => {
      const err = new Error('renewal failed');
      expect(isSessionHandledError(err)).toBeFalse();

      const marked = markSessionHandled(err);
      expect(marked).toBe(err);
      expect(isSessionHandledError(err)).toBeTrue();
      expect(Object.keys(err)).toEqual([]);

      const plain = markSessionHandled({detail: 'Unauthorized'});
      expect(isSessionHandledError(plain)).toBeTrue();
      expect(JSON.stringify(plain)).toBe('{"detail":"Unauthorized"}');

      const frozen = Object.freeze(new Error('frozen'));
      expect(isSessionHandledError(markSessionHandled(frozen))).toBeTrue();

      expect(isSessionHandledError('plain string')).toBeFalse();
      expect(isSessionHandledError(null)).toBeFalse();
      expect(isSessionHandledError(undefined)).toBeFalse();
    });
  });
});
