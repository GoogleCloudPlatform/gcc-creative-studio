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
import {provideHttpClient} from '@angular/common/http';
import {TestBed, fakeAsync, tick} from '@angular/core/testing';
import {environment} from '../../environments/environment';
import {AuthService} from '../common/services/auth.service';
import {AdminVersionInfo, AdminVersionService} from './admin-version.service';

describe('AdminVersionService', () => {
  let httpMock: HttpTestingController;
  let authSpy: jasmine.SpyObj<AuthService>;

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

  function setup(platformId: Object, isAdmin: boolean): AdminVersionService {
    authSpy = jasmine.createSpyObj<AuthService>('AuthService', ['isUserAdmin']);
    authSpy.isUserAdmin.and.returnValue(isAdmin);

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

  it('makes zero HTTP calls on SSR server platform', () => {
    const service = setup('server', true);

    service.ensureLoaded();
    service.refresh();

    httpMock.expectNone(`${environment.backendURL}/admin/version`);
    expect(service.versionInfo()).toBeNull();
  });

  it('makes zero HTTP calls when user is not an admin', () => {
    const service = setup('browser', false);

    service.ensureLoaded();
    service.refresh();

    httpMock.expectNone(`${environment.backendURL}/admin/version`);
    expect(service.versionInfo()).toBeNull();
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

  it('rejects non-GitHub release URLs in safeReleaseUrl', () => {
    const service = setup('browser', true);

    service.ensureLoaded();
    const req = httpMock.expectOne(`${environment.backendURL}/admin/version`);
    req.flush({
      ...mockInfo,
      releaseUrl: 'https://evil.example.com/phish',
    });

    expect(service.safeReleaseUrl()).toBeNull();
  });
});
