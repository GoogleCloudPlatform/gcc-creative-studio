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
import {RouterTestingModule} from '@angular/router/testing';
import {Auth} from '@angular/fire/auth';
import {firstValueFrom} from 'rxjs';
import {AuthService} from './auth.service';
import {NotificationService} from './notification.service';
import {UserService} from './user.service';
import {RENEW_RETRY_MS, SESSION_STORAGE_KEY} from './auth-session.store';
import {
  GisInitializeConfig,
  GisPromptMomentNotification,
  GisPromptSuppressedError,
  SessionSupersededError,
  attachFailedSessionToken,
  resolveSessionExpiry,
  sanitizeReturnUrl,
} from './auth-token.utils';
import {GIS_SCRIPT_LOAD_TIMEOUT_MS} from './gis-client';
import {environment} from '../../../environments/environment';

type PromptBehavior =
  | 'credential'
  | 'skip'
  | 'not_displayed'
  | 'dismissed'
  | 'hang';

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
  let router: {
    url: string;
    navigate: jasmine.Spy;
    navigateByUrl: jasmine.Spy;
    getCurrentNavigation?: jasmine.Spy;
  };
  let notificationService: jasmine.SpyObj<NotificationService>;
  let authMock: Record<string, unknown>;
  let gis: {
    initialize: jasmine.Spy;
    prompt: jasmine.Spy;
    renderButton: jasmine.Spy;
    cancel: jasmine.Spy;
    disableAutoSelect: jasmine.Spy;
  };
  let promptBehavior: PromptBehavior;
  let nextGisToken: string;
  let httpMock: HttpTestingController;
  let isLocalBeforeTest: boolean;
  let gisCallback: ((r: {credential?: string}) => void) | null;
  let locksSpy: jasmine.Spy;
  let addedScripts: HTMLScriptElement[];

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

  const attachGisScript = (): HTMLScriptElement => {
    const script = document.createElement('script');
    script.type = 'text/plain';
    script.src = 'https://accounts.google.com/gsi/client';
    document.head.appendChild(script);
    addedScripts.push(script);
    return script;
  };

  beforeEach(() => {
    localStorage.clear();
    addedScripts = [];
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
          } else if (promptBehavior === 'not_displayed') {
            moment?.({isNotDisplayed: () => true});
          } else if (promptBehavior === 'dismissed') {
            moment?.({
              isDismissedMoment: () => true,
              getDismissedReason: () => 'cancel_called',
            });
          }
        }),
      renderButton: jasmine.createSpy('renderButton'),
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
    addedScripts.forEach(script => script.remove());
    addedScripts = [];
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

    expect(router.navigate).toHaveBeenCalledWith(['/login'], {
      queryParams: {returnUrl: '/home'},
    });
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

  it('fails fast when the GIS script tag is missing or dispatches an error event', fakeAsync(() => {
    delete (window as unknown as {google?: unknown}).google;
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();

    let missingErr: Error | undefined;
    service
      .getValidIdentityPlatformToken$()
      .subscribe({error: e => (missingErr = e)});
    flushMicrotasks();
    expect(missingErr?.message).toContain('not loaded');

    const script = attachGisScript();
    let scriptErr: Error | undefined;
    service.renewSession$().subscribe({error: e => (scriptErr = e)});
    flushMicrotasks();
    script.dispatchEvent(new Event('error'));
    flushMicrotasks();
    expect(scriptErr?.message).toContain('not loaded');
    service.ngOnDestroy();
  }));

  it('waits for cold GIS script load when google attaches at 200ms', fakeAsync(() => {
    delete (window as unknown as {google?: unknown}).google;
    attachGisScript();
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();

    let loadedToken: string | undefined;
    let loadErr: unknown;
    service.getValidIdentityPlatformToken$().subscribe({
      next: t => (loadedToken = t),
      error: e => (loadErr = e),
    });
    flushMicrotasks();
    expect(loadErr).toBeUndefined();
    expect(gis.initialize).not.toHaveBeenCalled();

    tick(150);
    expect(loadErr).toBeUndefined();
    expect(loadedToken).toBeUndefined();
    (window as unknown as {google: unknown}).google = {accounts: {id: gis}};
    tick(50);
    flushMicrotasks();
    expect(loadErr).toBeUndefined();
    expect(loadedToken).toBe(nextGisToken);
    tick(0);
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
    service.ngOnDestroy();
  }));

  it('aborts cold GIS script load cleanly if logout runs mid-load without initializing GIS', fakeAsync(() => {
    delete (window as unknown as {google?: unknown}).google;
    attachGisScript();
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();

    let abortedErr: Error | undefined;
    service.renewSession$().subscribe({error: e => (abortedErr = e)});
    flushMicrotasks();
    tick(50);
    void service.logout();
    flushMicrotasks();
    expect(abortedErr?.message).toContain('cancelled');
    expect(gis.initialize).not.toHaveBeenCalled();
    tick(GIS_SCRIPT_LOAD_TIMEOUT_MS);
    service.ngOnDestroy();
  }));

  it('preserves expiry + 1s backup timer across cooldown and focus when buffer prompt is skipped', fakeAsync(() => {
    const bufferRemainingMs = 3 * 60_000;
    const current = makeJwt(Date.now() + bufferRemainingMs, 'in-buffer');
    writeSession(current, Date.now() + bufferRemainingMs);
    promptBehavior = 'skip';
    const service = createService();

    let emitted: string | undefined;
    service.getValidIdentityPlatformToken$().subscribe(t => (emitted = t));
    flushMicrotasks();
    expect(emitted).toBe(current);
    expect(gis.prompt).toHaveBeenCalledTimes(1);

    // Focus and API calls inside 60s cooldown must NOT overwrite expiry+1s timer.
    tick(10_000);
    window.dispatchEvent(new Event('focus'));
    service.getValidIdentityPlatformToken$().subscribe();
    flushMicrotasks();
    expect(gis.prompt).toHaveBeenCalledTimes(1);

    // After 60s cooldown (still inside buffer), focus still keeps expiry+1s timer.
    tick(RENEW_RETRY_MS);
    window.dispatchEvent(new Event('focus'));
    flushMicrotasks();
    expect(gis.prompt).toHaveBeenCalledTimes(1);

    // Advance right up to expiry + 999ms: timer has not fired yet.
    const remainingToExpiry = bufferRemainingMs - 10_000 - RENEW_RETRY_MS;
    tick(remainingToExpiry + 999);
    flushMicrotasks();
    expect(gis.prompt).toHaveBeenCalledTimes(1);

    // At expiry + 1s, backup timer fires and renews cleanly (or expires if still skipped).
    promptBehavior = 'credential';
    nextGisToken = makeJwt(Date.now() + 3_600_000, 'recovered');
    tick(1);
    flushMicrotasks();
    expect(gis.prompt).toHaveBeenCalledTimes(2);
    expect(service.getToken()).toBe(nextGisToken);
    tick(0);
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
    service.ngOnDestroy();
  }));

  it('aborts a hung silent prompt on logout or interactive sign-in without leaking timers or blocking the new session', fakeAsync(() => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    promptBehavior = 'hang';
    const service = createService();

    let silentErr: Error | undefined;
    service.renewSession$().subscribe({error: e => (silentErr = e)});
    flushMicrotasks();
    expect(gis.prompt).toHaveBeenCalledTimes(1);

    // Logout aborts immediately without waiting 10s.
    void service.logout();
    flushMicrotasks();
    expect(silentErr?.message).toContain('cancelled');
    expect(gis.cancel).toHaveBeenCalledTimes(1);
    tick(15_000);
    expect(gis.cancel).toHaveBeenCalledTimes(1);

    // Hung silent prompt superseded by interactive sign-in: stale timer never fires cancel() on new session.
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    service.isLoggedIn();
    let silentErr2: Error | undefined;
    service.renewSession$().subscribe({error: e => (silentErr2 = e)});
    flushMicrotasks();
    expect(gis.prompt).toHaveBeenCalledTimes(2);

    gis.cancel.calls.reset();
    promptBehavior = 'credential';
    const freshInteractive = makeJwt(Date.now() + 3_600_000, 'interactive');
    nextGisToken = freshInteractive;
    let signedInToken: string | undefined;
    service
      .signInForGoogleIdentityPlatform()
      .subscribe(t => (signedInToken = t));
    flushMicrotasks();
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
    expect(silentErr2?.message).toContain('cancelled');
    expect(gis.cancel).toHaveBeenCalledTimes(1);
    expect(signedInToken).toBe(freshInteractive);

    tick(15_000);
    expect(gis.cancel).toHaveBeenCalledTimes(1);
    expect(service.isLoggedIn()).toBeTrue();
    service.ngOnDestroy();
  }));

  it('drops post-logout handoff macrotask and isolates cross-tab account switches', fakeAsync(() => {
    // 1. Post-logout setTimeout guard drops /users/me handoff.
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();
    let renewed: string | undefined;
    service.getValidIdentityPlatformToken$().subscribe(t => (renewed = t));
    flushMicrotasks();
    expect(renewed).toBe(nextGisToken);
    void service.logout();
    flushMicrotasks();
    tick(0);
    httpMock.expectNone(r => r.url.endsWith('/users/me'));

    // 2. Cross-tab account switch blocks stale Account A token readers, handles timeout/error purge, and reloads.
    const reloadSpy = spyOn(
      service as unknown as {reloadToHome: () => void},
      'reloadToHome',
    );
    const tokenA = makeJwt(Date.now() + 50 * 60_000, 'a', {
      sub: 'sub-a',
      email: 'a@example.com',
    });
    const tokenB = makeJwt(Date.now() + 20 * 60_000, 'b', {
      sub: 'sub-b',
      email: 'b@example.com',
    });
    writeSession(tokenA, Date.now() + 50 * 60_000);
    service.isLoggedIn();
    localStorage.setItem(
      'USER_DETAILS',
      JSON.stringify({email: 'a@example.com', roles: ['ADMIN']}),
    );

    const expiryB = Date.now() + 20 * 60_000;
    writeSession(tokenB, expiryB);
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: SESSION_STORAGE_KEY,
        newValue: JSON.stringify({
          token: tokenB,
          expiry: expiryB,
        }),
      }),
    );

    // During switchingAccount window: getValidIdentityPlatformToken$ emits empty, renewAfterUnauthorized$ rejects.
    let duringSwitchVal = 'unset';
    service
      .getValidIdentityPlatformToken$()
      .subscribe({next: v => (duringSwitchVal = v)});
    expect(duringSwitchVal).toBe('unset');

    let unauthorizedSwitchErr: Error | undefined;
    service
      .renewAfterUnauthorized$(tokenA)
      .subscribe({error: e => (unauthorizedSwitchErr = e)});
    expect(unauthorizedSwitchErr?.message).toContain('switch in progress');

    // Hit 1500ms timeout cap on /users/me -> stale Account A USER_DETAILS purged and reloadToHome called.
    const switchReq = httpMock.expectOne(r => r.url.endsWith('/users/me'));
    expect(switchReq.request.headers.get('Authorization')).toBe(
      `Bearer ${tokenB}`,
    );
    tick(1500);
    expect(localStorage.getItem('USER_DETAILS')).toBeNull();
    expect(reloadSpy).toHaveBeenCalledTimes(1);

    // After reloadToHome/reset, Account A's rejectedToken cannot renew Account B's session.
    let mismatchErr: Error | undefined;
    service
      .renewAfterUnauthorized$(tokenA)
      .subscribe({error: e => (mismatchErr = e)});
    expect(mismatchErr?.message).toContain('different account');

    // Successful /users/me on switch updates USER_DETAILS and reloads.
    const tokenC = makeJwt(Date.now() + 20 * 60_000, 'c', {
      sub: 'sub-c',
      email: 'c@example.com',
    });
    const expiryC = Date.now() + 20 * 60_000;
    writeSession(tokenC, expiryC);
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: SESSION_STORAGE_KEY,
        newValue: JSON.stringify({
          token: tokenC,
          expiry: expiryC,
        }),
      }),
    );
    const reqC = httpMock.expectOne(r => r.url.endsWith('/users/me'));
    reqC.flush({email: 'c@example.com', roles: ['USER']});
    expect(JSON.parse(localStorage.getItem('USER_DETAILS')!).email).toBe(
      'c@example.com',
    );
    expect(reloadSpy).toHaveBeenCalledTimes(2);
    service.ngOnDestroy();
  }));

  it('resolves cold deep links, redirects synchronously before signOut, and never clobbers /login returnUrl', async () => {
    // 1. Mock router at '/' with getCurrentNavigation returning deep link + unresolved signOut promise.
    let resolveSignOut!: () => void;
    authMock['signOut'] = jasmine.createSpy('signOut').and.returnValue(
      new Promise<void>(resolve => {
        resolveSignOut = resolve;
      }),
    );
    router.url = '/';
    router.getCurrentNavigation = jasmine
      .createSpy('getCurrentNavigation')
      .and.returnValue({
        finalUrl: {toString: () => '/gallery?test=1'},
      });
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();

    service.onSessionRenewalFailed();
    // Synchronous redirect BEFORE signOut resolves:
    expect(router.navigate).toHaveBeenCalledOnceWith(['/login'], {
      queryParams: {returnUrl: '/gallery?test=1'},
    });
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    resolveSignOut();
    await flushTimers();

    // 2. navigateToLoginIfNeeded preserves /login?returnUrl=... on cold boot.
    router.navigate.calls.reset();
    router.url = '/login?returnUrl=%2Fgallery%3Ftest%3D1';
    router.getCurrentNavigation.and.returnValue(null);
    await firstValueFrom(service.getValidIdentityPlatformToken$(), {
      defaultValue: null,
    });
    expect(router.navigate).not.toHaveBeenCalled();

    // 3. Real Router instance falls back to browser location when router.url === '/' and skips /login.
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule, RouterTestingModule.withRoutes([])],
      providers: [
        AuthService,
        {provide: NotificationService, useValue: notificationService},
        {provide: UserService, useValue: {getUserDetails: () => null}},
        {provide: Auth, useValue: {signOut: () => Promise.resolve()}},
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    const realRouter = TestBed.inject(Router);
    const navSpy = spyOn(realRouter, 'navigate').and.resolveTo(true);
    const realService = TestBed.inject(AuthService);

    const originalHref =
      window.location.pathname + window.location.search + window.location.hash;
    try {
      window.history.replaceState(null, '', '/gallery?test=1');
      writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
      realService.isLoggedIn();
      realService.onSessionRenewalFailed();
      expect(navSpy).toHaveBeenCalledOnceWith(['/login'], {
        queryParams: {returnUrl: '/gallery?test=1'},
      });

      navSpy.calls.reset();
      window.history.replaceState(null, '', '/login?returnUrl=%2Fgallery');
      await firstValueFrom(realService.getValidIdentityPlatformToken$(), {
        defaultValue: null,
      });
      expect(navSpy).not.toHaveBeenCalled();
    } finally {
      window.history.replaceState(null, '', originalHref);
      realService.ngOnDestroy();
    }
  });

  it('fails interactive GIS sign-in immediately with GisPromptSuppressedError, renders fallback buttons, and rolls back 403 /users/me', async () => {
    const service = createService();

    // 1. isNotDisplayed and isSkippedMoment fail immediately with GisPromptSuppressedError.
    promptBehavior = 'not_displayed';
    await expectAsync(
      firstValueFrom(service.signInForGoogleIdentityPlatform()),
    ).toBeRejectedWithError(GisPromptSuppressedError);

    promptBehavior = 'skip';
    await expectAsync(
      firstValueFrom(service.signInForGoogleIdentityPlatform()),
    ).toBeRejectedWithError(GisPromptSuppressedError);
    expect(gis.cancel).toHaveBeenCalledTimes(2);

    // 2. renderGoogleSignInButton$ initializes once, renders all containers, invokes onCredentialStart, and rolls back on 403.
    const el1 = document.createElement('div');
    const el2 = document.createElement('div');
    const onStart = jasmine.createSpy('onStart');
    const token403 = makeJwt(Date.now() + 3_600_000, 'unauth');

    let btnErr: unknown;
    const sub = service
      .renderGoogleSignInButton$([el1, el2], onStart)
      .subscribe({error: e => (btnErr = e)});

    expect(gis.initialize).toHaveBeenCalledTimes(3);
    const btnInitCfg = gis.initialize.calls.mostRecent().args[0];
    expect(btnInitCfg.use_fedcm_for_button).toBeTrue();
    expect(btnInitCfg.auto_select).toBeFalse();
    expect(gis.renderButton).toHaveBeenCalledTimes(2);
    expect(gis.renderButton.calls.argsFor(0)[0]).toBe(el1);
    expect(gis.renderButton.calls.argsFor(1)[0]).toBe(el2);

    gisCallback?.({credential: token403});
    expect(onStart).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).not.toBeNull();

    httpMock
      .expectOne(r => r.url.endsWith('/users/me'))
      .flush({detail: 'Forbidden'}, {status: 403, statusText: 'Forbidden'});

    expect(btnErr).toBeDefined();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(service.hasRenewableSession()).toBeFalse();
    sub.unsubscribe();

    // 3. signInForGoogleIdentityPlatform also rolls back firebase_session on 403 /users/me.
    promptBehavior = 'credential';
    nextGisToken = token403;
    let interactiveErr: unknown;
    service
      .signInForGoogleIdentityPlatform()
      .subscribe({error: e => (interactiveErr = e)});
    httpMock
      .expectOne(r => r.url.endsWith('/users/me'))
      .flush({detail: 'Forbidden'}, {status: 403, statusText: 'Forbidden'});
    expect(interactiveErr).toBeDefined();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('guards onSessionRenewalFailed against superseded errors, stale-account tokens, and already-renewed valid sessions', () => {
    const tokenA = makeJwt(Date.now() - 60_000, 'old-a', {
      sub: 'sub-a',
      email: 'a@example.com',
    });
    const tokenAValid = makeJwt(Date.now() + 3_600_000, 'new-a', {
      sub: 'sub-a',
      email: 'a@example.com',
    });
    const tokenB = makeJwt(Date.now() + 3_600_000, 'acct-b', {
      sub: 'sub-b',
      email: 'b@example.com',
    });
    const expiryValid = Date.now() + 3_600_000;

    writeSession(tokenB, expiryValid);
    const service = createService();
    const reloadSpy = spyOn(
      service as unknown as {reloadToHome: () => void},
      'reloadToHome',
    );

    // 1. SessionSupersededError is ignored immediately.
    service.onSessionRenewalFailed(
      '/gallery',
      new SessionSupersededError('superseded', tokenA),
    );
    expect(service.isLoggedIn()).toBeTrue();
    expect(service.getToken()).toBe(tokenB);
    expect(notificationService.show).not.toHaveBeenCalled();

    // 2. Plain error tagged with Account A token must not wipe Account B session.
    service.onSessionRenewalFailed(
      '/gallery',
      attachFailedSessionToken(new Error('late 401'), tokenA),
    );
    expect(service.isLoggedIn()).toBeTrue();
    expect(service.getToken()).toBe(tokenB);
    expect(notificationService.show).not.toHaveBeenCalled();

    // 3. Same-account stale token must not wipe a valid newly renewed session.
    writeSession(tokenAValid, expiryValid);
    service.isLoggedIn();
    httpMock.expectOne(r => r.url.endsWith('/users/me')).flush({});
    expect(reloadSpy).toHaveBeenCalledTimes(1);

    service.onSessionRenewalFailed(
      '/gallery',
      attachFailedSessionToken(new Error('stale 401'), tokenA),
    );
    expect(service.isLoggedIn()).toBeTrue();
    expect(service.getToken()).toBe(tokenAValid);
    expect(notificationService.show).not.toHaveBeenCalled();
  });
});
