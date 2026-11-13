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

import {
  Injectable,
  NgZone,
  OnDestroy,
  PLATFORM_ID,
  inject,
} from '@angular/core';
import {Router} from '@angular/router';
import {UserModel, UserRolesEnum} from '../models/user.model';
import {HttpClient, HttpHeaders, HttpErrorResponse} from '@angular/common/http';
import {environment} from '../../../environments/environment';
import {
  Auth,
  GoogleAuthProvider,
  IdTokenResult,
  UserCredential,
  signInWithPopup,
} from '@angular/fire/auth';
import {UserService} from '../services/user.service';
import {NotificationService} from './notification.service';
import {Observable, defer, firstValueFrom, from, throwError, of} from 'rxjs';
import {
  catchError,
  finalize,
  shareReplay,
  tap,
  map,
  switchMap,
} from 'rxjs/operators';
import {isPlatformBrowser} from '@angular/common';
import {
  AuthSessionStore,
  RENEW_RETRY_MS,
  RenewTrigger,
  SESSION_STORAGE_KEY,
} from './auth-session.store';
import {
  AccountMismatchError,
  GisCredentialResponse,
  GisIdApi,
  GisPromptMomentNotification,
  GoogleIdTokenPayload,
  decodeGoogleJwtPayload,
  extractSessionHints,
  isSameSessionAccount,
  resolveSessionExpiry,
  sanitizeReturnUrl,
} from './auth-token.utils';

declare const google: {accounts?: {id?: GisIdApi}} | undefined;

const USER_DETAILS = 'USER_DETAILS';
const LOGIN_ROUTE = '/login';
const RENEW_LOCK_NAME = 'cs-session-renew';
const LOGIN_PROMPT_TIMEOUT_MS = 15000;
const SILENT_PROMPT_TIMEOUT_MS = 10000;
const LOCK_WAIT_TIMEOUT_MS = 5000;
const SESSION_EXPIRED_MESSAGE = 'Your session expired. Please sign in again.';
const SESSION_EXPIRED_DURATION_MS = 6000;

interface RenewalResult {
  token: string;
  /** False when another tab had already renewed and we adopted its token. */
  renewedHere: boolean;
}

@Injectable({
  providedIn: 'root',
})
export class AuthService implements OnDestroy {
  private readonly auth: Auth = inject(Auth);
  private readonly platformId = inject(PLATFORM_ID);
  private readonly ngZone = inject(NgZone);
  private readonly notificationService = inject(NotificationService, {
    optional: true,
  });
  private readonly provider: GoogleAuthProvider = new GoogleAuthProvider();
  private readonly isBrowser = isPlatformBrowser(this.platformId);

  // Store token temporarily in memory for the session
  private currentOAuthAccessToken: string | null = null;
  private readonly session = new AuthSessionStore(
    this.isBrowser,
    {
      onRenewNeeded: trigger =>
        this.ngZone.run(() => this.renewInBackground(trigger)),
      onSignedOutElsewhere: () =>
        this.ngZone.run(() => {
          this.sessionGeneration++;
          this.pendingNavigationUrl = null;
          this.cancelGooglePrompt();
          this.navigateToLoginIfNeeded();
        }),
    },
    fn => this.ngZone.runOutsideAngular(fn),
  );
  private inFlightRenewal$: Observable<RenewalResult> | null = null;
  /** Bumped on every sign-out so an in-flight renewal cannot revive it. */
  private sessionGeneration = 0;
  private lastFailedRenewalAt: number | null = null;
  private promptBlockedToken: string | null = null;
  private pendingNavigationUrl: string | null = null;

  constructor(
    private router: Router,
    private httpClient: HttpClient,
    private userService: UserService,
  ) {
    this.provider.setCustomParameters({
      prompt: 'select_account',
    });
    this.session.load();
    this.session.startListening();
  }

  ngOnDestroy(): void {
    this.session.destroy();
  }

  private get firebaseIdToken(): string | null {
    return this.session.token;
  }

  /**
   * Local development sign-in method to get a Firebase ID token.
   */
  signInWithGoogleFirebase(): Observable<string> {
    return from(signInWithPopup(this.auth, this.provider)).pipe(
      switchMap((userCredential: UserCredential) => {
        if (!userCredential.user) {
          return throwError(
            () => new Error('Firebase user not found after sign-in.'),
          );
        }
        return from(userCredential.user.getIdTokenResult());
      }),
      switchMap((idTokenResult: IdTokenResult) => {
        const token = idTokenResult.token;
        let expiry = Date.parse(idTokenResult.expirationTime);
        try {
          expiry = this.expiryFromToken(token);
        } catch {
          // Fall back to Firebase's parsed expirationTime for synthetic test tokens.
        }
        this.saveFreshSession(token, expiry);

        return this.syncUserWithBackend$(token).pipe(map(() => token));
      }),
      catchError((error: unknown) => {
        console.error('An error occurred during the sign-in process:', error);
        return throwError(
          () => new Error(`Sign-in failed. Please try again. ${String(error)}`),
        );
      }),
    );
  }

  /**
   * Sign-in with Google Identity Services, returning a Google ID token that
   * Cloud Run IAM and the backend accept.
   */
  signInForGoogleIdentityPlatform(): Observable<string> {
    return this.promptForIdentityPlatformToken$().pipe(
      switchMap(idToken => {
        this.saveFreshSession(idToken, this.expiryFromToken(idToken));
        return this.syncUserWithBackend$(idToken).pipe(map(() => idToken));
      }),
    );
  }

  /**
   * Asks Google Identity Services for an ID token.
   * `silent` renews in the background: Google signs the user in without
   * interaction when it can (`auto_select`), and the attempt fails fast
   * (instead of leaving a prompt on screen) when it cannot.
   */
  private promptForIdentityPlatformToken$(silent = false): Observable<string> {
    const GOOGLE_CLIENT_ID = environment.GOOGLE_CLIENT_ID;

    return new Observable<string>(observer => {
      const gisId = typeof google !== 'undefined' ? google?.accounts?.id : null;
      if (!gisId) {
        observer.error(
          new Error(
            'Google Identity Services script not loaded. Add it to index.html',
          ),
        );
        return;
      }

      const silentHints = silent
        ? extractSessionHints(this.session.token)
        : null;
      if (silent && !silentHints) {
        observer.error(
          new Error(
            'Silent sign-in renewal failed: missing account hint for stored session',
          ),
        );
        return;
      }

      let settled = false;
      const settle = (action: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        action();
      };
      const failSilently = (reason: string, blockBufferPrompt = false) =>
        settle(() => {
          if (blockBufferPrompt) {
            this.promptBlockedToken = this.session.token;
          }
          this.cancelGooglePrompt();
          observer.error(new Error(`Silent sign-in renewal failed: ${reason}`));
        });

      const timeout = setTimeout(
        () => {
          if (silent) {
            failSilently('timed out', true);
            return;
          }
          settle(() =>
            observer.error(
              new Error(
                'Login timed out or third party sign-in may be disabled. Please try again and enable third party sign-in by clicking on the information button at the top left side of the browser.',
              ),
            ),
          );
        },
        silent ? SILENT_PROMPT_TIMEOUT_MS : LOGIN_PROMPT_TIMEOUT_MS,
      );

      try {
        gisId.initialize({
          client_id: GOOGLE_CLIENT_ID,
          auto_select: silent,
          use_fedcm_for_prompt: true,
          ...(silentHints ?? {}),
          callback: (response: GisCredentialResponse) => {
            const idToken = response?.credential;
            settle(() => {
              if (idToken) {
                observer.next(idToken);
                observer.complete();
              } else {
                observer.error(
                  new Error(
                    'Google Sign-In response did not contain a credential.',
                  ),
                );
              }
            });
          },
        });

        if (silent) {
          // Fail fast when Google will not sign the user in without a click.
          gisId.prompt((notification: GisPromptMomentNotification) => {
            if (notification?.isNotDisplayed?.()) {
              failSilently('prompt not displayed', true);
            } else if (notification?.isSkippedMoment?.()) {
              failSilently('prompt skipped', true);
            } else if (
              notification?.isDismissedMoment?.() &&
              notification?.getDismissedReason?.() !== 'credential_returned'
            ) {
              failSilently('prompt dismissed', true);
            }
          });
        } else {
          gisId.prompt();
        }
      } catch (error) {
        settle(() => {
          console.error(
            'Error during Google Identity Platform sign-in initialization:',
            error,
          );
          observer.error(error);
        });
      }

      return () => clearTimeout(timeout);
    });
  }

  /**
   * Returns a valid Identity Platform token without stalling in-buffer callers:
   * - No session: completes empty (and redirects to login), as before.
   * - Valid outside buffer: emits the cached token.
   * - Valid inside the 5-min buffer: emits the still-valid token immediately
   *   and triggers single-flight background renewal (subject to cooldown).
   * - Expired: renews (or fails fast when hidden, offline, or cooling down).
   */
  getValidIdentityPlatformToken$(): Observable<string> {
    if (!this.isBrowser) {
      return of();
    }

    this.session.syncFromStorage();
    if (!this.session.hasSession()) {
      this.navigateToLoginIfNeeded();
      return of();
    }

    const now = Date.now();
    if (this.session.isValid(now)) {
      const validToken = this.firebaseIdToken!;
      if (this.session.needsRenewal(now)) {
        this.renewInBackground('request');
      }
      return of(validToken);
    }

    if (!this.inFlightRenewal$) {
      if (this.isHidden() || this.isOffline()) {
        return throwError(
          () => new Error('Session renewal deferred while hidden or offline.'),
        );
      }
      if (this.isInFailureCooldown(now)) {
        return throwError(
          () =>
            new Error('Session renewal is in cooldown after recent failure.'),
        );
      }
    }

    return this.renewSession$();
  }

  /**
   * Used by AuthInterceptor when the server rejects `rejectedToken` with 401
   * (e.g. slow client clock). Reuses a newer token if another call/tab already
   * refreshed, otherwise forces one single-flight renewal.
   */
  renewAfterUnauthorized$(rejectedToken: string): Observable<string> {
    if (!this.isBrowser) {
      return throwError(() => new Error('Not running in browser.'));
    }
    this.session.syncFromStorage();
    if (!this.session.hasSession()) {
      return throwError(() => new Error('No active session to renew.'));
    }
    const current = this.session.token;
    if (current && current !== rejectedToken && this.session.isValid()) {
      return of(current);
    }
    if (!this.inFlightRenewal$) {
      if (this.isHidden() || this.isOffline()) {
        return throwError(
          () => new Error('Session renewal deferred while hidden or offline.'),
        );
      }
      if (this.isInFailureCooldown()) {
        return throwError(
          () =>
            new Error('Session renewal is in cooldown after recent failure.'),
        );
      }
    }
    return this.renewSession$(rejectedToken);
  }

  /**
   * Renews the session once per tab at a time (concurrent callers share the
   * same attempt) and once across tabs (Web Locks + storage re-check).
   */
  renewSession$(rejectedToken?: string): Observable<string> {
    if (!this.inFlightRenewal$) {
      const generation = this.sessionGeneration;
      this.inFlightRenewal$ = defer(() =>
        this.performRenewal(rejectedToken),
      ).pipe(
        finalize(() => {
          this.inFlightRenewal$ = null;
        }),
        shareReplay({bufferSize: 1, refCount: false}),
      );
      // Hand the fresh token to the backend after it is saved and emitted.
      this.inFlightRenewal$.subscribe({
        next: result => {
          if (result.renewedHere) {
            setTimeout(() => this.handOffTokenToBackend(result.token));
          }
          if (this.pendingNavigationUrl && this.session.isValid()) {
            const url = this.pendingNavigationUrl;
            this.pendingNavigationUrl = null;
            this.ngZone.run(() => {
              void this.router.navigateByUrl(url);
            });
          }
        },
        error: () => {
          if (generation === this.sessionGeneration) {
            this.lastFailedRenewalAt = Date.now();
          }
        },
      });
    }
    return this.inFlightRenewal$.pipe(map(result => result.token));
  }

  private async performRenewal(rejectedToken?: string): Promise<RenewalResult> {
    const generation = this.sessionGeneration;
    const previousToken = this.session.token;

    const saveIfStillSignedIn = (token: string) => {
      this.session.syncFromStorage();
      if (
        generation !== this.sessionGeneration ||
        (this.isBrowser && !this.session.hasSession())
      ) {
        throw new Error('Signed out during session renewal.');
      }
      if (!isSameSessionAccount(previousToken, token)) {
        this.onSessionRenewalFailed();
        throw new AccountMismatchError();
      }
      this.saveFreshSession(token, this.expiryFromToken(token));
    };

    if (environment.isLocal) {
      // Wait for Firebase to restore the user after a reload or wake-up.
      await this.auth.authStateReady();
      const user = this.auth.currentUser;
      if (!user) {
        throw new Error('Firebase session is no longer available.');
      }
      const token = await user.getIdToken(true);
      saveIfStillSignedIn(token);
      return {token, renewedHere: true};
    }

    const renew = async (): Promise<RenewalResult> => {
      const adopted = this.freshTokenFromOtherTab(rejectedToken);
      if (adopted) return {token: adopted, renewedHere: false};
      try {
        const token = await firstValueFrom(
          this.promptForIdentityPlatformToken$(true),
        );
        saveIfStillSignedIn(token);
        return {token, renewedHere: true};
      } catch (error) {
        const lateAdopted = this.freshTokenFromOtherTab(rejectedToken);
        if (lateAdopted) return {token: lateAdopted, renewedHere: false};
        throw error;
      }
    };

    return this.runWithRenewLock(renew);
  }

  private async runWithRenewLock<T>(fn: () => Promise<T>): Promise<T> {
    const locks = typeof navigator !== 'undefined' ? navigator.locks : null;
    if (!locks?.request) return fn();

    let lockAcquired = false;
    const controller = new AbortController();
    const timer = this.ngZone.runOutsideAngular(() =>
      setTimeout(() => controller.abort(), LOCK_WAIT_TIMEOUT_MS),
    );
    try {
      return await locks.request(
        RENEW_LOCK_NAME,
        {signal: controller.signal},
        () => {
          lockAcquired = true;
          clearTimeout(timer);
          return fn();
        },
      );
    } catch (error) {
      if (!lockAcquired && controller.signal.aborted) {
        return fn();
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  /** Re-reads storage; returns the token if another tab already renewed. */
  private freshTokenFromOtherTab(rejectedToken?: string): string | null {
    this.session.syncFromStorage();
    const token = this.session.token;
    if (!token || token === rejectedToken) return null;
    if (rejectedToken) {
      return this.session.isValid() ? token : null;
    }
    return !this.session.needsRenewal() ? token : null;
  }

  /** Lets the backend store the fresh token for queued workflows/agent runs. */
  private handOffTokenToBackend(token: string): void {
    this.syncUserWithBackend$(token).subscribe({
      error: error =>
        console.warn(
          'Could not share the renewed session with the server.',
          error,
        ),
    });
  }

  /** Timer / wake / reconnect / in-buffer request trigger. */
  private renewInBackground(trigger: RenewTrigger | 'request'): void {
    if (trigger === 'online') {
      this.lastFailedRenewalAt = null;
      this.promptBlockedToken = null;
    } else if (trigger === 'wake' && !this.session.isValid()) {
      this.lastFailedRenewalAt = null;
    }

    if (!this.session.needsRenewal()) return;
    if (this.isHidden() || this.isOffline()) return;
    const now = Date.now();
    if (!this.inFlightRenewal$) {
      if (this.isInFailureCooldown(now)) {
        if (this.lastFailedRenewalAt !== null) {
          this.session.scheduleRenewal(
            Math.max(1, RENEW_RETRY_MS - (now - this.lastFailedRenewalAt)),
          );
        }
        return;
      }
      if (
        this.session.isValid(now) &&
        this.promptBlockedToken !== null &&
        this.promptBlockedToken === this.session.token
      ) {
        return;
      }
    }

    this.renewSession$().subscribe({
      error: error => {
        if (error instanceof AccountMismatchError || !this.session.isValid()) {
          this.onSessionRenewalFailed();
          return;
        }
        console.warn('Session renewal failed; retrying shortly.', error);
        const expiry = this.session.expiry;
        const delay =
          this.promptBlockedToken === this.session.token && expiry !== null
            ? Math.max(RENEW_RETRY_MS, expiry - Date.now() + 1000)
            : RENEW_RETRY_MS;
        this.session.scheduleRenewal(delay);
      },
    });
  }

  /**
   * Called when an expired session could not be renewed. Idempotent once the
   * session is cleared. Hidden tabs and offline browsers keep the session and
   * remember `targetUrl` to finish navigating on wake/reconnect; otherwise the
   * user sees a single session-expired notice and is sent to login with returnUrl.
   */
  onSessionRenewalFailed(targetUrl?: string): void {
    if (!this.isBrowser || !this.session.hasSession()) return;
    const candidateUrl = sanitizeReturnUrl(
      targetUrl ?? this.pendingNavigationUrl ?? this.router?.url,
    );
    if (this.isHidden() || this.isOffline()) {
      if (candidateUrl) {
        this.pendingNavigationUrl = candidateUrl;
      }
      return;
    }
    this.pendingNavigationUrl = null;
    this.notificationService?.show(
      SESSION_EXPIRED_MESSAGE,
      'info',
      undefined,
      'info',
      SESSION_EXPIRED_DURATION_MS,
    );
    void this.expireSession(LOGIN_ROUTE, candidateUrl);
  }

  redirectToLogin(returnUrl?: string | null): void {
    const safeReturnUrl = sanitizeReturnUrl(returnUrl);
    if (safeReturnUrl && safeReturnUrl !== '/') {
      void this.router.navigate([LOGIN_ROUTE], {
        queryParams: {returnUrl: safeReturnUrl},
      });
      return;
    }
    void this.router.navigate([LOGIN_ROUTE]);
  }

  private syncUserWithBackend$(token: string): Observable<UserModel> {
    return defer(() => {
      const generation = this.sessionGeneration;
      const headers = new HttpHeaders().set('Authorization', `Bearer ${token}`);
      return this.httpClient
        .get<UserModel>(`${environment.backendURL}/users/me`, {headers})
        .pipe(
          tap((userDetails: UserModel) => {
            if (
              generation === this.sessionGeneration &&
              (!this.isBrowser || this.session.hasSession())
            ) {
              localStorage.setItem(USER_DETAILS, JSON.stringify(userDetails));
            }
          }),
          catchError((error: HttpErrorResponse) => {
            console.error('Failed to sync user with backend', error);
            return throwError(
              () =>
                new Error(
                  error?.error?.detail ||
                    `Could not synchronize user profile with the server. ${error?.error?.detail}`,
                ),
            );
          }),
        );
    });
  }

  /**
   * User-initiated sign-out: also turns off Google auto sign-in so the next
   * visit shows the login page. Does not touch queued workflows on the server.
   */
  async logout(route: string = LOGIN_ROUTE) {
    this.disableGoogleAutoSelect();
    return this.endSession(route);
  }

  /** Automatic sign-out after a failed renewal; keeps silent sign-in enabled. */
  async expireSession(route: string = LOGIN_ROUTE, returnUrl?: string | null) {
    return this.endSession(route, returnUrl);
  }

  private async endSession(
    route: string,
    returnUrl?: string | null,
  ): Promise<void> {
    this.sessionGeneration++; // Any renewal still in flight must not save.
    this.lastFailedRenewalAt = null;
    this.promptBlockedToken = null;
    this.pendingNavigationUrl = null;
    this.cancelGooglePrompt();
    this.currentOAuthAccessToken = null; // Clear stored token on logout
    this.session.clear(); // Removal also signs out other open tabs.
    if (this.isBrowser) {
      localStorage.removeItem(USER_DETAILS);
      localStorage.removeItem('showTooltip');
    }
    try {
      if (typeof this.auth?.signOut === 'function') {
        await this.auth.signOut();
      }
    } catch (e) {
      console.error('Sign Out Error', e);
    }
    const safeReturnUrl = sanitizeReturnUrl(returnUrl);
    if (route === LOGIN_ROUTE && safeReturnUrl && safeReturnUrl !== '/') {
      this.redirectToLogin(safeReturnUrl);
    } else {
      void this.router.navigateByUrl(route);
    }
  }

  private saveFreshSession(token: string, expiry: number): void {
    this.lastFailedRenewalAt = null;
    this.promptBlockedToken = null;
    this.session.save(token, expiry);
    if (this.session.needsRenewal()) {
      this.session.scheduleRenewal(RENEW_RETRY_MS);
    }
  }

  private isHidden(): boolean {
    return (
      typeof document !== 'undefined' && document.visibilityState === 'hidden'
    );
  }

  private isOffline(): boolean {
    return typeof navigator !== 'undefined' && !navigator.onLine;
  }

  private isInFailureCooldown(now = Date.now()): boolean {
    return (
      this.lastFailedRenewalAt !== null &&
      now - this.lastFailedRenewalAt < RENEW_RETRY_MS
    );
  }

  private disableGoogleAutoSelect(): void {
    if (typeof google !== 'undefined') {
      google?.accounts?.id?.disableAutoSelect?.();
    }
  }

  private cancelGooglePrompt(): void {
    if (typeof google !== 'undefined') {
      google?.accounts?.id?.cancel?.();
    }
  }

  private navigateToLoginIfNeeded(): void {
    if (
      this.router?.url &&
      this.router.url !== LOGIN_ROUTE &&
      !this.router.url.startsWith(`${LOGIN_ROUTE}?`)
    ) {
      void this.router.navigate([LOGIN_ROUTE]);
    }
  }

  /**
   * True when the current token is still valid. Guards own redirecting
   * unauthenticated navigations; cross-tab sign-out is handled in syncFromStorage.
   */
  isLoggedIn(): boolean {
    if (!this.isBrowser) return false;

    this.session.syncFromStorage();
    const valid = this.session.isValid();
    if (valid) {
      this.pendingNavigationUrl = null;
    }
    return valid;
  }

  /** True when a (possibly expired) session exists that can be renewed. */
  hasRenewableSession(): boolean {
    return this.isBrowser && this.session.hasSession();
  }

  isUserLoggedIn() {
    if (!this.isBrowser) return false;

    return localStorage.getItem(SESSION_STORAGE_KEY) !== null;
  }

  isUserAdmin() {
    if (!this.isBrowser) return false;

    const user_role = this.userService.getUserDetails()?.roles;
    return user_role?.includes(UserRolesEnum.ADMIN) || false;
  }

  isUserWorkflows() {
    if (!this.isBrowser) return false;

    const user_role = this.userService.getUserDetails()?.roles;
    return user_role?.includes(UserRolesEnum.WORKFLOWS) || false;
  }

  getToken() {
    return this.firebaseIdToken;
  }

  setOAuthAccessToken(token: string | null): void {
    this.currentOAuthAccessToken = token;
  }

  getOAuthAccessToken(): string | null {
    return this.currentOAuthAccessToken;
  }

  /**
   * Retrieves the currently stored access token.
   */
  getAccessToken(): string | null {
    // Note: OAuth access tokens expire after 1 hour and are not renewed here.
    return this.currentOAuthAccessToken;
  }

  private expiryFromToken(token: string): number {
    return resolveSessionExpiry(token);
  }

  decodeJwtPayload(token: string): GoogleIdTokenPayload {
    return decodeGoogleJwtPayload(token);
  }
}
