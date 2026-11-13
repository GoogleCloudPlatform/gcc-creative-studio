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
import {Subscription} from 'rxjs';
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
const INITIAL_RETRY_BACKOFF_MS = 60_000;
const UNSAFE_RELEASE_URL_RE = /[\s\\]|(?:^|\/)\.\.?(?:\/|$)/;
const GITHUB_REPO_PATH_RE = /^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\//;

@Injectable({
  providedIn: 'root',
})
export class AdminVersionService implements OnDestroy {
  private readonly baseUrl = `${environment.backendURL}/admin/version`;

  private readonly _versionInfo = signal<AdminVersionInfo | null>(null);
  private readonly _loading = signal<boolean>(false);
  private readonly _loadFailed = signal<boolean>(false);
  private readonly _refreshFailed = signal<boolean>(false);
  private readonly _justChecked = signal<boolean>(false);
  private readonly _cooldownActive = signal<boolean>(false);

  private failedAtMs: number | null = null;
  private requestSub: Subscription | null = null;
  private activeRequestId = 0;
  private justCheckedTimer: ReturnType<typeof setTimeout> | null = null;
  private cooldownTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly sessionSub: Subscription | null = null;

  readonly versionInfo = this._versionInfo.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly loadFailed = this._loadFailed.asReadonly();
  readonly refreshFailed = this._refreshFailed.asReadonly();
  readonly justChecked = this._justChecked.asReadonly();
  readonly cooldownActive = this._cooldownActive.asReadonly();

  readonly isUpdateAvailable = computed(
    () => this._versionInfo()?.status === 'update_available',
  );

  readonly safeReleaseUrl = computed(() => {
    const url = this._versionInfo()?.releaseUrl;
    if (!url || UNSAFE_RELEASE_URL_RE.test(url)) {
      return null;
    }
    try {
      // eslint-disable-next-line n/no-unsupported-features/node-builtins
      const parsed = new URL(url);
      if (
        parsed.origin === 'https://github.com' &&
        GITHUB_REPO_PATH_RE.test(parsed.pathname)
      ) {
        return url;
      }
    } catch {
      return null;
    }
    return null;
  });

  constructor(
    private readonly http: HttpClient,
    private readonly authService: AuthService,
    @Inject(PLATFORM_ID) private readonly platformId: Object,
  ) {
    this.sessionSub =
      this.authService.sessionChanged$?.subscribe(() => this.reset()) ?? null;
  }

  isBrowserAdmin(): boolean {
    return (
      isPlatformBrowser(this.platformId) &&
      (this.authService.isUserLoggedIn?.() ?? true) &&
      this.authService.isUserAdmin()
    );
  }

  reset(): void {
    this.activeRequestId++;
    this.requestSub?.unsubscribe();
    this.requestSub = null;
    this.clearTimers();
    this.failedAtMs = null;
    this._versionInfo.set(null);
    this._loading.set(false);
    this._loadFailed.set(false);
    this._refreshFailed.set(false);
    this._justChecked.set(false);
    this._cooldownActive.set(false);
  }

  ensureLoaded(): void {
    if (!this.isBrowserAdmin()) {
      this.reset();
      return;
    }
    if (this._versionInfo() !== null || this._loading()) {
      return;
    }
    if (
      this._loadFailed() &&
      this.failedAtMs !== null &&
      Date.now() - this.failedAtMs < INITIAL_RETRY_BACKOFF_MS
    ) {
      return;
    }
    this.fetchVersion(false);
  }

  refresh(): void {
    if (!this.isBrowserAdmin()) {
      this.reset();
      return;
    }
    if (this._loading() || this._cooldownActive()) {
      return;
    }
    this.startCooldown();
    this.fetchVersion(true);
  }

  ngOnDestroy(): void {
    this.sessionSub?.unsubscribe();
    this.requestSub?.unsubscribe();
    this.requestSub = null;
    this.clearTimers();
  }

  private clearTimers(): void {
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
    this.requestSub?.unsubscribe();
    const reqId = ++this.activeRequestId;
    this._loading.set(true);
    this._loadFailed.set(false);
    this._refreshFailed.set(false);

    const request$ = isRefresh
      ? this.http.get<AdminVersionInfo>(this.baseUrl, {
          params: {refresh: 'true'},
        })
      : this.http.get<AdminVersionInfo>(this.baseUrl);

    let received = false;

    const handleFailure = (err?: unknown): void => {
      if (reqId !== this.activeRequestId) {
        return;
      }
      if (err !== undefined) {
        console.warn('Failed to fetch admin version info', err);
      } else {
        console.warn('Admin version check completed without a response');
      }
      if (this._versionInfo() !== null) {
        this._refreshFailed.set(true);
      } else {
        this._loadFailed.set(true);
        this.failedAtMs = Date.now();
      }
    };

    const sub = request$
      .pipe(
        finalize(() => {
          if (reqId === this.activeRequestId) {
            this._loading.set(false);
            this.requestSub = null;
          }
        }),
      )
      .subscribe({
        next: info => {
          if (reqId !== this.activeRequestId) {
            return;
          }
          received = true;
          this.failedAtMs = null;
          this._versionInfo.set(info);
          this._loadFailed.set(false);
          this._refreshFailed.set(false);
          if (isRefresh) {
            this.triggerJustChecked();
          }
        },
        error: err => handleFailure(err),
        complete: () => {
          if (!received) {
            handleFailure();
          }
        },
      });
    this.requestSub = sub.closed ? null : sub;
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
