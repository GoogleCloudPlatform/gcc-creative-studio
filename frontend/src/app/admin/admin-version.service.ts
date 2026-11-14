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
  NgZone,
  OnDestroy,
  Optional,
  PLATFORM_ID,
  WritableSignal,
  computed,
  signal,
} from '@angular/core';
import {NavigationEnd, NavigationStart, Router} from '@angular/router';
import {Subscription} from 'rxjs';
import {finalize} from 'rxjs/operators';
import {environment} from '../../environments/environment';
import {AuthService} from '../common/services/auth.service';
import {
  hasSessionAccountMismatch,
  isLoginRouteUrl,
  isWatchedSessionStorageKey,
  readBrowserSessionOwner,
} from './admin-version-session.utils';

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
const GITHUB_PREFIX = 'https://github.com/';
type TimerKey = 'justChecked' | 'cooldown';
type RenewableAuth = {hasRenewableSession?: () => boolean};

function hasControlOrWhitespaceChar(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code <= 0x20 || code === 0x7f) {
      return true;
    }
  }
  return false;
}

@Injectable({providedIn: 'root'})
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
  private timers: Partial<Record<TimerKey, ReturnType<typeof setTimeout>>> = {};
  private routerSub: Subscription | null = null;
  private storageListener: ((event: StorageEvent) => void) | null = null;
  private loadedSessionOwner: string | null = null;

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
    if (
      !url ||
      hasControlOrWhitespaceChar(url) ||
      !url.startsWith(GITHUB_PREFIX)
    ) {
      return null;
    }
    let decoded = url;
    try {
      for (let i = 0; i < 2; i++) {
        decoded = decodeURIComponent(decoded);
      }
    } catch {
      return null;
    }
    if (
      hasControlOrWhitespaceChar(decoded) ||
      UNSAFE_RELEASE_URL_RE.test(url) ||
      UNSAFE_RELEASE_URL_RE.test(decoded)
    ) {
      return null;
    }
    try {
      // eslint-disable-next-line n/no-unsupported-features/node-builtins
      const parsed = new URL(url);
      if (
        parsed.origin !== 'https://github.com' ||
        parsed.username ||
        parsed.password ||
        !GITHUB_REPO_PATH_RE.test(parsed.pathname)
      ) {
        return null;
      }
      const rawPrefix = url
        .slice('https://github.com'.length)
        .split('/')
        .slice(1, 3)
        .join('/');
      const parsedPrefix = parsed.pathname.split('/').slice(1, 3).join('/');
      return rawPrefix && rawPrefix === parsedPrefix ? parsed.href : null;
    } catch {
      return null;
    }
  });

  constructor(
    private readonly http: HttpClient,
    private readonly authService: AuthService,
    @Inject(PLATFORM_ID) private readonly platformId: Object,
    @Optional() @Inject(Router) private readonly router: Router | null = null,
    @Optional() @Inject(NgZone) private readonly ngZone: NgZone | null = null,
  ) {
    if (!isPlatformBrowser(this.platformId)) return;
    this.routerSub =
      this.router?.events?.subscribe(e => {
        if (e instanceof NavigationStart || e instanceof NavigationEnd) {
          const url =
            e instanceof NavigationEnd ? e.urlAfterRedirects || e.url : e.url;
          this.syncSessionOwner(isLoginRouteUrl(url));
        }
      }) ?? null;
    if (typeof window === 'undefined') return;
    this.storageListener = (e: StorageEvent) => {
      if (!isWatchedSessionStorageKey(e.key)) return;
      const run = () => this.syncSessionOwner(e.key === null || !e.newValue);
      if (this.ngZone) this.ngZone.run(run);
      else run();
    };
    window.addEventListener('storage', this.storageListener);
  }

  isBrowserAdmin(): boolean {
    if (!isPlatformBrowser(this.platformId) || !this.authService.isUserAdmin())
      return false;
    if (
      typeof localStorage !== 'undefined' &&
      hasSessionAccountMismatch(localStorage)
    ) {
      return false;
    }
    const loggedIn = this.authService.isUserLoggedIn?.();
    if (loggedIn === undefined || loggedIn) return true;
    const renewable = (this.authService as RenewableAuth).hasRenewableSession;
    return typeof renewable === 'function'
      ? renewable.call(this.authService)
      : false;
  }

  private currentSessionOwner(): string | null {
    if (!this.isBrowserAdmin()) return null;
    const owner =
      typeof localStorage !== 'undefined'
        ? readBrowserSessionOwner(localStorage)
        : null;
    return owner ?? '__authenticated_admin__';
  }

  private syncSessionOwner(forceReset = false): string | null {
    const owner = this.currentSessionOwner();
    if (
      forceReset ||
      owner === null ||
      (this.loadedSessionOwner !== null && owner !== this.loadedSessionOwner)
    ) {
      this.reset();
    }
    return owner;
  }

  private teardownActiveWork(): void {
    this.requestSub?.unsubscribe();
    this.requestSub = null;
    Object.values(this.timers).forEach(id => clearTimeout(id));
    this.timers = {};
  }

  reset(): void {
    this.activeRequestId++;
    this.teardownActiveWork();
    this.failedAtMs = null;
    this.loadedSessionOwner = null;
    this._versionInfo.set(null);
    this._loading.set(false);
    this._loadFailed.set(false);
    this._refreshFailed.set(false);
    this._justChecked.set(false);
    this._cooldownActive.set(false);
  }

  ensureLoaded(): void {
    const owner = this.syncSessionOwner();
    if (owner === null || this._versionInfo() !== null || this._loading())
      return;
    if (
      this._loadFailed() &&
      this.failedAtMs !== null &&
      Date.now() - this.failedAtMs < INITIAL_RETRY_BACKOFF_MS
    ) {
      return;
    }
    this.fetchVersion(false, owner);
  }

  refresh(): void {
    const owner = this.syncSessionOwner();
    if (owner === null || this._loading() || this._cooldownActive()) return;
    this.setFlag('cooldown', this._cooldownActive, REFRESH_COOLDOWN_MS);
    this.fetchVersion(true, owner);
  }

  ngOnDestroy(): void {
    this.routerSub?.unsubscribe();
    this.routerSub = null;
    if (this.storageListener !== null && typeof window !== 'undefined') {
      window.removeEventListener('storage', this.storageListener);
      this.storageListener = null;
    }
    this.teardownActiveWork();
  }

  private setFlag(
    key: TimerKey,
    flag: WritableSignal<boolean>,
    ms: number,
  ): void {
    clearTimeout(this.timers[key]);
    flag.set(true);
    this.timers[key] = setTimeout(() => {
      delete this.timers[key];
      flag.set(false);
    }, ms);
  }

  private fetchVersion(isRefresh: boolean, owner: string): void {
    this.requestSub?.unsubscribe();
    const reqId = ++this.activeRequestId;
    this.loadedSessionOwner = owner;
    this._loading.set(true);
    this._loadFailed.set(false);
    this._refreshFailed.set(false);
    const request$ = this.http.get<AdminVersionInfo>(
      this.baseUrl,
      isRefresh ? {params: {refresh: 'true'}} : undefined,
    );
    let received = false;
    const isStale = () =>
      reqId !== this.activeRequestId || this.syncSessionOwner() !== owner;
    const onFail = (err?: unknown): void => {
      if (isStale()) return;
      if (err !== undefined)
        console.warn('Failed to fetch admin version info', err);
      else console.warn('Admin version check completed without a response');
      if (this._versionInfo() !== null) this._refreshFailed.set(true);
      else {
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
          if (isStale()) return;
          received = true;
          this.failedAtMs = null;
          this._versionInfo.set(info);
          this._loadFailed.set(false);
          this._refreshFailed.set(false);
          if (isRefresh)
            this.setFlag('justChecked', this._justChecked, JUST_CHECKED_MS);
        },
        error: err => onFail(err),
        complete: () => {
          if (!received) onFail();
        },
      });
    this.requestSub = sub.closed ? null : sub;
  }
}
