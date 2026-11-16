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

import {provideHttpClient} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {PLATFORM_ID} from '@angular/core';
import {TestBed, fakeAsync, tick} from '@angular/core/testing';
import {environment} from '../../environments/environment';
import {AuthService} from '../common/services/auth.service';
import {UserService} from '../common/services/user.service';
import {
  AdminVersionInfo,
  AdminVersionService,
  JUST_CHECKED_MS,
  REFRESH_COOLDOWN_MS,
} from './admin-version.service';

describe('AdminVersionService', () => {
  let httpMock: HttpTestingController;
  let isAdminFlag: boolean;
  let tokenValue: string | null;
  let userEmail: string | null;

  const endpoint = `${environment.backendURL}/admin/version`;
  const mockInfo: AdminVersionInfo = {
    currentVersion: '26.11.12',
    latestVersion: '26.11.12',
    status: 'up_to_date',
    releaseUrl:
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12',
    checkedAt: '2026-11-12T20:05:00Z',
  };

  function setup(
    platformId: 'browser' | 'server' = 'browser',
  ): AdminVersionService {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: AuthService,
          useValue: {
            isUserAdmin: () => isAdminFlag,
            getToken: () => tokenValue,
          },
        },
        {
          provide: UserService,
          useValue: {
            getUserDetails: () => (userEmail ? {email: userEmail} : null),
          },
        },
        {provide: PLATFORM_ID, useValue: platformId},
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
    return TestBed.inject(AdminVersionService);
  }

  beforeEach(() => {
    isAdminFlag = true;
    tokenValue = 'admin-jwt';
    userEmail = 'admin@example.com';
  });

  afterEach(() => {
    httpMock?.verify();
    TestBed.resetTestingModule();
  });

  it('skips loading on SSR, non-admin users, missing tokens, or missing user details', () => {
    const ssrService = setup('server');
    expect(ssrService.isBrowserAdmin()).toBeFalse();
    expect(ssrService.isAdmin()).toBeFalse();
    ssrService.ensureLoaded();
    ssrService.refresh();
    httpMock.expectNone(endpoint);
    TestBed.resetTestingModule();

    isAdminFlag = false;
    const userService = setup('browser');
    expect(userService.isBrowserAdmin()).toBeFalse();
    userService.ensureLoaded();
    httpMock.expectNone(endpoint);
    TestBed.resetTestingModule();

    isAdminFlag = true;
    tokenValue = null;
    const noTokenService = setup('browser');
    expect(noTokenService.isBrowserAdmin()).toBeFalse();
    noTokenService.ensureLoaded();
    httpMock.expectNone(endpoint);
    TestBed.resetTestingModule();

    tokenValue = 'admin-jwt';
    userEmail = null;
    const noUserService = setup('browser');
    expect(noUserService.isBrowserAdmin()).toBeFalse();
    noUserService.ensureLoaded();
    httpMock.expectNone(endpoint);
  });

  it('keeps isBrowserAdmin() pure without mutating isAdmin signal', () => {
    isAdminFlag = false;
    const service = setup('browser');
    expect(service.isAdmin()).toBeFalse();

    isAdminFlag = true;
    expect(service.isBrowserAdmin()).toBeTrue();
    expect(service.isAdmin()).toBeFalse();

    service.ensureLoaded();
    httpMock.expectOne(endpoint).flush(mockInfo);
    expect(service.isAdmin()).toBeTrue();
  });

  it('loads version once for browser admins and tracks update availability', () => {
    const updateInfo: AdminVersionInfo = {
      ...mockInfo,
      latestVersion: '26.11.15',
      status: 'update_available',
    };
    const service = setup('browser');

    service.ensureLoaded();
    service.ensureLoaded();
    const req = httpMock.expectOne(endpoint);
    expect(req.request.method).toBe('GET');
    expect(service.loading()).toBeTrue();

    req.flush(updateInfo);
    expect(service.loading()).toBeFalse();
    expect(service.versionInfo()).toEqual(updateInfo);
    expect(service.isUpdateAvailable()).toBeTrue();

    service.ensureLoaded();
    httpMock.expectNone(endpoint);
  });

  it('forces refresh with cooldown and temporary justChecked indicator', fakeAsync(() => {
    const service = setup('browser');

    service.ensureLoaded();
    httpMock.expectOne(endpoint).flush(mockInfo);

    service.refresh();
    expect(service.cooldownActive()).toBeTrue();
    service.refresh();

    const refreshReq = httpMock.expectOne(`${endpoint}?refresh=true`);
    refreshReq.flush(mockInfo);
    expect(service.justChecked()).toBeTrue();
    expect(service.refreshFailed()).toBeFalse();

    tick(JUST_CHECKED_MS);
    expect(service.justChecked()).toBeFalse();
    expect(service.cooldownActive()).toBeTrue();

    tick(REFRESH_COOLDOWN_MS - JUST_CHECKED_MS);
    expect(service.cooldownActive()).toBeFalse();

    service.refresh();
    httpMock.expectOne(`${endpoint}?refresh=true`).flush(mockInfo);
    tick(REFRESH_COOLDOWN_MS);
  }));

  it('sets refreshFailed without clearing cached data on HTTP or backend refresh failure', fakeAsync(() => {
    const service = setup('browser');
    service.ensureLoaded();
    httpMock.expectOne(endpoint).flush(mockInfo);

    service.refresh();
    httpMock
      .expectOne(`${endpoint}?refresh=true`)
      .flush('upstream error', {status: 500, statusText: 'Server Error'});

    expect(service.refreshFailed()).toBeTrue();
    expect(service.loadFailed()).toBeFalse();
    expect(service.justChecked()).toBeFalse();
    expect(service.versionInfo()).toEqual(mockInfo);

    tick(REFRESH_COOLDOWN_MS);

    service.refresh();
    httpMock
      .expectOne(`${endpoint}?refresh=true`)
      .flush({...mockInfo, refreshFailed: true});
    expect(service.refreshFailed()).toBeTrue();
    expect(service.justChecked()).toBeFalse();

    tick(REFRESH_COOLDOWN_MS);
  }));

  it('sets loadFailed on initial error and recovers on retry', () => {
    const service = setup('browser');
    service.ensureLoaded();
    httpMock
      .expectOne(endpoint)
      .flush('down', {status: 502, statusText: 'Bad Gateway'});

    expect(service.loadFailed()).toBeTrue();
    expect(service.versionInfo()).toBeNull();

    service.ensureLoaded();
    httpMock.expectOne(endpoint).flush(mockInfo);
    expect(service.loadFailed()).toBeFalse();
    expect(service.versionInfo()).toEqual(mockInfo);
  });

  it('resets state and discards stale responses on user change, sign-out, or 401/403', () => {
    const service = setup('browser');
    service.ensureLoaded();
    httpMock.expectOne(endpoint).flush(mockInfo);

    userEmail = 'second-admin@example.com';
    service.ensureLoaded();
    const secondReq = httpMock.expectOne(endpoint);
    expect(service.versionInfo()).toBeNull();
    secondReq.flush({
      ...mockInfo,
      latestVersion: '26.11.15',
      status: 'update_available',
    });
    expect(service.versionInfo()?.latestVersion).toBe('26.11.15');

    tokenValue = null;
    service.ensureLoaded();
    expect(service.isAdmin()).toBeFalse();
    expect(service.versionInfo()).toBeNull();

    tokenValue = 'admin-jwt';
    service.ensureLoaded();
    httpMock
      .expectOne(endpoint)
      .flush(
        {detail: 'Unauthorized'},
        {status: 401, statusText: 'Unauthorized'},
      );
    expect(service.isAdmin()).toBeFalse();
    expect(service.versionInfo()).toBeNull();
  });
});
