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
  HttpHeaders,
  provideHttpClient,
  withInterceptorsFromDi,
} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {Router} from '@angular/router';
import {Auth} from '@angular/fire/auth';
import {EMPTY, firstValueFrom, of, throwError} from 'rxjs';

import {AuthInterceptor} from './auth.interceptor';
import {AuthService} from './common/services/auth.service';
import {SESSION_STORAGE_KEY} from './common/services/auth-session.store';
import {GisInitializeConfig} from './common/services/auth-token.utils';
import {NotificationService} from './common/services/notification.service';
import {UserService} from './common/services/user.service';
import {environment} from '../environments/environment';

function makeJwt(expMs: number, tag = 'x'): string {
  const enc = (o: object) =>
    btoa(JSON.stringify(o))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
  return `${enc({alg: 'RS256'})}.${enc({
    sub: 'sub-1',
    email: 'user@example.com',
    exp: Math.floor(expMs / 1000),
    tag,
  })}.sig`;
}

describe('AuthInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authService: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    authService = jasmine.createSpyObj<AuthService>('AuthService', [
      'getValidIdentityPlatformToken$',
      'renewAfterUnauthorized$',
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
    authService.getValidIdentityPlatformToken$.and.returnValue(of('tok'));

    http.get('/api/thing').subscribe();

    const req = httpMock.expectOne('/api/thing');
    expect(req.request.headers.get('Authorization')).toBe('Bearer tok');
    req.flush({});
  });

  it('passes through requests that already carry an explicit Authorization header', () => {
    const headers = new HttpHeaders().set('Authorization', 'Bearer explicit');

    http.get('/api/users/me', {headers}).subscribe();

    const req = httpMock.expectOne('/api/users/me');
    expect(req.request.headers.get('Authorization')).toBe('Bearer explicit');
    expect(authService.getValidIdentityPlatformToken$).not.toHaveBeenCalled();
    req.flush({});
  });

  it('drops requests quietly when there is no session (no sign-out)', () => {
    authService.getValidIdentityPlatformToken$.and.returnValue(EMPTY);

    http.get('/api/thing').subscribe();

    httpMock.expectNone('/api/thing');
    expect(authService.onSessionRenewalFailed).not.toHaveBeenCalled();
  });

  it('reports renewal errors and rethrows them to the caller', () => {
    authService.getValidIdentityPlatformToken$.and.returnValue(
      throwError(() => new Error('silent sign-in failed')),
    );
    const onError = jasmine.createSpy('onError');

    http.get('/api/thing').subscribe({error: onError});

    expect(onError).toHaveBeenCalled();
    expect(authService.onSessionRenewalFailed).toHaveBeenCalled();
  });

  it('does not report 500 or 403 backend HTTP errors as session failures', () => {
    authService.getValidIdentityPlatformToken$.and.returnValue(of('tok'));
    const on500 = jasmine.createSpy('on500');
    const on403 = jasmine.createSpy('on403');

    http.get('/api/thing').subscribe({error: on500});
    httpMock
      .expectOne('/api/thing')
      .flush('boom', {status: 500, statusText: 'Server Error'});

    http.get('/api/admin-only').subscribe({error: on403});
    httpMock
      .expectOne('/api/admin-only')
      .flush({detail: 'Forbidden'}, {status: 403, statusText: 'Forbidden'});

    expect(on500).toHaveBeenCalled();
    expect(on403).toHaveBeenCalled();
    expect(authService.renewAfterUnauthorized$).not.toHaveBeenCalled();
    expect(authService.onSessionRenewalFailed).not.toHaveBeenCalled();
  });

  it('renews once and retries once on a backend 401 (e.g. slow client clock)', () => {
    authService.getValidIdentityPlatformToken$.and.returnValue(of('stale-tok'));
    authService.renewAfterUnauthorized$.and.returnValue(of('fresh-tok'));
    let responseBody: unknown;

    http.get('/api/thing').subscribe(res => (responseBody = res));

    const first = httpMock.expectOne('/api/thing');
    expect(first.request.headers.get('Authorization')).toBe('Bearer stale-tok');
    first.flush(
      {detail: 'Token expired'},
      {status: 401, statusText: 'Unauthorized'},
    );

    expect(authService.renewAfterUnauthorized$).toHaveBeenCalledOnceWith(
      'stale-tok',
    );
    const retried = httpMock.expectOne('/api/thing');
    expect(retried.request.headers.get('Authorization')).toBe(
      'Bearer fresh-tok',
    );
    retried.flush({ok: true});
    expect(responseBody).toEqual({ok: true});
    expect(authService.onSessionRenewalFailed).not.toHaveBeenCalled();
  });

  it('does not loop if the retried request also returns 401', () => {
    authService.getValidIdentityPlatformToken$.and.returnValue(of('stale-tok'));
    authService.renewAfterUnauthorized$.and.returnValue(of('fresh-tok'));
    const onError = jasmine.createSpy('onError');

    http.get('/api/thing').subscribe({error: onError});

    httpMock
      .expectOne('/api/thing')
      .flush(
        {detail: 'Token expired'},
        {status: 401, statusText: 'Unauthorized'},
      );
    httpMock
      .expectOne('/api/thing')
      .flush(
        {detail: 'Still unauthorized'},
        {status: 401, statusText: 'Unauthorized'},
      );

    expect(authService.renewAfterUnauthorized$).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalled();
  });

  it('skips 401 renewal when backend rejects an unauthorized organization', () => {
    authService.getValidIdentityPlatformToken$.and.returnValue(of('tok'));
    const onError = jasmine.createSpy('onError');

    http.get('/api/thing').subscribe({error: onError});
    httpMock
      .expectOne('/api/thing')
      .flush(
        {detail: 'User is not authorized to access this application.'},
        {status: 401, statusText: 'Unauthorized'},
      );

    expect(authService.renewAfterUnauthorized$).not.toHaveBeenCalled();
    expect(authService.onSessionRenewalFailed).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalled();
  });

  it('leaves non-backend requests untouched', () => {
    http.get('https://example.com/asset.json').subscribe();

    const req = httpMock.expectOne('https://example.com/asset.json');
    expect(req.request.headers.has('Authorization')).toBeFalse();
    expect(authService.getValidIdentityPlatformToken$).not.toHaveBeenCalled();
    req.flush({});
  });
});

describe('AuthInterceptor with real AuthService', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let router: {url: string; navigate: jasmine.Spy; navigateByUrl: jasmine.Spy};
  let notificationService: jasmine.SpyObj<NotificationService>;
  let promptSpy: jasmine.Spy;
  let isLocalBefore: boolean;
  let nextToken: string;
  let shouldFailRenewal: boolean;

  beforeEach(() => {
    localStorage.clear();
    isLocalBefore = environment.isLocal;
    (environment as {isLocal: boolean}).isLocal = false;
    nextToken = makeJwt(Date.now() + 3_600_000, 'fresh');
    shouldFailRenewal = false;

    let gisCb: ((r: {credential?: string}) => void) | null = null;
    promptSpy = jasmine.createSpy('prompt').and.callFake(moment => {
      if (shouldFailRenewal) {
        moment?.({isSkippedMoment: () => true});
      } else {
        gisCb?.({credential: nextToken});
      }
    });
    (window as unknown as {google: unknown}).google = {
      accounts: {
        id: {
          initialize: (cfg: GisInitializeConfig) => {
            gisCb = cfg.callback;
          },
          prompt: promptSpy,
          cancel: () => undefined,
          disableAutoSelect: () => undefined,
        },
      },
    };
    spyOnProperty(
      Object.getPrototypeOf(navigator),
      'locks',
      'get',
    ).and.returnValue({
      request: (
        _name: string,
        optsOrCb: LockOptions | (() => unknown),
        maybeCb?: () => unknown,
      ) => {
        const cb = typeof optsOrCb === 'function' ? optsOrCb : maybeCb!;
        return Promise.resolve().then(cb);
      },
    } as unknown as LockManager);

    router = {
      url: '/gallery/123',
      navigate: jasmine.createSpy('navigate').and.resolveTo(true),
      navigateByUrl: jasmine.createSpy('navigateByUrl').and.resolveTo(true),
    };
    notificationService = jasmine.createSpyObj<NotificationService>(
      'NotificationService',
      ['show'],
    );

    TestBed.configureTestingModule({
      providers: [
        AuthService,
        {provide: Router, useValue: router},
        {provide: NotificationService, useValue: notificationService},
        {provide: UserService, useValue: {getUserDetails: () => null}},
        {
          provide: Auth,
          useValue: {signOut: jasmine.createSpy('signOut').and.resolveTo()},
        },
        {provide: HTTP_INTERCEPTORS, useClass: AuthInterceptor, multi: true},
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    TestBed.inject(AuthService).ngOnDestroy();
    httpMock.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    delete (window as unknown as {google?: unknown}).google;
    (environment as {isLocal: boolean}).isLocal = isLocalBefore;
  });

  it('shares 1 GIS renewal across 3 concurrent requests and sends all 3', async () => {
    localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({
        token: makeJwt(Date.now() - 60_000, 'expired'),
        expiry: Date.now() - 60_000,
      }),
    );

    const p1 = firstValueFrom(http.get('/api/one'));
    const p2 = firstValueFrom(http.get('/api/two'));
    const p3 = firstValueFrom(http.get('/api/three'));

    await new Promise(resolve => setTimeout(resolve, 0));
    expect(promptSpy).toHaveBeenCalledTimes(1);

    for (const url of ['/api/one', '/api/two', '/api/three']) {
      const req = httpMock.expectOne(url);
      expect(req.request.headers.get('Authorization')).toBe(
        `Bearer ${nextToken}`,
      );
      req.flush({url});
    }
    await Promise.all([p1, p2, p3]);

    await new Promise(resolve => setTimeout(resolve, 0));
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
  });

  it('shows 1 toast and preserves returnUrl across staggered 401 failures', async () => {
    const slowClockToken = makeJwt(Date.now() + 20 * 60_000, 'slow-clock');
    localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({
        token: slowClockToken,
        expiry: Date.now() + 20 * 60_000,
      }),
    );
    shouldFailRenewal = true;
    spyOnProperty(document, 'visibilityState', 'get').and.returnValue(
      'visible',
    );

    const err1 = jasmine.createSpy('err1');
    const err2 = jasmine.createSpy('err2');
    http.get('/api/first').subscribe({error: err1});
    http.get('/api/second').subscribe({error: err2});

    httpMock
      .expectOne('/api/first')
      .flush({detail: 'Expired'}, {status: 401, statusText: 'Unauthorized'});
    await new Promise(resolve => setTimeout(resolve, 0));
    router.url = '/login?returnUrl=%2Fgallery%2F123';

    httpMock
      .expectOne('/api/second')
      .flush({detail: 'Expired'}, {status: 401, statusText: 'Unauthorized'});
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(err1).toHaveBeenCalled();
    expect(err2).toHaveBeenCalled();
    expect(notificationService.show).toHaveBeenCalledTimes(1);
    expect(router.navigate).toHaveBeenCalledOnceWith(['/login'], {
      queryParams: {returnUrl: '/gallery/123'},
    });
  });
});
