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

import {isPlatformBrowser} from '@angular/common';
import {HttpClient} from '@angular/common/http';
import {
  Inject,
  Injectable,
  OnDestroy,
  PLATFORM_ID,
  computed,
  signal,
} from '@angular/core';
import {finalize} from 'rxjs/operators';
import {environment} from '../../environments/environment';
import {AuthService} from '../common/services/auth.service';

export type AdminVersionStatus =
  | 'up_to_date'
  | 'update_available'
  | 'unavailable';

export interface AdminVersionInfo {
  currentVersion: string;
  latestVersion: string | null;
  status: AdminVersionStatus;
  releaseUrl: string | null;
  releaseName: string | null;
  publishedAt: string | null;
  checkedAt: string;
}

const JUST_CHECKED_MS = 1500;
const REFRESH_COOLDOWN_MS = 5000;

@Injectable({
  providedIn: 'root',
})
export class AdminVersionService implements OnDestroy {
  private readonly baseUrl = `${environment.backendURL}/admin/version`;

  private readonly _versionInfo = signal<AdminVersionInfo | null>(null);
  private readonly _loading = signal<boolean>(false);
  private readonly _loadFailed = signal<boolean>(false);
  private readonly _justChecked = signal<boolean>(false);
  private readonly _cooldownActive = signal<boolean>(false);

  private justCheckedTimer: ReturnType<typeof setTimeout> | null = null;
  private cooldownTimer: ReturnType<typeof setTimeout> | null = null;

  readonly versionInfo = this._versionInfo.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly loadFailed = this._loadFailed.asReadonly();
  readonly justChecked = this._justChecked.asReadonly();
  readonly cooldownActive = this._cooldownActive.asReadonly();

  readonly isUpdateAvailable = computed(
    () => this._versionInfo()?.status === 'update_available',
  );

  readonly safeReleaseUrl = computed(() => {
    const url = this._versionInfo()?.releaseUrl;
    return url && url.startsWith('https://github.com/') ? url : null;
  });

  constructor(
    private readonly http: HttpClient,
    private readonly authService: AuthService,
    @Inject(PLATFORM_ID) private readonly platformId: Object,
  ) {}

  isBrowserAdmin(): boolean {
    return isPlatformBrowser(this.platformId) && this.authService.isUserAdmin();
  }

  ensureLoaded(): void {
    if (!this.isBrowserAdmin()) {
      return;
    }
    if (this._versionInfo() !== null || this._loading() || this._loadFailed()) {
      return;
    }
    this.fetchVersion(false);
  }

  refresh(): void {
    if (!this.isBrowserAdmin() || this._loading() || this._cooldownActive()) {
      return;
    }
    this.startCooldown();
    this.fetchVersion(true);
  }

  ngOnDestroy(): void {
    if (this.justCheckedTimer !== null) {
      clearTimeout(this.justCheckedTimer);
      this.justCheckedTimer = null;
    }
    if (this.cooldownTimer !== null) {
      clearTimeout(this.cooldownTimer);
      this.cooldownTimer = null;
    }
  }

  private fetchVersion(isRefresh: boolean): void {
    this._loading.set(true);
    this._loadFailed.set(false);

    const request$ = isRefresh
      ? this.http.get<AdminVersionInfo>(this.baseUrl, {
          params: {refresh: 'true'},
        })
      : this.http.get<AdminVersionInfo>(this.baseUrl);

    request$.pipe(finalize(() => this._loading.set(false))).subscribe({
      next: info => {
        this._versionInfo.set(info);
        if (isRefresh) {
          this.triggerJustChecked();
        }
      },
      error: err => {
        console.warn('Failed to fetch admin version info', err);
        this._loadFailed.set(true);
      },
    });
  }

  private triggerJustChecked(): void {
    if (this.justCheckedTimer !== null) {
      clearTimeout(this.justCheckedTimer);
    }
    this._justChecked.set(true);
    this.justCheckedTimer = setTimeout(() => {
      this._justChecked.set(false);
      this.justCheckedTimer = null;
    }, JUST_CHECKED_MS);
  }

  private startCooldown(): void {
    if (this.cooldownTimer !== null) {
      clearTimeout(this.cooldownTimer);
    }
    this._cooldownActive.set(true);
    this.cooldownTimer = setTimeout(() => {
      this._cooldownActive.set(false);
      this.cooldownTimer = null;
    }, REFRESH_COOLDOWN_MS);
  }
}
