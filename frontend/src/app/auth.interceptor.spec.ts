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
import {
  ActivatedRouteSnapshot,
  Router,
  RouterStateSnapshot,
} from '@angular/router';
import {Auth} from '@angular/fire/auth';
import {MatSnackBar} from '@angular/material/snack-bar';
import {EMPTY, Observable, firstValueFrom, of, throwError} from 'rxjs';

import {AuthInterceptor} from './auth.interceptor';
import {AdminAuthGuard} from './admin/admin-auth.guard';
import {UserRolesEnum} from './common/models/user.model';
import {AuthService} from './common/services/auth.service';
import {SESSION_STORAGE_KEY} from './common/services/auth-session.store';
import {
  GisInitializeConfig,
  isSessionHandledError,
} from './common/services/auth-token.utils';
import {NotificationService} from './common/services/notification.service';
import {UserService} from './common/services/user.service';
import {useTestBedAppInjector} from './testing/app-injector.testing';
import {handleErrorSnackbar} from './utils/handleMessageSnackbar';
import {environment} from '../environments/environment';

function makeJwt(
  expMs: number,
  tag = 'x',
  extra: Record<string, unknown> = {},
): string {
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
    ...extra,
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
    expect(isSessionHandledError(err1.calls.mostRecent().args[0])).toBeTrue();
    expect(isSessionHandledError(err2.calls.mostRecent().args[0])).toBeTrue();
    expect(notificationService.show).toHaveBeenCalledTimes(1);
    expect(router.navigate).toHaveBeenCalledOnceWith(['/login'], {
      queryParams: {returnUrl: '/gallery/123'},
    });
  });

  it('suppresses duplicate error snackbars via markSessionHandled on pre-request and 401 failures while still notifying subscribers', async () => {
    useTestBedAppInjector();
    const snackBar = {} as MatSnackBar;
    const consoleErrSpy = spyOn(console, 'error');

    // 1. Pre-request renewal failure
    localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({
        token: makeJwt(Date.now() - 60_000, 'expired'),
        expiry: Date.now() - 60_000,
      }),
    );
    shouldFailRenewal = true;
    const preErr = jasmine.createSpy('preErr');
    http.get('/api/workspace').subscribe({error: preErr});
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(preErr).toHaveBeenCalled();
    const preThrown = preErr.calls.mostRecent().args[0];
    expect(isSessionHandledError(preThrown)).toBeTrue();
    handleErrorSnackbar(snackBar, preThrown, 'Load Workspace');

    // Only the 1 info session-expired toast from AuthService; zero error snackbars.
    expect(notificationService.show).toHaveBeenCalledTimes(1);
    expect(notificationService.show.calls.mostRecent().args[1]).toBe('info');

    // 2. Post-401 renewal failure
    notificationService.show.calls.reset();
    const validToken = makeJwt(Date.now() + 20 * 60_000, 'slow');
    localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({token: validToken, expiry: Date.now() + 20 * 60_000}),
    );
    const postErr = jasmine.createSpy('postErr');
    http.get('/api/items').subscribe({error: postErr});
    httpMock
      .expectOne('/api/items')
      .flush({detail: 'Expired'}, {status: 401, statusText: 'Unauthorized'});
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(postErr).toHaveBeenCalled();
    const postThrown = postErr.calls.mostRecent().args[0];
    expect(isSessionHandledError(postThrown)).toBeTrue();
    handleErrorSnackbar(snackBar, postThrown, 'Load Items');

    expect(notificationService.show).toHaveBeenCalledTimes(1);
    expect(notificationService.show.calls.mostRecent().args[1]).toBe('info');

    // 3. Regular 500 error is NOT suppressed.
    localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({token: validToken, expiry: Date.now() + 20 * 60_000}),
    );
    const err500 = jasmine.createSpy('err500');
    http.get('/api/other').subscribe({error: err500});
    httpMock
      .expectOne('/api/other')
      .flush({detail: 'Server boom'}, {status: 500, statusText: 'Error'});
    expect(
      isSessionHandledError(err500.calls.mostRecent().args[0]),
    ).toBeFalse();
    handleErrorSnackbar(snackBar, err500.calls.mostRecent().args[0], 'Other');
    expect(notificationService.show).toHaveBeenCalledTimes(2);
    expect(notificationService.show.calls.mostRecent().args[1]).toBe('error');
    expect(consoleErrSpy).toHaveBeenCalled();
  });

  it('recovers pendingNavigationUrl on wake via AdminAuthGuard and rejects non-admin sessions with expireSession', async () => {
    TestBed.resetTestingModule();
    let visibility: DocumentVisibilityState = 'hidden';
    spyOnProperty(document, 'visibilityState', 'get').and.callFake(
      () => visibility,
    );
    const disableAutoSelectSpy = jasmine.createSpy('disableAutoSelect');
    let gisCb: ((r: {credential?: string}) => void) | null = null;
    (window as unknown as {google: unknown}).google = {
      accounts: {
        id: {
          initialize: (cfg: GisInitializeConfig) => {
            gisCb = cfg.callback;
          },
          prompt: () => {
            gisCb?.({credential: nextToken});
          },
          cancel: () => undefined,
          disableAutoSelect: disableAutoSelectSpy,
        },
      },
    };
    localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({
        token: makeJwt(Date.now() - 60_000, 'expired'),
        expiry: Date.now() - 60_000,
      }),
    );

    const route = {} as ActivatedRouteSnapshot;
    const state = {url: '/admin'} as RouterStateSnapshot;

    const routerSpy = {
      url: '/',
      navigate: jasmine.createSpy('navigate').and.resolveTo(true),
      navigateByUrl: jasmine
        .createSpy('navigateByUrl')
        .and.callFake(async (url: string) => {
          if (url === '/admin') {
            void TestBed.inject(AdminAuthGuard).canActivate(route, state);
          }
          return true;
        }),
    };

    TestBed.configureTestingModule({
      providers: [
        AuthService,
        AdminAuthGuard,
        {provide: Router, useValue: routerSpy},
        {provide: NotificationService, useValue: notificationService},
        {
          provide: UserService,
          useValue: {
            getUserDetails: () => ({
              email: 'viewer@example.com',
              roles: [UserRolesEnum.USER],
            }),
          },
        },
        {provide: MatSnackBar, useValue: {}},
        {
          provide: Auth,
          useValue: {signOut: jasmine.createSpy('signOut').and.resolveTo()},
        },
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
      ],
    });
    useTestBedAppInjector();
    httpMock = TestBed.inject(HttpTestingController);
    const adminGuard = TestBed.inject(AdminAuthGuard);
    const authService = TestBed.inject(AuthService);

    // Cold boot while hidden: guard defers without clearing session.
    const initialResult = adminGuard.canActivate(
      route,
      state,
    ) as Observable<boolean>;
    expect(await firstValueFrom(initialResult)).toBeFalse();
    expect(authService.hasRenewableSession()).toBeTrue();

    // Tab wakes: AuthService renews, navigates to /admin, guard rejects non-admin via expireSession.
    visibility = 'visible';
    window.dispatchEvent(new Event('focus'));
    await new Promise(resolve => setTimeout(resolve, 20));

    expect(routerSpy.navigateByUrl).toHaveBeenCalledWith('/admin');
    expect(authService.hasRenewableSession()).toBeFalse();
    expect(disableAutoSelectSpy).not.toHaveBeenCalled();
    expect(routerSpy.navigateByUrl).toHaveBeenCalledWith('/login');
    httpMock.match(r => r.url.endsWith('/users/me')).forEach(r => r.flush({}));
  });

  it('preserves Account B and suppresses toast when a hung Account A renewal collides with a cross-tab switch', async () => {
    const tokenA = makeJwt(Date.now() - 60_000, 'acct-a-expired', {
      sub: 'sub-a',
      email: 'a@example.com',
    });
    const tokenB = makeJwt(Date.now() + 3_600_000, 'acct-b', {
      sub: 'sub-b',
      email: 'b@example.com',
    });

    localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({token: tokenA, expiry: Date.now() - 60_000}),
    );
    const authService = TestBed.inject(AuthService);
    const reloadSpy = spyOn(
      authService as unknown as {reloadToHome: () => void},
      'reloadToHome',
    );
    promptSpy.and.stub(); // hang silent GIS prompt

    const onHungErr = jasmine.createSpy('onHungErr');
    http.get('/api/account-a-data').subscribe({error: onHungErr});
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(promptSpy).toHaveBeenCalledTimes(1);

    const expiryB = Date.now() + 3_600_000;
    localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({token: tokenB, expiry: expiryB}),
    );
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: SESSION_STORAGE_KEY,
        newValue: JSON.stringify({token: tokenB, expiry: expiryB}),
      }),
    );
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(onHungErr).toHaveBeenCalled();
    expect(
      isSessionHandledError(onHungErr.calls.mostRecent().args[0]),
    ).toBeTrue();
    expect(JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY)!).token).toBe(
      tokenB,
    );
    expect(notificationService.show).not.toHaveBeenCalled();
    const switchMeReq = httpMock.expectOne(r => r.url.endsWith('/users/me'));
    expect(switchMeReq.request.headers.get('Authorization')).toBe(
      `Bearer ${tokenB}`,
    );
    switchMeReq.flush({email: 'b@example.com'});
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it('preserves Account B and suppresses toast when late Account A 401s arrive during or after a cross-tab switch', async () => {
    const tokenAValid = makeJwt(Date.now() + 20 * 60_000, 'acct-a-valid', {
      sub: 'sub-a',
      email: 'a@example.com',
    });
    const tokenB = makeJwt(Date.now() + 3_600_000, 'acct-b', {
      sub: 'sub-b',
      email: 'b@example.com',
    });

    localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({token: tokenAValid, expiry: Date.now() + 20 * 60_000}),
    );
    const authService = TestBed.inject(AuthService);
    const reloadSpy = spyOn(
      authService as unknown as {reloadToHome: () => void},
      'reloadToHome',
    );

    const errDuring = jasmine.createSpy('errDuring');
    const errAfter = jasmine.createSpy('errAfter');
    http.get('/api/during-switch').subscribe({error: errDuring});
    http.get('/api/after-sync').subscribe({error: errAfter});

    const reqDuring = httpMock.expectOne('/api/during-switch');
    const reqAfter = httpMock.expectOne('/api/after-sync');
    expect(reqDuring.request.headers.get('Authorization')).toBe(
      `Bearer ${tokenAValid}`,
    );

    const expiryB = Date.now() + 3_600_000;
    localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({token: tokenB, expiry: expiryB}),
    );
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: SESSION_STORAGE_KEY,
        newValue: JSON.stringify({token: tokenB, expiry: expiryB}),
      }),
    );

    // 401 arrives while switchingAccount === true
    reqDuring.flush(
      {detail: 'Expired'},
      {status: 401, statusText: 'Unauthorized'},
    );
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(errDuring).toHaveBeenCalled();
    expect(JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY)!).token).toBe(
      tokenB,
    );
    expect(notificationService.show).not.toHaveBeenCalled();

    // Flush Account B /users/me -> switchingAccount resets to false, reloadToHome called
    const switchMeReq = httpMock.expectOne(r => r.url.endsWith('/users/me'));
    switchMeReq.flush({email: 'b@example.com'});
    expect(reloadSpy).toHaveBeenCalledTimes(1);

    // 401 arrives AFTER reloadToHome() / switchingAccount === false
    reqAfter.flush(
      {detail: 'Expired'},
      {status: 401, statusText: 'Unauthorized'},
    );
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(errAfter).toHaveBeenCalled();
    expect(JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY)!).token).toBe(
      tokenB,
    );
    expect(notificationService.show).not.toHaveBeenCalled();
    expect(promptSpy).not.toHaveBeenCalled();
  });
});
