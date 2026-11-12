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

import {TestBed} from '@angular/core/testing';
import {
  HTTP_INTERCEPTORS,
  HttpClient,
  provideHttpClient,
  withInterceptorsFromDi,
} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {EMPTY, of, throwError} from 'rxjs';

import {AuthInterceptor} from './auth.interceptor';
import {AuthService} from './common/services/auth.service';

describe('AuthInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authService: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    authService = jasmine.createSpyObj<AuthService>('AuthService', [
      'getValidIdentityPlatformToken$',
      'hasRenewableSession',
      'onSessionRenewalFailed',
    ]);
    TestBed.configureTestingModule({
      providers: [
        {provide: AuthService, useValue: authService},
        {provide: HTTP_INTERCEPTORS, useClass: AuthInterceptor, multi: true},
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('adds the bearer token to backend requests', () => {
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(of('tok'));

    http.get('/api/thing').subscribe();

    const req = httpMock.expectOne('/api/thing');
    expect(req.request.headers.get('Authorization')).toBe('Bearer tok');
    req.flush({});
  });

  it('drops requests quietly when there is no session (no sign-out)', () => {
    authService.hasRenewableSession.and.returnValue(false);
    authService.getValidIdentityPlatformToken$.and.returnValue(EMPTY);

    http.get('/api/thing').subscribe();

    httpMock.expectNone('/api/thing');
    expect(authService.onSessionRenewalFailed).not.toHaveBeenCalled();
  });

  it('reports a renewal failure when a session existed but produced no token', () => {
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(EMPTY);

    http.get('/api/thing').subscribe();

    httpMock.expectNone('/api/thing');
    expect(authService.onSessionRenewalFailed).toHaveBeenCalled();
  });

  it('reports renewal errors and rethrows them to the caller', () => {
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(
      throwError(() => new Error('silent sign-in failed')),
    );
    const onError = jasmine.createSpy('onError');

    http.get('/api/thing').subscribe({error: onError});

    expect(onError).toHaveBeenCalled();
    expect(authService.onSessionRenewalFailed).toHaveBeenCalled();
  });

  it('does not report backend HTTP errors as session failures', () => {
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(of('tok'));
    const onError = jasmine.createSpy('onError');

    http.get('/api/thing').subscribe({error: onError});
    httpMock
      .expectOne('/api/thing')
      .flush('boom', {status: 500, statusText: 'Server Error'});

    expect(onError).toHaveBeenCalled();
    expect(authService.onSessionRenewalFailed).not.toHaveBeenCalled();
  });

  it('leaves non-backend requests untouched', () => {
    http.get('https://example.com/asset.json').subscribe();

    const req = httpMock.expectOne('https://example.com/asset.json');
    expect(req.request.headers.has('Authorization')).toBeFalse();
    expect(authService.getValidIdentityPlatformToken$).not.toHaveBeenCalled();
    req.flush({});
  });
});
