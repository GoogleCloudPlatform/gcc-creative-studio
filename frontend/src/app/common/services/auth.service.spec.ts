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
import {firstValueFrom} from 'rxjs';
import {AuthService} from './auth.service';
import {UserService} from './user.service';
import {SESSION_STORAGE_KEY} from './auth-session.store';
import {environment} from '../../../environments/environment';

type PromptBehavior = 'credential' | 'skip' | 'hang';

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
  return `${enc({alg: 'RS256'})}.${enc({exp: Math.floor(expMs / 1000), tag, ...extra})}.sig`;
}

const writeSession = (token: string, expiry: number) =>
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({token, expiry}));

const flushTimers = () => new Promise(resolve => setTimeout(resolve, 0));

describe('AuthService', () => {
  let router: {url: string; navigate: jasmine.Spy; navigateByUrl: jasmine.Spy};
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
  let gisCallback: ((r: {credential: string}) => void) | null;

  const createService = () => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        AuthService,
        {provide: Router, useValue: router},
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
    authMock = {signOut: jasmine.createSpy('signOut').and.resolveTo()};
    promptBehavior = 'credential';
    nextGisToken = makeJwt(Date.now() + 3_600_000, 'renewed');

    gisCallback = null;
    gis = {
      initialize: jasmine.createSpy('initialize').and.callFake(cfg => {
        gisCallback = cfg.callback;
      }),
      prompt: jasmine.createSpy('prompt').and.callFake(moment => {
        if (promptBehavior === 'credential') {
          gisCallback?.({credential: nextGisToken});
        } else if (promptBehavior === 'skip') {
          moment?.({isSkippedMoment: () => true});
        }
      }),
      cancel: jasmine.createSpy('cancel'),
      disableAutoSelect: jasmine.createSpy('disableAutoSelect'),
    };
    (window as unknown as {google: unknown}).google = {accounts: {id: gis}};

    // Run cross-tab locked sections immediately in tests.
    spyOnProperty(
      Object.getPrototypeOf(navigator),
      'locks',
      'get',
    ).and.returnValue({
      request: (_name: string, cb: () => unknown) => Promise.resolve().then(cb),
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

  it('throws for invalid JWT structure', () => {
    const service = createService();
    expect(() =>
      service.decodeJwtPayload('invalid_token_without_dots'),
    ).toThrow(new Error('Invalid JWT token'));
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

  it('renews silently inside the window and hands the new token to the server', async () => {
    writeSession(
      makeJwt(Date.now() + 2 * 60_000, 'init', {
        email: 'admin@belvederej.altostrat.com',
        hd: 'belvederej.altostrat.com',
      }),
      Date.now() + 2 * 60_000,
    );
    const service = createService();

    const token = await firstValueFrom(
      service.getValidIdentityPlatformToken$(),
    );

    expect(token).toBe(nextGisToken);
    const initCfg = gis.initialize.calls.mostRecent().args[0];
    expect(initCfg.auto_select).toBeTrue();
    expect(initCfg.login_hint).toBe('admin@belvederej.altostrat.com');
    expect(initCfg.hd).toBe('belvederej.altostrat.com');
    expect(JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY)!).token).toBe(
      nextGisToken,
    );
    await flushTimers();
    const handOff = httpMock.expectOne(r => r.url.endsWith('/users/me'));
    expect(handOff.request.headers.get('Authorization')).toBe(
      `Bearer ${nextGisToken}`,
    );
    handOff.flush({email: 'a@example.com'});
  });

  it('shares one renewal between concurrent callers', async () => {
    writeSession(makeJwt(Date.now() + 60_000), Date.now() + 60_000);
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

  it('keeps the still-valid token and cancels the prompt when renewal fails', async () => {
    const current = makeJwt(Date.now() + 2 * 60_000);
    writeSession(current, Date.now() + 2 * 60_000);
    promptBehavior = 'skip';
    const service = createService();

    expect(await firstValueFrom(service.getValidIdentityPlatformToken$())).toBe(
      current,
    );
    expect(gis.cancel).toHaveBeenCalled();
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

  it('errors when an expired session cannot be renewed', async () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    promptBehavior = 'skip';
    const service = createService();

    await expectAsync(
      firstValueFrom(service.getValidIdentityPlatformToken$()),
    ).toBeRejected();
  });

  it('reuses a session another tab already renewed instead of prompting', async () => {
    writeSession(makeJwt(Date.now() + 60_000), Date.now() + 60_000);
    const service = createService();
    const fresh = makeJwt(Date.now() + 3_600_000, 'other-tab');
    writeSession(fresh, Date.now() + 3_600_000);

    expect(await firstValueFrom(service.renewSession$())).toBe(fresh);
    expect(gis.prompt).not.toHaveBeenCalled();
    await flushTimers(); // No hand-off: the other tab already did it.
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

  it('keeps the session when renewal fails in a hidden tab', () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();
    spyOnProperty(document, 'visibilityState', 'get').and.returnValue('hidden');
    spyOn(service, 'expireSession');

    service.onSessionRenewalFailed();

    expect(service.expireSession).not.toHaveBeenCalled();
    expect(service.hasRenewableSession()).toBeTrue();
  });

  it('keeps the session when renewal fails while offline', () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();
    spyOnProperty(document, 'visibilityState', 'get').and.returnValue(
      'visible',
    );
    spyOnProperty(navigator, 'onLine', 'get').and.returnValue(false);
    spyOn(service, 'expireSession');

    service.onSessionRenewalFailed();

    expect(service.expireSession).not.toHaveBeenCalled();
    expect(service.hasRenewableSession()).toBeTrue();
  });

  it('does not bring the session back when signing out during a renewal', async () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    promptBehavior = 'hang';
    const service = createService();

    const pending = firstValueFrom(service.getValidIdentityPlatformToken$());
    await flushTimers(); // Let the renewal reach the Google prompt.
    expect(gis.prompt).toHaveBeenCalled();

    await service.logout();
    expect(gis.cancel).toHaveBeenCalled();
    gisCallback?.({credential: nextGisToken}); // Google answers late.

    await expectAsync(pending).toBeRejected();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(service.hasRenewableSession()).toBeFalse();
    await flushTimers(); // No hand-off request may follow.
  });

  it('expires the session when renewal fails in a visible, online tab', () => {
    writeSession(makeJwt(Date.now() - 60_000), Date.now() - 60_000);
    const service = createService();
    spyOnProperty(document, 'visibilityState', 'get').and.returnValue(
      'visible',
    );
    spyOn(service, 'expireSession').and.resolveTo();

    service.onSessionRenewalFailed();

    expect(service.expireSession).toHaveBeenCalled();
  });

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
  });
});
