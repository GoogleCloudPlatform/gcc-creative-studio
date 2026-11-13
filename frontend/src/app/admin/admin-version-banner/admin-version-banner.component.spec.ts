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

import {PLATFORM_ID, computed, signal} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {AuthService} from '../../common/services/auth.service';
import {AdminVersionInfo, AdminVersionService} from '../admin-version.service';
import {AdminVersionBannerComponent} from './admin-version-banner.component';

describe('AdminVersionBannerComponent', () => {
  let fixture: ComponentFixture<AdminVersionBannerComponent>;
  let versionInfoSig: ReturnType<typeof signal<AdminVersionInfo | null>>;
  let authSpy: jasmine.SpyObj<AuthService>;
  let ensureLoadedSpy: jasmine.Spy;

  async function configure(
    platformId: Object,
    isAdmin: boolean,
    initialInfo: AdminVersionInfo | null,
  ): Promise<void> {
    versionInfoSig = signal<AdminVersionInfo | null>(initialInfo);
    ensureLoadedSpy = jasmine.createSpy('ensureLoaded');
    authSpy = jasmine.createSpyObj<AuthService>('AuthService', ['isUserAdmin']);
    authSpy.isUserAdmin.and.returnValue(isAdmin);

    const mockVersionService = {
      versionInfo: versionInfoSig.asReadonly(),
      isUpdateAvailable: computed(
        () => versionInfoSig()?.status === 'update_available',
      ),
      safeReleaseUrl: computed(() => {
        const url = versionInfoSig()?.releaseUrl;
        return url && url.startsWith('https://github.com/') ? url : null;
      }),
      ensureLoaded: ensureLoadedSpy,
    };

    await TestBed.configureTestingModule({
      declarations: [AdminVersionBannerComponent],
      providers: [
        {provide: AdminVersionService, useValue: mockVersionService},
        {provide: AuthService, useValue: authSpy},
        {provide: PLATFORM_ID, useValue: platformId},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(AdminVersionBannerComponent);
    fixture.detectChanges();
  }

  it('renders nothing when up_to_date or unavailable', async () => {
    await configure('browser', true, {
      currentVersion: '26.11.12',
      latestVersion: '26.11.12',
      status: 'up_to_date',
      releaseUrl:
        'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12',
      releaseName: 'v26.11.12',
      publishedAt: null,
      checkedAt: '2026-11-12T20:05:00Z',
    });
    expect(ensureLoadedSpy).toHaveBeenCalledTimes(1);
    expect(fixture.nativeElement.querySelector('[role="status"]')).toBeNull();

    versionInfoSig.set({
      currentVersion: '26.11.12',
      latestVersion: null,
      status: 'unavailable',
      releaseUrl: null,
      releaseName: null,
      publishedAt: null,
      checkedAt: '2026-11-12T20:05:00Z',
    });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="status"]')).toBeNull();
  });

  it('renders WCAG-AA banner and GitHub link when update_available for browser admin', async () => {
    const releaseUrl =
      'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.15';
    await configure('browser', true, {
      currentVersion: '26.11.12',
      latestVersion: '26.11.15',
      status: 'update_available',
      releaseUrl,
      releaseName: 'v26.11.15',
      publishedAt: '2026-11-15T12:00:00Z',
      checkedAt: '2026-11-15T12:05:00Z',
    });

    const banner = fixture.nativeElement.querySelector(
      '[role="status"]',
    ) as HTMLElement;
    expect(banner).not.toBeNull();
    expect(banner.textContent).toContain('New version available: v26.11.15');
    expect(banner.textContent).toContain('Installed: v26.11.12');

    const link = banner.querySelector('a') as HTMLAnchorElement;
    expect(link).not.toBeNull();
    expect(link.getAttribute('href')).toBe(releaseUrl);
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('renders nothing for non-admins or SSR', async () => {
    const outdatedInfo: AdminVersionInfo = {
      currentVersion: '26.11.12',
      latestVersion: '26.11.15',
      status: 'update_available',
      releaseUrl:
        'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.15',
      releaseName: 'v26.11.15',
      publishedAt: null,
      checkedAt: '2026-11-15T12:05:00Z',
    };

    await configure('browser', false, outdatedInfo);
    expect(ensureLoadedSpy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('[role="status"]')).toBeNull();

    TestBed.resetTestingModule();
    await configure('server', true, outdatedInfo);
    expect(ensureLoadedSpy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('[role="status"]')).toBeNull();
  });
});
