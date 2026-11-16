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
import {UserService} from '../common/services/user.service';

export type AdminVersionStatus =
  | 'up_to_date'
  | 'update_available'
  | 'unavailable';

export interface AdminVersionInfo {
  currentVersion: string;
  latestVersion: string | null;
  status: AdminVersionStatus;
  releaseUrl: string | null;
  checkedAt: string;
  refreshFailed?: boolean;
}

const FIREBASE_SESSION_KEY = 'firebase_session';
const USER_DETAILS_KEY = 'USER_DETAILS';
const JUST_CHECKED_MS = 1500;
const REFRESH_COOLDOWN_MS = 5000;
const INITIAL_RETRY_BACKOFF_MS = 60_000;
type TimerKey = 'justChecked' | 'cooldown';

function isLoginRouteUrl(rawUrl: string | null | undefined): boolean {
  if (!rawUrl) return false;
  const pathOnly = rawUrl.split(/[?#;]/, 1)[0].trim();
  return (
    pathOnly
      .split('/')
      .find(seg => seg.length > 0)
      ?.toLowerCase() === 'login'
  );
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split('.');
  if (parts.length !== 3 || !parts[1]) return null;
  try {
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padLen = (4 - (b64.length % 4)) % 4;
    const raw = atob(b64 + '='.repeat(padLen));
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) {
      bytes[i] = raw.charCodeAt(i);
    }
    // eslint-disable-next-line n/no-unsupported-features/node-builtins
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
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
  private readonly _isAdmin = signal<boolean>(false);
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
  readonly isAdmin = this._isAdmin.asReadonly();
  readonly isUpdateAvailable = computed(
    () => this._versionInfo()?.status === 'update_available',
  );

  constructor(
    private readonly http: HttpClient,
    private readonly authService: AuthService,
    private readonly userService: UserService,
    @Inject(PLATFORM_ID) private readonly platformId: Object,
    private readonly router: Router,
    private readonly ngZone: NgZone,
  ) {
    if (!isPlatformBrowser(this.platformId)) return;
    this._isAdmin.set(this.computeBrowserAdmin());
    this.routerSub = this.router.events.subscribe(e => {
      if (e instanceof NavigationStart || e instanceof NavigationEnd) {
        const url =
          e instanceof NavigationEnd ? e.urlAfterRedirects || e.url : e.url;
        this.syncSessionOwner(isLoginRouteUrl(url));
      }
    });
    this.storageListener = (e: StorageEvent) => {
      if (
        e.key !== null &&
        e.key !== FIREBASE_SESSION_KEY &&
        e.key !== USER_DETAILS_KEY
      ) {
        return;
      }
      this.ngZone.run(() =>
        this.syncSessionOwner(e.key === null || !e.newValue),
      );
    };
    window.addEventListener('storage', this.storageListener);
  }

  private readStoredToken(): string | null {
    if (typeof localStorage === 'undefined') return null;
    try {
      const raw = localStorage.getItem(FIREBASE_SESSION_KEY);
      if (!raw) return null;
      const parsed: unknown = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return null;
      }
      const token = (parsed as Record<string, unknown>)['token'];
      return typeof token === 'string' && token.trim() ? token.trim() : null;
    } catch {
      return null;
    }
  }

  private readSessionIdentity(): {
    token: string | null;
    email: string | null;
    sub: string | null;
    mismatch: boolean;
  } {
    const token = this.readStoredToken();
    const rawUserEmail = this.userService.getUserDetails()?.email;
    const userEmail =
      typeof rawUserEmail === 'string' && rawUserEmail.trim()
        ? rawUserEmail.trim().toLowerCase()
        : null;
    let tokenEmail: string | null = null;
    let tokenSub: string | null = null;
    const payload = token ? decodeJwtPayload(token) : null;
    if (payload) {
      if (typeof payload['email'] === 'string' && payload['email'].trim()) {
        tokenEmail = payload['email'].trim().toLowerCase();
      }
      if (typeof payload['sub'] === 'string' && payload['sub'].trim()) {
        tokenSub = payload['sub'].trim();
      }
    }
    const mismatch =
      tokenEmail !== null && userEmail !== null && tokenEmail !== userEmail;
    return {
      token,
      email: tokenEmail ?? userEmail,
      sub: tokenSub,
      mismatch,
    };
  }

  private computeBrowserAdmin(): boolean {
    if (
      !isPlatformBrowser(this.platformId) ||
      !this.authService.isUserAdmin()
    ) {
      return false;
    }
    const id = this.readSessionIdentity();
    return id.token !== null && !id.mismatch;
  }

  isBrowserAdmin(): boolean {
    return this.computeBrowserAdmin();
  }

  private currentSessionOwner(): string | null {
    if (!this.computeBrowserAdmin()) return null;
    const id = this.readSessionIdentity();
    if (id.email) return `email:${id.email}`;
    if (id.sub) return `sub:${id.sub}`;
    return id.token ? `token:${id.token}` : null;
  }

  private syncSessionOwner(forceReset = false): string | null {
    const owner = this.currentSessionOwner();
    this._isAdmin.set(owner !== null);
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
    if (this.storageListener !== null) {
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
          const refreshFailed = Boolean(info.refreshFailed);
          this._versionInfo.set(info);
          this._loadFailed.set(false);
          this._refreshFailed.set(refreshFailed);
          if (isRefresh && !refreshFailed) {
            this.setFlag('justChecked', this._justChecked, JUST_CHECKED_MS);
          }
        },
        error: err => onFail(err),
        complete: () => {
          if (!received) onFail();
        },
      });
    this.requestSub = sub.closed ? null : sub;
  }
}
