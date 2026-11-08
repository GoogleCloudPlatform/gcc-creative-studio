/**
 * Copyright 2025 Google LLC
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

import {TestBed} from '@angular/core/testing';
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import {Router} from '@angular/router';
import {Auth} from '@angular/fire/auth';
import {AuthService, OIDC_NONCE_KEY} from './auth.service';
import {UserService} from './user.service';
import {environment} from '../../../environments/environment';

function createFakeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({alg: 'RS256', typ: 'JWT'}));
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `${header}.${body}.signature`;
}

describe('AuthService', () => {
  let service: AuthService;
  let httpMock: HttpTestingController;
  const originalClientId = environment.GOOGLE_CLIENT_ID;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        AuthService,
        {provide: Router, useValue: {navigate: jasmine.createSpy('navigate')}},
        {provide: UserService, useValue: {}},
        {provide: Auth, useValue: {signOut: jasmine.createSpy('signOut')}},
      ],
    });
    service = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);
    environment.GOOGLE_CLIENT_ID = 'test-client-id.apps.googleusercontent.com';
  });

  afterEach(() => {
    httpMock.verify();
    environment.GOOGLE_CLIENT_ID = originalClientId;
    sessionStorage.removeItem(OIDC_NONCE_KEY);
    localStorage.removeItem(OIDC_NONCE_KEY);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should decode JWT payload with Base64URL and UTF-8 characters correctly', () => {
    const base64UrlPayload =
      'eyJuYW1lIjoiVG9tYXN6IMWad2l0b8WEIiwic3ViIjoiMTIzLTQ1Nl83ODkifQ';
    const fakeToken = `header.${base64UrlPayload}.signature`;

    const decoded = service.decodeJwtPayload(fakeToken);
    expect(decoded.name).toEqual('Tomasz Świtoń');
    expect(decoded.sub).toEqual('123-456_789');
  });

  it('should throw an error for invalid JWT structure', () => {
    expect(() =>
      service.decodeJwtPayload('invalid_token_without_dots'),
    ).toThrow(new Error('Invalid JWT token'));
  });

  describe('buildGoogleOidcRedirectUrl', () => {
    it('should throw an error if GOOGLE_CLIENT_ID is not configured', () => {
      environment.GOOGLE_CLIENT_ID = '';
      expect(() => service.buildGoogleOidcRedirectUrl()).toThrowError(
        'Google Client ID is not configured.',
      );
    });

    it('should store nonce in sessionStorage and return valid OIDC redirect URL', () => {
      const urlString = service.buildGoogleOidcRedirectUrl();
      // eslint-disable-next-line n/no-unsupported-features/node-builtins
      const url = new URL(urlString);

      expect(url.origin).toEqual('https://accounts.google.com');
      expect(url.pathname).toEqual('/o/oauth2/v2/auth');
      expect(url.searchParams.get('client_id')).toEqual(
        'test-client-id.apps.googleusercontent.com',
      );
      expect(url.searchParams.get('redirect_uri')).toEqual(
        `${window.location.origin}/login`,
      );
      expect(url.searchParams.get('response_type')).toEqual('id_token');
      expect(url.searchParams.get('scope')).toEqual('openid email profile');
      expect(url.searchParams.get('prompt')).toEqual('select_account');

      const storedNonce = sessionStorage.getItem(OIDC_NONCE_KEY);
      expect(storedNonce).toBeTruthy();
      expect(url.searchParams.get('nonce')).toEqual(storedNonce);
    });
  });

  describe('signInForGoogleIdentityPlatform', () => {
    it('should call redirectToUrl with the generated auth URL', () => {
      const redirectSpy = spyOn(service, 'redirectToUrl');
      let completed = false;

      service.signInForGoogleIdentityPlatform().subscribe({
        complete: () => {
          completed = true;
        },
      });

      expect(redirectSpy).toHaveBeenCalled();
      const calledUrl = redirectSpy.calls.mostRecent().args[0];
      expect(calledUrl).toContain(
        'https://accounts.google.com/o/oauth2/v2/auth',
      );
      expect(completed).toBeTrue();
    });

    it('should emit error if buildGoogleOidcRedirectUrl throws', done => {
      environment.GOOGLE_CLIENT_ID = '';
      service.signInForGoogleIdentityPlatform().subscribe({
        next: () => fail('should have failed'),
        error: error => {
          expect(error.message).toContain(
            'Google Client ID is not configured.',
          );
          done();
        },
      });
    });
  });

  describe('hasPendingOidcRedirect', () => {
    it('should return true if pendingOidcHash is set', () => {
      (service as any).pendingOidcHash = '#id_token=sample';
      expect(service.hasPendingOidcRedirect()).toBeTrue();
    });

    it('should return false if pendingOidcHash is empty', () => {
      (service as any).pendingOidcHash = '';
      expect(service.hasPendingOidcRedirect()).toBeFalse();
    });
  });

  describe('completeGoogleOidcRedirect$', () => {
    it('should complete redirect flow, validate nonce, clean URL and sync user', done => {
      const testNonce = 'valid-test-nonce-12345';
      sessionStorage.setItem(OIDC_NONCE_KEY, testNonce);
      const replaceStateSpy = spyOn(window.history, 'replaceState');

      const exp = Math.floor(Date.now() / 1000) + 3600;
      const fakeToken = createFakeJwt({
        nonce: testNonce,
        exp,
        email: 'test@example.com',
        name: 'Test User',
      });
      const rawHash = `#id_token=${fakeToken}&token_type=Bearer`;

      service.completeGoogleOidcRedirect$(rawHash).subscribe({
        next: token => {
          expect(token).toEqual(fakeToken);
          expect(sessionStorage.getItem(OIDC_NONCE_KEY)).toBeNull();
          expect(replaceStateSpy).toHaveBeenCalledWith(
            {},
            document.title,
            window.location.pathname + window.location.search,
          );
          expect(service.getToken()).toEqual(fakeToken);
          done();
        },
        error: err => fail(`Unexpected error: ${err.message}`),
      });

      const req = httpMock.expectOne(`${environment.backendURL}/users/me`);
      expect(req.request.method).toEqual('GET');
      expect(req.request.headers.get('Authorization')).toEqual(
        `Bearer ${fakeToken}`,
      );
      req.flush({id: 'u123', email: 'test@example.com', name: 'Test User'});
    });

    it('should throw error when hash contains error parameter', done => {
      const replaceStateSpy = spyOn(window.history, 'replaceState');
      const rawHash =
        '#error=access_denied&error_description=User+denied+consent';

      service.completeGoogleOidcRedirect$(rawHash).subscribe({
        next: () => fail('should have failed'),
        error: error => {
          expect(error.message).toEqual('User denied consent');
          expect(replaceStateSpy).toHaveBeenCalled();
          done();
        },
      });
    });

    it('should throw error when hash is missing id_token', done => {
      const rawHash = '#token_type=Bearer';

      service.completeGoogleOidcRedirect$(rawHash).subscribe({
        next: () => fail('should have failed'),
        error: error => {
          expect(error.message).toEqual(
            'Google Sign-In response did not contain an ID token.',
          );
          done();
        },
      });
    });

    it('should throw error when nonce does not match expected nonce', done => {
      sessionStorage.setItem(OIDC_NONCE_KEY, 'stored-nonce-abc');
      const exp = Math.floor(Date.now() / 1000) + 3600;
      const fakeToken = createFakeJwt({
        nonce: 'mismatched-nonce-xyz',
        exp,
      });
      const rawHash = `#id_token=${fakeToken}`;

      service.completeGoogleOidcRedirect$(rawHash).subscribe({
        next: () => fail('should have failed'),
        error: error => {
          expect(error.message).toEqual(
            'Invalid OIDC nonce. Please try signing in again.',
          );
          expect(sessionStorage.getItem(OIDC_NONCE_KEY)).toBeNull();
          done();
        },
      });
    });

    it('should throw error when ID token is malformed', done => {
      sessionStorage.setItem(OIDC_NONCE_KEY, 'some-nonce');
      const rawHash = '#id_token=malformed-token-without-parts';

      service.completeGoogleOidcRedirect$(rawHash).subscribe({
        next: () => fail('should have failed'),
        error: error => {
          expect(error.message).toEqual('Failed to decode Google ID token.');
          done();
        },
      });
    });

    it('should validate nonce from localStorage if sessionStorage is missing and clean up both', done => {
      const testNonce = 'local-storage-nonce-999';
      localStorage.setItem(OIDC_NONCE_KEY, testNonce);
      sessionStorage.removeItem(OIDC_NONCE_KEY);

      const exp = Math.floor(Date.now() / 1000) + 3600;
      const fakeToken = createFakeJwt({
        nonce: testNonce,
        exp,
        email: 'test@example.com',
      });
      const rawHash = `#id_token=${fakeToken}`;

      service.completeGoogleOidcRedirect$(rawHash).subscribe({
        next: token => {
          expect(token).toEqual(fakeToken);
          expect(localStorage.getItem(OIDC_NONCE_KEY)).toBeNull();
          expect(sessionStorage.getItem(OIDC_NONCE_KEY)).toBeNull();
          done();
        },
        error: err => fail(`Unexpected error: ${err.message}`),
      });

      const req = httpMock.expectOne(`${environment.backendURL}/users/me`);
      req.flush({id: 'u1', email: 'test@example.com', name: 'Test'});
    });

    it('should roll back session if syncUserWithBackend$ fails', done => {
      const testNonce = 'rollback-test-nonce';
      sessionStorage.setItem(OIDC_NONCE_KEY, testNonce);

      const exp = Math.floor(Date.now() / 1000) + 3600;
      const fakeToken = createFakeJwt({
        nonce: testNonce,
        exp,
        email: 'forbidden@example.com',
      });
      const rawHash = `#id_token=${fakeToken}`;

      service.completeGoogleOidcRedirect$(rawHash).subscribe({
        next: () => fail('should have failed'),
        error: err => {
          expect(err.message).toContain('Forbidden');
          expect(service.getToken()).toBeNull();
          done();
        },
      });

      const req = httpMock.expectOne(`${environment.backendURL}/users/me`);
      req.flush(
        {detail: 'Forbidden: User identity could not be confirmed.'},
        {status: 403, statusText: 'Forbidden'},
      );
    });
  });

  describe('getValidIdentityPlatformToken$', () => {
    it('should emit an error observable when not logged in', done => {
      spyOn(service, 'isLoggedIn').and.returnValue(false);

      service.getValidIdentityPlatformToken$().subscribe({
        next: () => fail('should have failed'),
        error: err => {
          expect(err.message).toEqual(
            'User session is not valid or has expired.',
          );
          done();
        },
      });
    });

    it('should emit the token when logged in', done => {
      spyOn(service, 'isLoggedIn').and.returnValue(true);
      (service as any).firebaseIdToken = 'valid-firebase-token';

      service.getValidIdentityPlatformToken$().subscribe({
        next: token => {
          expect(token).toEqual('valid-firebase-token');
          done();
        },
        error: err => fail(`Unexpected error: ${err.message}`),
      });
    });
  });
});
