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

import {TestBed, fakeAsync, flushMicrotasks, tick} from '@angular/core/testing';
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import {Router} from '@angular/router';
import {Auth} from '@angular/fire/auth';
import {firstValueFrom} from 'rxjs';
import {AuthService} from './auth.service';
import {NotificationService} from './notification.service';
import {UserService} from './user.service';
import {RENEW_RETRY_MS, SESSION_STORAGE_KEY} from './auth-session.store';
import {
  GisInitializeConfig,
  GisPromptMomentNotification,
  resolveSessionExpiry,
  sanitizeReturnUrl,
} from './auth-token.utils';
import {environment} from '../../../environments/environment';

type PromptBehavior = 'credential' | 'skip' | 'dismissed' | 'hang';

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
    sub: 'sub-user-1',
    email: 'user@example.com',
    exp: Math.floor(expMs / 1000),
    tag,
    ...extra,
  })}.sig`;
}

const writeSession = (token: string, expiry: number) =>
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({token, expiry}));

const flushTimers = () => new Promise(resolve => setTimeout(resolve, 0));

describe('AuthService', () => {
  let router: {url: string; navigate: jasmine.Spy; navigateByUrl: jasmine.Spy};
  let notificationService: jasmine.SpyObj<NotificationService>;
  let authMock: Record<string, unknown>;
  let gis: {
    initialize: jasmine.Spy;
    prompt: jasmine.Spy;
    cancel: jasmine.Spy;
    disableAutoSelect: jasmine.Spy;
  };
  let promptBehavior: PromptBehavior;
  let nextGisToken: string;
  let httpMock: HttpTestingController;
  let isLocalBeforeTest: boolean;
  let gisCallback: ((r: {credential?: string}) => void) | null;
  let locksSpy: jasmine.Spy;

  const createService = () => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        AuthService,
        {provide: Router, useValue: router},
        {provide: NotificationService, useValue: notificationService},
        {provide: UserService, useValue: {getUserDetails: () => null}},
        {provide: Auth, useValue: authMock},
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    return TestBed.inject(AuthService);
  };

  beforeEach(() => {
    localStorage.clear();
    // Other specs mutate the shared environment object; pin deployed mode.
    isLocalBeforeTest = environment.isLocal;
    (environment as {isLocal: boolean}).isLocal = false;
    router = {
      url: '/home',
      navigate: jasmine.createSpy('navigate').and.resolveTo(true),
      navigateByUrl: jasmine.createSpy('navigateByUrl').and.resolveTo(true),
    };
    notificationService = jasmine.createSpyObj<NotificationService>(
      'NotificationService',
      ['show'],
    );
    authMock = {signOut: jasmine.createSpy('signOut').and.resolveTo()};
    promptBehavior = 'credential';
    nextGisToken = makeJwt(Date.now() + 3_600_000, 'renewed');

    gisCallback = null;
    gis = {
      initialize: jasmine
        .createSpy('initialize')
        .and.callFake((cfg: GisInitializeConfig) => {
          gisCallback = cfg.callback;
        }),
      prompt: jasmine
        .createSpy('prompt')
        .and.callFake((moment?: (n: GisPromptMomentNotification) => void) => {
          if (promptBehavior === 'credential') {
            gisCallback?.({credential: nextGisToken});
          } else if (promptBehavior === 'skip') {
            moment?.({isSkippedMoment: () => true});
          } else if (promptBehavior === 'dismissed') {
            moment?.({
              isDismissedMoment: () => true,
              getDismissedReason: () => 'cancel_called',
            });
          }
        }),
      cancel: jasmine.createSpy('cancel'),
      disableAutoSelect: jasmine.createSpy('disableAutoSelect'),
    };
    (window as unknown as {google: unknown}).google = {accounts: {id: gis}};

    // Run cross-tab locked sections immediately in tests unless overridden.
    locksSpy = spyOnProperty(
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
  });

  afterEach(() => {
    httpMock?.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    delete (window as unknown as {google?: unknown}).google;
    (environment as {isLocal: boolean}).isLocal = isLocalBeforeTest;
  });

  it('decodes JWT payloads with Base64URL and UTF-8 characters', () => {
    const service = createService();
    const payload =
      'eyJuYW1lIjoiVG9tYXN6IMWad2l0b8WEIiwic3ViIjoiMTIzLTQ1Nl83ODkifQ';
    const decoded = service.decodeJwtPayload(`header.${payload}.signature`);
    expect(decoded.name).toEqual('Tomasz Świtoń');
    expect(decoded.sub).toEqual('123-456_789');
  });

  it('throws for invalid JWT structure or missing exp claim', () => {
    const service = createService();
    expect(() =>
      service.decodeJwtPayload('invalid_token_without_dots'),
    ).toThrow(new Error('Invalid JWT token'));
    const noExp = `${btoa('{}')}.${btoa(JSON.stringify({sub: '1'}))}.sig`;
    expect(() => resolveSessionExpiry(noExp)).toThrow(
      new Error('JWT token missing valid exp claim'),
    );
  });

  it('adjusts expiry using iat when the client clock is skewed fast or slow', () => {
    const serverNowSec = 1_700_000_000;
    const token = makeJwt((serverNowSec + 3600) * 1000, 'skew', {
      iat: serverNowSec,
    });
    // Client clock 58 minutes fast: without skew correction, only 2 min remain.
    const fastClientNow = (serverNowSec + 58 * 60) * 1000;
    expect(resolveSessionExpiry(token, fastClientNow)).toBe(
      fastClientNow + 3_600_000,
    );
    // Client clock 30 minutes slow: without skew correction, 90 min remain.
    const slowClientNow = (serverNowSec - 30 * 60) * 1000;
    expect(resolveSessionExpiry(token, slowClientNow)).toBe(
      slowClientNow + 3_600_000,
    );
  });

  it('applies iat clock-skew correction and rejects missing exp inside AuthService login and renewal', async () => {
    const nowMs = Date.now();
    // Simulate a client clock 58 minutes fast relative to Google's iat.
    const skewedIatSec = Math.floor(nowMs / 1000) - 58 * 60;
    const skewedLoginToken = makeJwt(
      (skewedIatSec + 3600) * 1000,
      'skew-login',
      {iat: skewedIatSec},
    );
    nextGisToken = skewedLoginToken;
    const service = createService();

    const signInPromise = firstValueFrom(
      service.signInForGoogleIdentityPlatform(),
    );
    await flushTimers();
    httpMock
      .expectOne(r => r.url.endsWith('/users/me'))
      .flush({email: 'user@example.com'});
    expect(await signInPromise).toBe(skewedLoginToken);

    const savedAfterLogin = JSON.parse(
      localStorage.getItem(SESSION_STORAGE_KEY)!,
    );
    expect(savedAfterLogin.expiry - nowMs).toBeGreaterThan(50 * 60_000);
    expect(service.isLoggedIn()).toBeTrue();

    // Force renewal with another skewed-iat token and verify persisted expiry.
    const skewedRenewToken = makeJwt(
      (skewedIatSec + 3600) * 1000,
      'skew-renew',
      {iat: skewedIatSec},
    );
    nextGisToken = skewedRenewToken;
    expect(
      await firstValueFrom(service.renewAfterUnauthorized$(skewedLoginToken)),
    ).toBe(skewedRenewToken);
    await flushTimers();
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});

    const savedAfterRenew = JSON.parse(
      localStorage.getItem(SESSION_STORAGE_KEY)!,
    );
    expect(savedAfterRenew.expiry - nowMs).toBeGreaterThan(50 * 60_000);

    // Token missing exp must be rejected by AuthService during renewal.
    const enc = (o: object) =>
      btoa(JSON.stringify(o))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '');
    nextGisToken = `${enc({alg: 'RS256'})}.${enc({
      sub: 'sub-user-1',
      email: 'user@example.com',
    })}.sig`;
    await expectAsync(
      firstValueFrom(service.renewAfterUnauthorized$(skewedRenewToken)),
    ).toBeRejectedWithError(/missing valid exp claim/);
  });

  it('sanitizes internal returnUrl values and rejects unsafe or login paths', () => {
    expect(sanitizeReturnUrl('/')).toBe('/');
    expect(sanitizeReturnUrl('/workbench?storyboardId=42#scene-3')).toBe(
      '/workbench?storyboardId=42#scene-3',
    );
    expect(sanitizeReturnUrl('https://evil.example/phish')).toBeNull();
    expect(sanitizeReturnUrl('//evil.example/phish')).toBeNull();
    expect(sanitizeReturnUrl('/\\evil.example')).toBeNull();
    expect(sanitizeReturnUrl('/login')).toBeNull();
    expect(sanitizeReturnUrl('/login?returnUrl=/home')).toBeNull();
  });

  it('reuses the cached token outside the renewal window', async () => {
    const token = makeJwt(Date.now() + 30 * 60_000);
    writeSession(token, Date.now() + 30 * 60_000);
    const service = createService();

    expect(await firstValueFrom(service.getValidIdentityPlatformToken$())).toBe(
      token,
    );
    expect(gis.prompt).not.toHaveBeenCalled();
  });

  it('returns the still-valid token immediately inside the buffer while renewing in the background', async () => {
    const current = makeJwt(Date.now() + 2 * 60_000, 'init', {
      email: 'admin@example.com',
      hd: 'example.com',
    });
    nextGisToken = makeJwt(Date.now() + 3_600_000, 'renewed', {
      email: 'admin@example.com',
      hd: 'example.com',
    });
    writeSession(current, Date.now() + 2 * 60_000);
    const service = createService();

    // Must resolve immediately to the still-valid token without waiting on GIS.
    const token = await firstValueFrom(
      service.getValidIdentityPlatformToken$(),
    );
    expect(token).toBe(current);

    await flushTimers();
    const initCfg = gis.initialize.calls.mostRecent().args[0];
    expect(initCfg.auto_select).toBeTrue();
    expect(initCfg.login_hint).toBe('admin@example.com');
    expect(initCfg.hd).toBe('example.com');
    expect(JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY)!).token).toBe(
      nextGisToken,
    );
    await flushTimers();
    const handOff = httpMock.expectOne(r => r.url.endsWith('/users/me'));
    expect(handOff.request.headers.get('Authorization')).toBe(
      `Bearer ${nextGisToken}`,
    );
    handOff.flush({email: 'admin@example.com'});
  });

  it('never stalls in-buffer requests even when the silent GIS prompt hangs', async () => {
    const current = makeJwt(Date.now() + 2 * 60_000);
    writeSession(current, Date.now() + 2 * 60_000);
    promptBehavior = 'hang';
    const service = createService();

    expect(await firstValueFrom(service.getValidIdentityPlatformToken$())).toBe(
      current,
    );
    await service.logout();
  });

  it('shares one renewal between concurrent expired callers', async () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();

    const [a, b] = await Promise.all([
      firstValueFrom(service.getValidIdentityPlatformToken$()),
      firstValueFrom(service.getValidIdentityPlatformToken$()),
    ]);

    expect(a).toBe(nextGisToken);
    expect(b).toBe(nextGisToken);
    expect(gis.prompt).toHaveBeenCalledTimes(1);
    await flushTimers();
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
  });

  it('rejects a renewed token for a different sub and expires the session once', async () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    nextGisToken = makeJwt(Date.now() + 3_600_000, 'swapped', {
      sub: 'sub-different-user',
      email: 'other@example.com',
    });
    const service = createService();

    await expectAsync(
      firstValueFrom(service.getValidIdentityPlatformToken$()),
    ).toBeRejected();

    // Downstream caller passing a different URL must be an idempotent no-op.
    service.onSessionRenewalFailed('/other');

    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(notificationService.show).toHaveBeenCalledTimes(1);
    expect(router.navigate).toHaveBeenCalledOnceWith(['/login'], {
      queryParams: {returnUrl: '/home'},
    });
    await flushTimers();
    httpMock.expectNone(r => r.url.endsWith('/users/me'));
  });

  it('accepts case-insensitive email match on renewal and rejects email mismatch with same sub', async () => {
    writeSession(
      makeJwt(Date.now() - 60_000, 'init', {email: 'User@Example.com'}),
      Date.now() - 60_000,
    );
    nextGisToken = makeJwt(Date.now() + 3_600_000, 'cased', {
      email: 'user@example.com',
    });
    const service = createService();

    expect(await firstValueFrom(service.getValidIdentityPlatformToken$())).toBe(
      nextGisToken,
    );
    await flushTimers();
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});

    // Same sub, different email -> rejected and expired.
    nextGisToken = makeJwt(Date.now() + 3_600_000, 'diff-email', {
      email: 'intruder@example.com',
    });
    await expectAsync(
      firstValueFrom(service.renewAfterUnauthorized$(service.getToken()!)),
    ).toBeRejected();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('refuses silent renewal without prompting when stored JWT has no account hint', async () => {
    writeSession('not-a-valid-jwt', Date.now() - 60_000);
    const service = createService();

    await expectAsync(
      firstValueFrom(service.getValidIdentityPlatformToken$()),
    ).toBeRejectedWithError(/missing account hint/);
    expect(gis.prompt).not.toHaveBeenCalled();
  });

  it('backs off for the rest of the buffer after a skipped or dismissed prompt, even across focus events', async () => {
    const current = makeJwt(Date.now() + 3 * 60_000);
    writeSession(current, Date.now() + 3 * 60_000);
    promptBehavior = 'dismissed';
    const service = createService();

    expect(await firstValueFrom(service.getValidIdentityPlatformToken$())).toBe(
      current,
    );
    await flushTimers();
    expect(gis.prompt).toHaveBeenCalledTimes(1);
    expect(gis.cancel).toHaveBeenCalled();

    // Window focus and follow-up requests inside the same buffer must NOT re-prompt.
    window.dispatchEvent(new Event('focus'));
    expect(await firstValueFrom(service.getValidIdentityPlatformToken$())).toBe(
      current,
    );
    await flushTimers();
    expect(gis.prompt).toHaveBeenCalledTimes(1);
  });

  it('times out a hung silent prompt after 10s with fake timers', fakeAsync(() => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    promptBehavior = 'hang';
    const service = createService();
    let error: Error | undefined;

    service.renewSession$().subscribe({error: e => (error = e)});
    tick(0);
    tick(9_999);
    expect(error).toBeUndefined();
    tick(1);
    expect(error?.message).toContain('timed out');
    expect(gis.cancel).toHaveBeenCalled();
    service.ngOnDestroy();
  }));

  it('enforces RENEW_RETRY_MS cooldown on the request path after a failed renewal, then retries', fakeAsync(() => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    promptBehavior = 'skip';
    const service = createService();
    let firstErr: unknown;
    let secondErr: unknown;
    let recovered: string | undefined;

    service.getValidIdentityPlatformToken$().subscribe({
      error: e => (firstErr = e),
    });
    tick();
    expect(firstErr).toBeDefined();
    expect(gis.prompt).toHaveBeenCalledTimes(1);

    // Immediate second request during cooldown fails fast without calling GIS.
    service.getValidIdentityPlatformToken$().subscribe({
      error: e => (secondErr = e),
    });
    tick();
    expect(secondErr).toBeDefined();
    expect(gis.prompt).toHaveBeenCalledTimes(1);

    // After RENEW_RETRY_MS cooldown expires, a new attempt succeeds.
    promptBehavior = 'credential';
    nextGisToken = makeJwt(Date.now() + 3_600_000 + RENEW_RETRY_MS);
    tick(RENEW_RETRY_MS);
    service.getValidIdentityPlatformToken$().subscribe({
      next: t => (recovered = t),
    });
    tick();
    expect(recovered).toBe(nextGisToken);
    expect(gis.prompt).toHaveBeenCalledTimes(2);
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
    service.ngOnDestroy();
  }));

  it('falls back cleanly when navigator.locks is unavailable', async () => {
    locksSpy.and.returnValue(undefined as unknown as LockManager);
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();

    expect(await firstValueFrom(service.getValidIdentityPlatformToken$())).toBe(
      nextGisToken,
    );
    await flushTimers();
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
  });

  it('adopts the fresh token after waiting on lock contention without prompting twice', async () => {
    let releaseLock!: () => void;
    const lockGate = new Promise<void>(resolve => {
      releaseLock = resolve;
    });
    locksSpy.and.returnValue({
      request: async (
        _name: string,
        _opts: LockOptions,
        cb: () => Promise<unknown>,
      ) => {
        await lockGate;
        return cb();
      },
    } as unknown as LockManager);

    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();

    const pending = firstValueFrom(service.renewSession$());
    // While waiting on the lock, Tab 1 saves a fresh token.
    const freshFromTab1 = makeJwt(Date.now() + 3_600_000, 'tab1');
    writeSession(freshFromTab1, Date.now() + 3_600_000);
    releaseLock();

    expect(await pending).toBe(freshFromTab1);
    expect(gis.prompt).not.toHaveBeenCalled();
    await flushTimers();
    httpMock.expectNone(r => r.url.endsWith('/users/me'));
  });

  it('keeps an expired session at startup and renews instead of redirecting', async () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();

    expect(service.isLoggedIn()).toBeFalse();
    expect(service.hasRenewableSession()).toBeTrue();
    expect(router.navigate).not.toHaveBeenCalled();

    expect(await firstValueFrom(service.getValidIdentityPlatformToken$())).toBe(
      nextGisToken,
    );
    await flushTimers();
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
  });

  it('completes empty with no session (unchanged contract)', async () => {
    const service = createService();
    const result = await firstValueFrom(
      service.getValidIdentityPlatformToken$(),
      {defaultValue: null},
    );
    expect(result).toBeNull();
    expect(gis.prompt).not.toHaveBeenCalled();
  });

  it('navigates to login without signing out again when another tab signs out', () => {
    writeSession(makeJwt(Date.now() + 30 * 60_000), Date.now() + 30 * 60_000);
    const service = createService();
    spyOn(service, 'logout');

    window.dispatchEvent(
      new StorageEvent('storage', {key: SESSION_STORAGE_KEY, newValue: null}),
    );

    expect(router.navigate).toHaveBeenCalledWith(['/login']);
    expect(service.logout).not.toHaveBeenCalled();
    expect(gis.disableAutoSelect).not.toHaveBeenCalled();
    expect(notificationService.show).not.toHaveBeenCalled();
  });

  it('logout turns off Google auto sign-in, clears the session, and makes no server call', async () => {
    writeSession(makeJwt(Date.now() + 30 * 60_000), Date.now() + 30 * 60_000);
    const service = createService();

    await service.logout();

    expect(gis.disableAutoSelect).toHaveBeenCalled();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(router.navigateByUrl).toHaveBeenCalledWith('/login');
    expect(authMock['signOut']).toHaveBeenCalled();
  });

  it('expireSession keeps Google auto sign-in enabled', async () => {
    writeSession(makeJwt(Date.now() + 30 * 60_000), Date.now() + 30 * 60_000);
    const service = createService();

    await service.expireSession();

    expect(gis.disableAutoSelect).not.toHaveBeenCalled();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('remembers pending navigation URL (including Home "/") when offline and navigates on reconnect', async () => {
    let online = false;
    spyOnProperty(navigator, 'onLine', 'get').and.callFake(() => online);
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();

    service.onSessionRenewalFailed('/');
    expect(service.hasRenewableSession()).toBeTrue();
    expect(notificationService.show).not.toHaveBeenCalled();

    online = true;
    window.dispatchEvent(new Event('online'));
    await flushTimers();

    expect(router.navigateByUrl).toHaveBeenCalledWith('/');
    await flushTimers();
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
  });

  it('does not revive session or write USER_DETAILS when another tab signs out or hand-off lands late', async () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    promptBehavior = 'hang';
    const service = createService();

    const pending = firstValueFrom(service.getValidIdentityPlatformToken$());
    await flushTimers();
    expect(gis.prompt).toHaveBeenCalled();

    // Another tab clears storage right before Google returns a credential (no StorageEvent yet).
    localStorage.removeItem(SESSION_STORAGE_KEY);
    gisCallback?.({credential: nextGisToken});

    await expectAsync(pending).toBeRejected();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(service.hasRenewableSession()).toBeFalse();
    await flushTimers();
    httpMock.expectNone(r => r.url.endsWith('/users/me'));
  });

  it('ignores a /users/me 500 error and skips USER_DETAILS write if signed out in flight', async () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();

    expect(await firstValueFrom(service.getValidIdentityPlatformToken$())).toBe(
      nextGisToken,
    );
    await flushTimers();
    const firstHandOff = httpMock.expectOne(r => r.url.endsWith('/users/me'));
    firstHandOff.flush('boom', {status: 500, statusText: 'Server Error'});
    expect(service.isLoggedIn()).toBeTrue();

    // Start a second hand-off via forced 401 renewal, then logout before /users/me responds.
    const newerToken = makeJwt(Date.now() + 3_700_000, 'newer');
    nextGisToken = newerToken;
    expect(
      await firstValueFrom(
        service.renewAfterUnauthorized$(service.getToken()!),
      ),
    ).toBe(newerToken);
    await flushTimers();
    const lateHandOff = httpMock.expectOne(r => r.url.endsWith('/users/me'));
    await service.logout();
    lateHandOff.flush({email: 'user@example.com'});

    expect(localStorage.getItem('USER_DETAILS')).toBeNull();
    expect(notificationService.show).not.toHaveBeenCalled();
  });

  it('shows 1 session-expired toast and preserves returnUrl when renewal fails while visible and online', async () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();
    spyOnProperty(document, 'visibilityState', 'get').and.returnValue(
      'visible',
    );

    service.onSessionRenewalFailed('/workbench?sessionId=42');
    service.onSessionRenewalFailed('/login?returnUrl=%2Fworkbench');
    await flushTimers();

    expect(notificationService.show).toHaveBeenCalledTimes(1);
    expect(router.navigate).toHaveBeenCalledOnceWith(['/login'], {
      queryParams: {returnUrl: '/workbench?sessionId=42'},
    });
  });

  it('falls back unlocked if waiting for navigator.locks exceeds the timeout', fakeAsync(() => {
    locksSpy.and.returnValue({
      request: (_name: string, opts: LockOptions) =>
        new Promise((_resolve, reject) => {
          opts.signal?.addEventListener('abort', () =>
            reject(new DOMException('Lock aborted', 'AbortError')),
          );
        }),
    } as unknown as LockManager);
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();
    let result: string | undefined;

    service.renewSession$().subscribe({next: t => (result = t)});
    tick(5_000);
    flushMicrotasks();
    tick();

    expect(result).toBe(nextGisToken);
    expect(gis.prompt).toHaveBeenCalledTimes(1);
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
    service.ngOnDestroy();
  }));

  describe('local development (Firebase)', () => {
    beforeEach(() => {
      (environment as {isLocal: boolean}).isLocal = true;
    });

    it('waits for Firebase to restore the user before refreshing, without GIS', async () => {
      const localToken = makeJwt(Date.now() + 3_600_000, 'local');
      const calls: string[] = [];
      const user = {
        getIdToken: jasmine.createSpy('getIdToken').and.callFake(async () => {
          calls.push('getIdToken');
          return localToken;
        }),
      };
      authMock = {
        signOut: jasmine.createSpy('signOut').and.resolveTo(),
        currentUser: null,
        authStateReady: jasmine
          .createSpy('authStateReady')
          .and.callFake(async () => {
            calls.push('authStateReady');
            authMock['currentUser'] = user;
          }),
      };
      writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
      const service = createService();

      expect(
        await firstValueFrom(service.getValidIdentityPlatformToken$()),
      ).toBe(localToken);
      expect(calls).toEqual(['authStateReady', 'getIdToken']);
      expect(gis.prompt).not.toHaveBeenCalled();
      await flushTimers();
      httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
    });

    it('rejects when Firebase has no currentUser after authStateReady()', async () => {
      authMock = {
        signOut: jasmine.createSpy('signOut').and.resolveTo(),
        currentUser: null,
        authStateReady: jasmine.createSpy('authStateReady').and.resolveTo(),
      };
      writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
      const service = createService();

      await expectAsync(
        firstValueFrom(service.getValidIdentityPlatformToken$()),
      ).toBeRejectedWithError(/Firebase session is no longer available/);
    });

    it('rejects a local Firebase token refresh when sub belongs to a different account', async () => {
      const swappedLocal = makeJwt(Date.now() + 3_600_000, 'swapped-local', {
        sub: 'sub-different-local',
      });
      authMock = {
        signOut: jasmine.createSpy('signOut').and.resolveTo(),
        currentUser: {
          getIdToken: jasmine
            .createSpy('getIdToken')
            .and.resolveTo(swappedLocal),
        },
        authStateReady: jasmine.createSpy('authStateReady').and.resolveTo(),
      };
      writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
      const service = createService();

      await expectAsync(
        firstValueFrom(service.getValidIdentityPlatformToken$()),
      ).toBeRejected();
      await flushTimers();
      expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
      expect(notificationService.show).toHaveBeenCalledTimes(1);
      httpMock.expectNone(r => r.url.endsWith('/users/me'));
    });
  });
});
