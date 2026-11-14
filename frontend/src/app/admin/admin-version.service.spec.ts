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

import {PLATFORM_ID} from '@angular/core';
import {HttpClient, provideHttpClient} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {TestBed, fakeAsync, tick} from '@angular/core/testing';
import {Event, NavigationEnd, NavigationStart, Router} from '@angular/router';
import {EMPTY, Subject} from 'rxjs';
import {environment} from '../../environments/environment';
import {AuthService} from '../common/services/auth.service';
import {
  decodeJwtIdentity,
  hasSessionAccountMismatch,
  isLoginRouteUrl,
  readBrowserSessionOwner,
} from './admin-version-session.utils';
import {AdminVersionInfo, AdminVersionService} from './admin-version.service';

interface MockAuthService {
  isUserAdmin: jasmine.Spy<() => boolean>;
  isUserLoggedIn: jasmine.Spy<() => boolean>;
  hasRenewableSession: jasmine.Spy<() => boolean>;
}

function makeJwt(payload: Record<string, unknown>): string {
  const encoded = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `eyJhbGciOiJSUzI1NiJ9.${encoded}.sig`;
}

function setStoredSession(email: string, sub = 'sub-1'): void {
  localStorage.setItem(
    'firebase_session',
    JSON.stringify({
      token: makeJwt({sub, email}),
      expiry: Date.now() + 3_600_000,
    }),
  );
  localStorage.setItem('USER_DETAILS', JSON.stringify({email}));
}

describe('AdminVersionService', () => {
  let httpMock: HttpTestingController;
  let authSpy: MockAuthService;
  let routerEvents$: Subject<Event>;

  const mockInfo: AdminVersionInfo = {
    currentVersion: '26.11.12',
    latestVersion: '26.11.12',
    status: 'up_to_date',
    releaseUrl:
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12',
    releaseName: 'v26.11.12',
    publishedAt: '2026-11-12T20:00:00Z',
    checkedAt: '2026-11-12T20:05:00Z',
  };

  function setup(
    platformId: Object,
    isAdmin: boolean,
    isLoggedIn = true,
    hasRenewable = false,
  ): AdminVersionService {
    routerEvents$ = new Subject<Event>();
    authSpy = {
      isUserAdmin: jasmine.createSpy('isUserAdmin').and.returnValue(isAdmin),
      isUserLoggedIn: jasmine
        .createSpy('isUserLoggedIn')
        .and.returnValue(isLoggedIn),
      hasRenewableSession: jasmine
        .createSpy('hasRenewableSession')
        .and.returnValue(hasRenewable),
    };

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {provide: AuthService, useValue: authSpy},
        {provide: PLATFORM_ID, useValue: platformId},
        {provide: Router, useValue: {events: routerEvents$.asObservable()}},
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    return TestBed.inject(AdminVersionService);
  }

  beforeEach(() => {
    localStorage.removeItem('firebase_session');
    localStorage.removeItem('USER_DETAILS');
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.removeItem('firebase_session');
    localStorage.removeItem('USER_DETAILS');
  });

  it('loads version info once via ensureLoaded() for browser admins', () => {
    const service = setup('browser', true);

    service.ensureLoaded();
    service.ensureLoaded();

    const req = httpMock.expectOne(`${environment.backendURL}/admin/version`);
    expect(req.request.method).toBe('GET');
    req.flush(mockInfo);

    expect(service.versionInfo()).toEqual(mockInfo);
    expect(service.loading()).toBeFalse();
    expect(service.isUpdateAvailable()).toBeFalse();
    expect(service.safeReleaseUrl()).toBe(mockInfo.releaseUrl);
  });

  it('supports backwards-compatible 3-argument construction', () => {
    setup('browser', true);
    const standalone = new AdminVersionService(
      TestBed.inject(HttpClient),
      authSpy as unknown as AuthService,
      'browser',
    );
    standalone.ensureLoaded();
    httpMock
      .expectOne(`${environment.backendURL}/admin/version`)
      .flush(mockInfo);
    expect(standalone.versionInfo()).toEqual(mockInfo);
    standalone.ngOnDestroy();
  });

  it('sends refresh=true, sets justChecked for 1.5s, and enforces 5s cooldown', fakeAsync(() => {
    const service = setup('browser', true);

    service.refresh();
    service.refresh();

    const req = httpMock.expectOne(
      r =>
        r.url === `${environment.backendURL}/admin/version` &&
        r.params.get('refresh') === 'true',
    );
    req.flush({
      ...mockInfo,
      latestVersion: '26.11.15',
      status: 'update_available',
    });

    expect(service.isUpdateAvailable()).toBeTrue();
    expect(service.justChecked()).toBeTrue();
    expect(service.cooldownActive()).toBeTrue();

    tick(1500);
    expect(service.justChecked()).toBeFalse();
    expect(service.cooldownActive()).toBeTrue();

    service.refresh();
    httpMock.expectNone(`${environment.backendURL}/admin/version`);

    tick(3500);
    expect(service.cooldownActive()).toBeFalse();
  }));

  it('preserves last-known state and sets refreshFailed on failed refresh(), then clears on next success', fakeAsync(() => {
    const service = setup('browser', true);
    const warnSpy = spyOn(console, 'warn');

    service.ensureLoaded();
    const initReq = httpMock.expectOne(
      `${environment.backendURL}/admin/version`,
    );
    const updateInfo: AdminVersionInfo = {
      ...mockInfo,
      latestVersion: '26.11.15',
      status: 'update_available',
      releaseUrl:
        'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.15',
    };
    initReq.flush(updateInfo);

    service.refresh();
    const failReq = httpMock.expectOne(
      r =>
        r.url === `${environment.backendURL}/admin/version` &&
        r.params.get('refresh') === 'true',
    );
    failReq.flush('Bad gateway', {status: 502, statusText: 'Bad Gateway'});

    expect(warnSpy).toHaveBeenCalled();
    expect(service.versionInfo()).toEqual(updateInfo);
    expect(service.isUpdateAvailable()).toBeTrue();
    expect(service.safeReleaseUrl()).toBe(updateInfo.releaseUrl);
    expect(service.loadFailed()).toBeFalse();
    expect(service.refreshFailed()).toBeTrue();
    expect(service.justChecked()).toBeFalse();

    tick(5000);
    service.refresh();
    const okReq = httpMock.expectOne(
      r =>
        r.url === `${environment.backendURL}/admin/version` &&
        r.params.get('refresh') === 'true',
    );
    okReq.flush(mockInfo);

    expect(service.refreshFailed()).toBeFalse();
    expect(service.versionInfo()).toEqual(mockInfo);
    expect(service.isUpdateAvailable()).toBeFalse();
    expect(service.justChecked()).toBeTrue();
    tick(1500);
    expect(service.justChecked()).toBeFalse();
    tick(3500);
    expect(service.cooldownActive()).toBeFalse();
  }));

  it('handles cold-start EMPTY completion from AuthInterceptor and retries after 60s backoff', fakeAsync(() => {
    const warnSpy = spyOn(console, 'warn');
    let nowMs = 1_000_000;
    spyOn(Date, 'now').and.callFake(() => nowMs);

    const service = setup('browser', true);
    const http = TestBed.inject(HttpClient);
    const getSpy = spyOn(http, 'get').and.returnValue(EMPTY);

    service.ensureLoaded();
    expect(getSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalled();
    expect(service.loading()).toBeFalse();
    expect(service.loadFailed()).toBeTrue();
    expect(service.versionInfo()).toBeNull();

    nowMs += 30_000;
    service.ensureLoaded();
    expect(getSpy).toHaveBeenCalledTimes(1);

    getSpy.and.callThrough();
    nowMs += 30_000;
    service.ensureLoaded();
    const retryReq = httpMock.expectOne(
      `${environment.backendURL}/admin/version`,
    );
    retryReq.flush(mockInfo);

    expect(service.loadFailed()).toBeFalse();
    expect(service.versionInfo()).toEqual(mockInfo);
  }));

  it('cancels in-flight refresh and resets timers on login route navigation, ignoring post-destroy events', fakeAsync(() => {
    setStoredSession('admin-a@google.com', 'sub-a');
    const service = setup('browser', true);

    const loginUrls = [
      '/login',
      '/login?returnUrl=%2Fadmin%2Fdashboard',
      '/%6cogin',
    ];
    for (const loginUrl of loginUrls) {
      service.refresh();
      const inFlight = httpMock.expectOne(
        r =>
          r.url === `${environment.backendURL}/admin/version` &&
          r.params.get('refresh') === 'true',
      );
      expect(service.loading()).toBeTrue();
      expect(service.cooldownActive()).toBeTrue();

      routerEvents$.next(
        loginUrl.includes('returnUrl')
          ? new NavigationEnd(1, '/admin/dashboard', loginUrl)
          : new NavigationStart(1, loginUrl),
      );

      expect(inFlight.cancelled).toBeTrue();
      expect(service.loading()).toBeFalse();
      expect(service.cooldownActive()).toBeFalse();
      expect(service.versionInfo()).toBeNull();
    }

    // Navigating within the app as the same admin keeps loaded versionInfo.
    service.ensureLoaded();
    httpMock
      .expectOne(`${environment.backendURL}/admin/version`)
      .flush(mockInfo);
    routerEvents$.next(new NavigationEnd(2, '/admin/users', '/admin/users'));
    expect(service.versionInfo()).toEqual(mockInfo);

    // After ngOnDestroy(), router events must no longer trigger reset().
    service.ngOnDestroy();
    routerEvents$.next(new NavigationStart(3, '/login'));
    expect(service.versionInfo()).toEqual(mockInfo);
    tick(5000);
  }));

  it('resets on cross-tab StorageEvent sign-out/clear/mismatch, while preserving same-user renewal', fakeAsync(() => {
    setStoredSession('admin-a@google.com', 'sub-a');
    const service = setup('browser', true);

    // Cross-tab firebase_session removal cancels in-flight refresh.
    service.refresh();
    const req1 = httpMock.expectOne(
      r =>
        r.url === `${environment.backendURL}/admin/version` &&
        r.params.get('refresh') === 'true',
    );
    localStorage.removeItem('firebase_session');
    window.dispatchEvent(
      new StorageEvent('storage', {key: 'firebase_session', newValue: null}),
    );
    expect(req1.cancelled).toBeTrue();
    expect(service.loading()).toBeFalse();
    expect(service.cooldownActive()).toBeFalse();
    expect(service.versionInfo()).toBeNull();

    // Same-user JWT renewal preserves versionInfo.
    setStoredSession('admin-a@google.com', 'sub-a');
    service.ensureLoaded();
    httpMock
      .expectOne(`${environment.backendURL}/admin/version`)
      .flush(mockInfo);
    const renewedSession = JSON.stringify({
      token: makeJwt({sub: 'sub-a', email: 'admin-a@google.com', iat: 200}),
      expiry: Date.now() + 3_600_000,
    });
    localStorage.setItem('firebase_session', renewedSession);
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'firebase_session',
        newValue: renewedSession,
      }),
    );
    expect(service.versionInfo()).toEqual(mockInfo);

    // Cross-tab account switch (firebase_session -> admin-b while USER_DETAILS is admin-a)
    // triggers mismatch: isBrowserAdmin() becomes false and state resets.
    const switchedSession = JSON.stringify({
      token: makeJwt({sub: 'sub-b', email: 'admin-b@google.com'}),
      expiry: Date.now() + 3_600_000,
    });
    localStorage.setItem('firebase_session', switchedSession);
    expect(service.isBrowserAdmin()).toBeFalse();
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'firebase_session',
        newValue: switchedSession,
      }),
    );
    expect(service.versionInfo()).toBeNull();

    // Reload for admin-b, then localStorage.clear() (key: null) resets state.
    setStoredSession('admin-b@google.com', 'sub-b');
    expect(service.isBrowserAdmin()).toBeTrue();
    service.ensureLoaded();
    httpMock
      .expectOne(`${environment.backendURL}/admin/version`)
      .flush(mockInfo);
    localStorage.clear();
    window.dispatchEvent(new StorageEvent('storage', {key: null}));
    expect(service.versionInfo()).toBeNull();

    // Post-destroy storage events must be ignored.
    setStoredSession('admin-b@google.com', 'sub-b');
    service.ensureLoaded();
    httpMock
      .expectOne(`${environment.backendURL}/admin/version`)
      .flush(mockInfo);
    service.ngOnDestroy();
    localStorage.removeItem('firebase_session');
    window.dispatchEvent(
      new StorageEvent('storage', {key: 'firebase_session', newValue: null}),
    );
    expect(service.versionInfo()).toEqual(mockInfo);
    tick(5000);
  }));

  it('resets cached versionInfo and clears 60s loadFailed backoff on same-tab user switch', fakeAsync(() => {
    spyOn(console, 'warn');
    setStoredSession('admin-a@google.com', 'sub-a');
    const service = setup('browser', true);

    service.ensureLoaded();
    httpMock
      .expectOne(`${environment.backendURL}/admin/version`)
      .flush(mockInfo);
    expect(service.versionInfo()).toEqual(mockInfo);

    // Same-tab switch to admin-b resets cached info and triggers load for admin-b.
    setStoredSession('admin-b@google.com', 'sub-b');
    service.ensureLoaded();
    const failReq = httpMock.expectOne(
      `${environment.backendURL}/admin/version`,
    );
    failReq.flush('Server error', {status: 500, statusText: 'Internal Error'});
    expect(service.versionInfo()).toBeNull();
    expect(service.loadFailed()).toBeTrue();

    // Still within 60s backoff for admin-b -> no request.
    service.ensureLoaded();
    httpMock.expectNone(`${environment.backendURL}/admin/version`);

    // Same-tab switch to admin-c clears prior backoff immediately.
    setStoredSession('admin-c@example.com', 'sub-c');
    service.ensureLoaded();
    httpMock
      .expectOne(`${environment.backendURL}/admin/version`)
      .flush(mockInfo);
    expect(service.loadFailed()).toBeFalse();
    expect(service.versionInfo()).toEqual(mockInfo);
  }));

  it('keeps isBrowserAdmin() true during wake-from-sleep renewable state and resets cleanly on synchronous clear before HTTP failure', fakeAsync(() => {
    setStoredSession('admin-a@google.com', 'sub-a');
    const service = setup('browser', true, false, true);

    expect(service.isBrowserAdmin()).toBeTrue();
    service.ensureLoaded();
    httpMock
      .expectOne(`${environment.backendURL}/admin/version`)
      .flush(mockInfo);
    expect(service.versionInfo()).toEqual(mockInfo);

    service.refresh();
    const refreshOk = httpMock.expectOne(
      r =>
        r.url === `${environment.backendURL}/admin/version` &&
        r.params.get('refresh') === 'true',
    );
    const updatedInfo: AdminVersionInfo = {
      ...mockInfo,
      latestVersion: '26.11.15',
      status: 'update_available',
    };
    refreshOk.flush(updatedInfo);
    expect(service.versionInfo()).toEqual(updatedInfo);

    // Advance past 5s cooldown, start refresh, then clear session synchronously
    // before HTTP 502/401 arrives: service must reset without refreshFailed=true.
    tick(5000);
    for (const status of [502, 401]) {
      setStoredSession('admin-a@google.com', 'sub-a');
      authSpy.isUserLoggedIn.and.returnValue(false);
      authSpy.hasRenewableSession.and.returnValue(true);
      service.ensureLoaded();
      const prime = httpMock.match(`${environment.backendURL}/admin/version`);
      if (prime.length === 1) prime[0].flush(mockInfo);

      service.refresh();
      const failReq = httpMock.expectOne(
        r =>
          r.url === `${environment.backendURL}/admin/version` &&
          r.params.get('refresh') === 'true',
      );
      localStorage.removeItem('firebase_session');
      localStorage.removeItem('USER_DETAILS');
      authSpy.hasRenewableSession.and.returnValue(false);

      failReq.flush('Error', {status, statusText: 'Auth or Gateway Error'});
      expect(service.versionInfo()).toBeNull();
      expect(service.refreshFailed()).toBeFalse();
      expect(service.loadFailed()).toBeFalse();
      expect(service.loading()).toBeFalse();
      expect(service.cooldownActive()).toBeFalse();
    }
  }));

  it('resets state on non-admin transition', fakeAsync(() => {
    const service = setup('browser', true);

    service.ensureLoaded();
    httpMock
      .expectOne(`${environment.backendURL}/admin/version`)
      .flush(mockInfo);
    expect(service.versionInfo()).toEqual(mockInfo);

    authSpy.isUserAdmin.and.returnValue(false);
    service.ensureLoaded();
    expect(service.versionInfo()).toBeNull();
    httpMock.expectNone(`${environment.backendURL}/admin/version`);

    service.refresh();
    httpMock.expectNone(`${environment.backendURL}/admin/version`);
    tick(5000);
  }));

  it('makes zero HTTP calls on SSR server platform', () => {
    const service = setup('server', true);

    service.ensureLoaded();
    service.refresh();

    httpMock.expectNone(`${environment.backendURL}/admin/version`);
    expect(service.versionInfo()).toBeNull();
  });

  it('makes zero HTTP calls when user is not an admin or logged out', () => {
    const service = setup('browser', false);

    service.ensureLoaded();
    service.refresh();

    httpMock.expectNone(`${environment.backendURL}/admin/version`);
    expect(service.versionInfo()).toBeNull();

    TestBed.resetTestingModule();
    const loggedOutService = setup('browser', true, false, false);
    loggedOutService.ensureLoaded();
    loggedOutService.refresh();
    httpMock.expectNone(`${environment.backendURL}/admin/version`);
  });

  it('handles HTTP errors gracefully without throwing or setting undefined version', () => {
    const service = setup('browser', true);
    const warnSpy = spyOn(console, 'warn');

    service.ensureLoaded();
    const req = httpMock.expectOne(`${environment.backendURL}/admin/version`);
    req.flush('Server error', {status: 500, statusText: 'Internal Error'});

    expect(warnSpy).toHaveBeenCalled();
    expect(service.loading()).toBeFalse();
    expect(service.loadFailed()).toBeTrue();
    expect(service.versionInfo()).toBeNull();
  });

  it('rejects non-GitHub, spoofed, and traversal release URLs in safeReleaseUrl', () => {
    const unsafeUrls = [
      'https://evil.example.com/phish',
      'javascript:alert(1)',
      'http://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12',
      'https://github.com.evil.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12',
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/../../evil',
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases\\evil',
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/%2e%2e/%2e%2e/evil/repo/releases/tag/v1',
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/%252e%252e/evil',
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/..%2fevil',
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases%5cevil',
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v1\nHeader',
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v1\x7fevil',
      'https://evil.com@github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.15',
    ];

    for (const badUrl of unsafeUrls) {
      TestBed.resetTestingModule();
      const service = setup('browser', true);
      service.ensureLoaded();
      const req = httpMock.expectOne(`${environment.backendURL}/admin/version`);
      req.flush({
        ...mockInfo,
        releaseUrl: badUrl,
      });
      expect(service.safeReleaseUrl())
        .withContext(`Expected ${badUrl} to be rejected`)
        .toBeNull();
      httpMock.verify();
    }
  });
});

describe('admin-version-session utils', () => {
  it('detects login route variants safely', () => {
    expect(isLoginRouteUrl('/login')).toBeTrue();
    expect(isLoginRouteUrl('/login?returnUrl=%2Fadmin')).toBeTrue();
    expect(isLoginRouteUrl('/login;foo=1')).toBeTrue();
    expect(isLoginRouteUrl('/login/e2e')).toBeTrue();
    expect(isLoginRouteUrl('/%6cogin')).toBeTrue();
    expect(isLoginRouteUrl('/%E0%A4%A')).toBeFalse();
    expect(isLoginRouteUrl('/admin/dashboard')).toBeFalse();
    expect(isLoginRouteUrl(null)).toBeFalse();
  });

  it('decodes JWT identity, detects account mismatches, and handles throwing storage', () => {
    const jwt = makeJwt({sub: ' 42 ', email: ' Admin@Google.com '});
    expect(decodeJwtIdentity(jwt)).toEqual({
      sub: '42',
      email: 'admin@google.com',
    });
    expect(decodeJwtIdentity('not-a-jwt')).toBeNull();

    const subOnlyStorage = {
      getItem: (k: string) =>
        k === 'firebase_session'
          ? JSON.stringify({token: makeJwt({sub: 'sub-only'})})
          : null,
    };
    expect(hasSessionAccountMismatch(subOnlyStorage)).toBeFalse();
    expect(readBrowserSessionOwner(subOnlyStorage)).toBe('sub:sub-only');

    const throwingStorage = {
      getItem: () => {
        throw new Error('storage blocked');
      },
    };
    expect(hasSessionAccountMismatch(throwingStorage)).toBeFalse();
    expect(readBrowserSessionOwner(throwingStorage)).toBeNull();
  });
});
