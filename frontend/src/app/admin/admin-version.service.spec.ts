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
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {HttpClient, provideHttpClient} from '@angular/common/http';
import {TestBed, fakeAsync, tick} from '@angular/core/testing';
import {EMPTY, Subject} from 'rxjs';
import {environment} from '../../environments/environment';
import {AuthService} from '../common/services/auth.service';
import {AdminVersionInfo, AdminVersionService} from './admin-version.service';

describe('AdminVersionService', () => {
  let httpMock: HttpTestingController;
  let authSpy: jasmine.SpyObj<AuthService>;
  let sessionChangedSubject: Subject<void>;

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
  ): AdminVersionService {
    sessionChangedSubject = new Subject<void>();
    authSpy = jasmine.createSpyObj<AuthService>(
      'AuthService',
      ['isUserAdmin', 'isUserLoggedIn'],
      {sessionChanged$: sessionChangedSubject.asObservable()},
    );
    authSpy.isUserAdmin.and.returnValue(isAdmin);
    authSpy.isUserLoggedIn.and.returnValue(isLoggedIn);

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {provide: AuthService, useValue: authSpy},
        {provide: PLATFORM_ID, useValue: platformId},
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    return TestBed.inject(AdminVersionService);
  }

  afterEach(() => {
    httpMock.verify();
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

  it('sends refresh=true, sets justChecked for 1.5s, and enforces 5s cooldown', fakeAsync(() => {
    const service = setup('browser', true);

    service.refresh();
    // Second call during loading/cooldown should be ignored
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

    // Still within 5s cooldown
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

    // Within 60s backoff, ensureLoaded() does not retry
    nowMs += 30_000;
    service.ensureLoaded();
    expect(getSpy).toHaveBeenCalledTimes(1);

    // At >= 60s backoff, ensureLoaded() retries cleanly
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

  it('resets state on sessionChanged$, non-admin transition, and cancels in-flight requests', fakeAsync(() => {
    const service = setup('browser', true);

    service.refresh();
    const inFlightReq = httpMock.expectOne(
      r =>
        r.url === `${environment.backendURL}/admin/version` &&
        r.params.get('refresh') === 'true',
    );
    expect(service.loading()).toBeTrue();
    expect(service.cooldownActive()).toBeTrue();

    // Session change cancels in-flight request and clears timers/signals
    sessionChangedSubject.next();
    expect(inFlightReq.cancelled).toBeTrue();
    expect(service.loading()).toBeFalse();
    expect(service.cooldownActive()).toBeFalse();
    expect(service.versionInfo()).toBeNull();

    // Load again, then lose admin privilege -> ensureLoaded() / refresh() resets
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
    const loggedOutService = setup('browser', true, false);
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
