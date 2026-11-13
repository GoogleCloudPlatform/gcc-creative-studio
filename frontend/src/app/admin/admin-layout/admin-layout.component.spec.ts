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

import {PLATFORM_ID, computed, signal} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {MatIconModule} from '@angular/material/icon';
import {MatListModule} from '@angular/material/list';
import {MatSidenavModule} from '@angular/material/sidenav';
import {MatTooltipModule} from '@angular/material/tooltip';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {RouterModule, provideRouter} from '@angular/router';
import {AuthService} from '../../common/services/auth.service';
import {AdminVersionInfo, AdminVersionService} from '../admin-version.service';
import {AdminLayoutComponent} from './admin-layout.component';

describe('AdminLayoutComponent', () => {
  let component: AdminLayoutComponent;
  let fixture: ComponentFixture<AdminLayoutComponent>;

  let versionInfoSig: ReturnType<typeof signal<AdminVersionInfo | null>>;
  let loadingSig: ReturnType<typeof signal<boolean>>;
  let loadFailedSig: ReturnType<typeof signal<boolean>>;
  let justCheckedSig: ReturnType<typeof signal<boolean>>;
  let cooldownActiveSig: ReturnType<typeof signal<boolean>>;
  let ensureLoadedSpy: jasmine.Spy;
  let refreshSpy: jasmine.Spy;
  let authSpy: jasmine.SpyObj<AuthService>;

  async function configure(
    platformId: Object,
    isAdmin: boolean,
  ): Promise<void> {
    versionInfoSig = signal<AdminVersionInfo | null>({
      currentVersion: '26.11.12',
      latestVersion: '26.11.12',
      status: 'up_to_date',
      releaseUrl:
        'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12',
      releaseName: 'v26.11.12',
      publishedAt: '2026-11-12T20:00:00Z',
      checkedAt: '2026-11-12T20:05:00Z',
    });
    loadingSig = signal(false);
    loadFailedSig = signal(false);
    justCheckedSig = signal(false);
    cooldownActiveSig = signal(false);
    ensureLoadedSpy = jasmine.createSpy('ensureLoaded');
    refreshSpy = jasmine.createSpy('refresh');
    authSpy = jasmine.createSpyObj<AuthService>('AuthService', ['isUserAdmin']);
    authSpy.isUserAdmin.and.returnValue(isAdmin);

    const mockVersionService = {
      versionInfo: versionInfoSig.asReadonly(),
      loading: loadingSig.asReadonly(),
      loadFailed: loadFailedSig.asReadonly(),
      justChecked: justCheckedSig.asReadonly(),
      cooldownActive: cooldownActiveSig.asReadonly(),
      isUpdateAvailable: computed(
        () => versionInfoSig()?.status === 'update_available',
      ),
      safeReleaseUrl: computed(() => {
        const url = versionInfoSig()?.releaseUrl;
        return url && url.startsWith('https://github.com/') ? url : null;
      }),
      ensureLoaded: ensureLoadedSpy,
      refresh: refreshSpy,
    };

    await TestBed.configureTestingModule({
      declarations: [AdminLayoutComponent],
      imports: [
        RouterModule,
        MatSidenavModule,
        MatListModule,
        MatIconModule,
        MatTooltipModule,
        NoopAnimationsModule,
      ],
      providers: [
        provideRouter([]),
        {provide: AdminVersionService, useValue: mockVersionService},
        {provide: AuthService, useValue: authSpy},
        {provide: PLATFORM_ID, useValue: platformId},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(AdminLayoutComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  it('creates and loads System Version footer for browser admins', async () => {
    await configure('browser', true);
    expect(component).toBeTruthy();
    expect(ensureLoadedSpy).toHaveBeenCalledTimes(1);

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('System Version');
    expect(text).toContain('v26.11.12');
    expect(text).toContain('Up to date');
    expect(text).toContain('Release notes');
  });

  it('renders update_available, unavailable, and cold-start loading states', async () => {
    await configure('browser', true);

    versionInfoSig.set({
      currentVersion: '26.11.12',
      latestVersion: '26.11.15',
      status: 'update_available',
      releaseUrl:
        'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.15',
      releaseName: 'v26.11.15',
      publishedAt: null,
      checkedAt: '2026-11-12T20:05:00Z',
    });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(
      'New version available: v26.11.15',
    );

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
    expect(fixture.nativeElement.textContent).toContain(
      'Update check unavailable',
    );

    versionInfoSig.set({
      currentVersion: '26.11.12',
      latestVersion: '26.11.12',
      status: 'up_to_date',
      releaseUrl:
        'https://github.com/GoogleCloudPlatform/gcc-creative-studio/releases/tag/v26.11.12',
      releaseName: 'v26.11.12',
      publishedAt: null,
      checkedAt: '2026-11-12T20:05:00Z',
    });
    loadFailedSig.set(true);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('v26.11.12');
    expect(fixture.nativeElement.textContent).toContain(
      'Update check unavailable',
    );
    expect(fixture.nativeElement.textContent).not.toContain('Up to date');

    loadFailedSig.set(false);
    versionInfoSig.set(null);
    loadingSig.set(true);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(
      'Checking for updates…',
    );
  });

  it('calls refresh() on Check now click and disables button during loading/cooldown', async () => {
    await configure('browser', true);

    const btn = fixture.nativeElement.querySelector(
      'button',
    ) as HTMLButtonElement;
    expect(btn.disabled).toBeFalse();
    btn.click();
    expect(refreshSpy).toHaveBeenCalledTimes(1);

    cooldownActiveSig.set(true);
    fixture.detectChanges();
    expect(btn.disabled).toBeTrue();

    cooldownActiveSig.set(false);
    loadingSig.set(true);
    fixture.detectChanges();
    expect(btn.disabled).toBeTrue();
    expect(btn.textContent?.trim()).toBe('Checking…');
  });

  it('hides System Version footer and skips ensureLoaded for non-admin or SSR', async () => {
    await configure('browser', false);
    expect(ensureLoadedSpy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).not.toContain('System Version');

    TestBed.resetTestingModule();
    await configure('server', true);
    expect(ensureLoadedSpy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).not.toContain('System Version');
  });
});
