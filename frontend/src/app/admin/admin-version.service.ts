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
  WritableSignal,
  computed,
  signal,
} from '@angular/core';
import {finalize} from 'rxjs/operators';
import {environment} from '../../environments/environment';
import {AuthService} from '../common/services/auth.service';
import {UserService} from '../common/services/user.service';

export type VersionStatus = 'up_to_date' | 'update_available' | 'unavailable';

export interface AdminVersionInfo {
  currentVersion: string;
  latestVersion: string | null;
  status: VersionStatus;
  releaseUrl: string | null;
  checkedAt: string;
  refreshFailed?: boolean;
}

export const REFRESH_COOLDOWN_MS = 5000;
export const JUST_CHECKED_MS = 3000;
type TimerKey = 'justChecked' | 'cooldown';

@Injectable({providedIn: 'root'})
export class AdminVersionService implements OnDestroy {
  private readonly _versionInfo = signal<AdminVersionInfo | null>(null);
  private readonly _isAdmin = signal(false);
  private readonly _loading = signal(false);
  private readonly _loadFailed = signal(false);
  private readonly _refreshFailed = signal(false);
  private readonly _justChecked = signal(false);
  private readonly _cooldownActive = signal(false);

  readonly versionInfo = this._versionInfo.asReadonly();
  readonly isAdmin = this._isAdmin.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly loadFailed = this._loadFailed.asReadonly();
  readonly refreshFailed = this._refreshFailed.asReadonly();
  readonly justChecked = this._justChecked.asReadonly();
  readonly cooldownActive = this._cooldownActive.asReadonly();
  readonly isUpdateAvailable = computed(
    () => this._versionInfo()?.status === 'update_available',
  );

  private activeOwner: string | null = null;
  private requestEpoch = 0;
  private readonly timers: Partial<
    Record<TimerKey, ReturnType<typeof setTimeout>>
  > = {};

  constructor(
    private readonly http: HttpClient,
    private readonly authService: AuthService,
    private readonly userService: UserService,
    @Inject(PLATFORM_ID) private readonly platformId: Object,
  ) {
    this.syncSession();
  }

  ngOnDestroy(): void {
    this.clearTimer('justChecked', this._justChecked);
    this.clearTimer('cooldown', this._cooldownActive);
  }

  isBrowserAdmin(): boolean {
    return this.activeAdminEmail() !== null;
  }

  ensureLoaded(): void {
    const owner = this.syncSession();
    if (
      owner === null ||
      this._loading() ||
      (this._versionInfo() !== null && !this._loadFailed())
    )
      return;
    this.fetchVersion(false, owner);
  }

  refresh(): void {
    const owner = this.syncSession();
    if (owner === null || this._loading() || this._cooldownActive()) return;
    this.startTimer('cooldown', this._cooldownActive, REFRESH_COOLDOWN_MS);
    this.fetchVersion(true, owner);
  }

  reset(): void {
    this.requestEpoch++;
    this.clearTimer('justChecked', this._justChecked);
    this.clearTimer('cooldown', this._cooldownActive);
    this._versionInfo.set(null);
    this._loading.set(false);
    this._loadFailed.set(false);
    this._refreshFailed.set(false);
    this.activeOwner = null;
  }

  private activeAdminEmail(): string | null {
    if (
      !isPlatformBrowser(this.platformId) ||
      !this.authService.isUserAdmin() ||
      !this.authService.getToken()
    ) {
      return null;
    }
    return (
      this.userService.getUserDetails()?.email?.trim().toLowerCase() || null
    );
  }

  private syncSession(): string | null {
    const owner = this.activeAdminEmail();
    this._isAdmin.set(owner !== null);
    if (
      owner === null ||
      (this.activeOwner !== null && this.activeOwner !== owner)
    )
      this.reset();
    this.activeOwner = owner;
    return owner;
  }

  private fetchVersion(isRefresh: boolean, owner: string): void {
    const epoch = ++this.requestEpoch;
    this._loading.set(true);
    this._loadFailed.set(false);
    this._refreshFailed.set(false);
    if (isRefresh) this.clearTimer('justChecked', this._justChecked);

    const url = `${environment.backendURL}/admin/version${isRefresh ? '?refresh=true' : ''}`;
    this.http
      .get<AdminVersionInfo>(url)
      .pipe(
        finalize(() => epoch === this.requestEpoch && this._loading.set(false)),
      )
      .subscribe({
        next: info => {
          if (epoch !== this.requestEpoch || this.syncSession() !== owner)
            return;
          const refreshFailed = Boolean(info.refreshFailed);
          this._versionInfo.set(info);
          this._loadFailed.set(false);
          this._refreshFailed.set(refreshFailed);
          if (isRefresh && !refreshFailed)
            this.startTimer('justChecked', this._justChecked, JUST_CHECKED_MS);
        },
        error: err => {
          if (epoch !== this.requestEpoch) return;
          if (err?.status === 401 || err?.status === 403) {
            this._isAdmin.set(false);
            this.reset();
            return;
          }
          if (this._versionInfo() !== null) this._refreshFailed.set(true);
          else this._loadFailed.set(true);
        },
      });
  }

  private startTimer(
    key: TimerKey,
    target: WritableSignal<boolean>,
    ms: number,
  ): void {
    this.clearTimer(key, target);
    target.set(true);
    this.timers[key] = setTimeout(() => {
      delete this.timers[key];
      target.set(false);
    }, ms);
  }

  private clearTimer(key: TimerKey, target: WritableSignal<boolean>): void {
    const handle = this.timers[key];
    if (handle !== undefined) {
      clearTimeout(handle);
      delete this.timers[key];
    }
    target.set(false);
  }
}
