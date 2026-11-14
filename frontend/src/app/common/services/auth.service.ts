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
import {
  Observable,
  Subscription,
  defer,
  firstValueFrom,
  from,
  throwError,
  of,
} from 'rxjs';
import {
  catchError,
  finalize,
  shareReplay,
  tap,
  map,
  switchMap,
  timeout,
} from 'rxjs/operators';
import {isPlatformBrowser} from '@angular/common';
import {
  AuthSessionStore,
  RENEW_RETRY_MS,
  RenewTrigger,
  StoredSession,
} from './auth-session.store';
import {
  AccountMismatchError,
  GoogleIdTokenPayload,
  SessionSupersededError,
  attachFailedSessionToken,
  decodeGoogleJwtPayload,
  getFailedSessionToken,
  isLoginPath,
  isSameSessionAccount,
  resolveSessionExpiry,
  sanitizeReturnUrl,
} from './auth-token.utils';
import {GisClientAdapter} from './gis-client';

const USER_DETAILS = 'USER_DETAILS';
const LOGIN_ROUTE = '/login';
const RENEW_LOCK_NAME = 'cs-session-renew';
const LOCK_WAIT_TIMEOUT_MS = 5000;
const ACCOUNT_SWITCH_SYNC_TIMEOUT_MS = 1500;
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
  private readonly gisClient = new GisClientAdapter(this.isBrowser, fn =>
    this.ngZone.runOutsideAngular(fn),
  );

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
          this.inFlightRenewal$ = null;
          this.lastFailedRenewalAt = null;
          this.promptBlockedToken = null;
          this.pendingNavigationUrl = null;
          this.switchingAccount = false;
          this.accountSwitchSub?.unsubscribe();
          this.accountSwitchSub = null;
          this.gisClient.abortActivePrompt();
          this.navigateToLoginIfNeeded();
        }),
      onAccountSwitchedElsewhere: incoming =>
        this.ngZone.run(() => this.handleAccountSwitchedElsewhere(incoming)),
    },
    fn => this.ngZone.runOutsideAngular(fn),
  );
  private inFlightRenewal$: Observable<RenewalResult> | null = null;
  /** Bumped on every sign-out so an in-flight renewal cannot revive it. */
  private sessionGeneration = 0;
  private lastFailedRenewalAt: number | null = null;
  private promptBlockedToken: string | null = null;
  private pendingNavigationUrl: string | null = null;
  private switchingAccount = false;
  private accountSwitchSub: Subscription | null = null;

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
    this.inFlightRenewal$ = null;
    this.switchingAccount = false;
    this.accountSwitchSub?.unsubscribe();
    this.accountSwitchSub = null;
    this.gisClient.abortActivePrompt();
    this.session.destroy();
  }

  private get firebaseIdToken(): string | null {
    return this.session.token;
  }

  /**
   * Local development sign-in method to get a Firebase ID token.
   */
  signInWithGoogleFirebase(): Observable<string> {
    return defer(() => {
      this.sessionGeneration++;
      this.inFlightRenewal$ = null;
      this.gisClient.abortActivePrompt();
      return from(signInWithPopup(this.auth, this.provider));
    }).pipe(
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
        return this.completeInteractiveSignIn$(token, expiry);
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
    return defer(() => {
      this.sessionGeneration++;
      this.inFlightRenewal$ = null;
      return this.gisClient.prompt$({
        clientId: environment.GOOGLE_CLIENT_ID,
        silent: false,
      });
    }).pipe(
      switchMap(idToken =>
        this.completeInteractiveSignIn$(idToken, this.expiryFromToken(idToken)),
      ),
    );
  }

  /**
   * Renders Google's standard Sign-In button across `containers` (used when
   * One Tap / FedCM prompt is suppressed) and emits each synced Google ID token.
   */
  renderGoogleSignInButton$(
    containers: readonly HTMLElement[],
    onCredentialStart?: () => void,
  ): Observable<string> {
    return defer(() => {
      this.sessionGeneration++;
      this.inFlightRenewal$ = null;
      return this.gisClient.renderButtons$(
        containers,
        environment.GOOGLE_CLIENT_ID,
      );
    }).pipe(
      switchMap(idToken => {
        onCredentialStart?.();
        return this.completeInteractiveSignIn$(
          idToken,
          this.expiryFromToken(idToken),
        );
      }),
    );
  }

  private completeInteractiveSignIn$(
    token: string,
    expiry: number,
  ): Observable<string> {
    this.saveFreshSession(token, expiry);
    return this.syncUserWithBackend$(token).pipe(
      map(() => token),
      catchError(error => {
        if (this.session.token === token) {
          this.session.clear();
        }
        return throwError(() => error);
      }),
    );
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
    if (!this.isBrowser || this.switchingAccount) {
      return of();
    }

    this.session.syncFromStorage();
    if (this.switchingAccount) {
      return of();
    }
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
      const expiredToken = this.session.token;
      if (this.isHidden() || this.isOffline()) {
        return throwError(() =>
          attachFailedSessionToken(
            new Error('Session renewal deferred while hidden or offline.'),
            expiredToken,
          ),
        );
      }
      if (this.isInFailureCooldown(now)) {
        return throwError(() =>
          attachFailedSessionToken(
            new Error('Session renewal is in cooldown after recent failure.'),
            expiredToken,
          ),
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
      return throwError(() =>
        attachFailedSessionToken(
          new Error('Not running in browser.'),
          rejectedToken,
        ),
      );
    }
    if (this.switchingAccount) {
      return throwError(
        () =>
          new SessionSupersededError(
            'Session account switch in progress.',
            rejectedToken,
          ),
      );
    }
    this.session.syncFromStorage();
    if (this.switchingAccount) {
      return throwError(
        () =>
          new SessionSupersededError(
            'Session account switch in progress.',
            rejectedToken,
          ),
      );
    }
    if (!this.session.hasSession()) {
      return throwError(() =>
        attachFailedSessionToken(
          new Error('No active session to renew.'),
          rejectedToken,
        ),
      );
    }
    const current = this.session.token;
    if (current && !isSameSessionAccount(rejectedToken, current)) {
      return throwError(
        () =>
          new SessionSupersededError(
            'Session belongs to a different account.',
            rejectedToken,
          ),
      );
    }
    if (current && current !== rejectedToken && this.session.isValid()) {
      return of(current);
    }
    if (!this.inFlightRenewal$) {
      if (this.isHidden() || this.isOffline()) {
        return throwError(() =>
          attachFailedSessionToken(
            new Error('Session renewal deferred while hidden or offline.'),
            rejectedToken,
          ),
        );
      }
      if (this.isInFailureCooldown()) {
        return throwError(() =>
          attachFailedSessionToken(
            new Error('Session renewal is in cooldown after recent failure.'),
            rejectedToken,
          ),
        );
      }
    }
    return this.renewSession$(rejectedToken).pipe(
      catchError(err =>
        throwError(() => attachFailedSessionToken(err, rejectedToken)),
      ),
    );
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
          if (
            result.renewedHere &&
            generation === this.sessionGeneration &&
            this.session.token === result.token
          ) {
            const expectedToken = result.token;
            setTimeout(() => {
              if (
                generation === this.sessionGeneration &&
                this.session.token === expectedToken
              ) {
                this.handOffTokenToBackend(expectedToken);
              }
            });
          }
          if (
            generation === this.sessionGeneration &&
            this.pendingNavigationUrl &&
            this.session.isValid()
          ) {
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

    const ensureActiveSameSession = () => {
      if (
        generation !== this.sessionGeneration ||
        this.switchingAccount ||
        (this.isBrowser && !this.session.hasSession())
      ) {
        throw new SessionSupersededError(
          'Signed out or switched account during session renewal.',
          previousToken,
        );
      }
    };

    const saveIfStillSignedIn = (token: string) => {
      this.session.syncFromStorage();
      ensureActiveSameSession();
      if (!isSameSessionAccount(previousToken, token)) {
        this.onSessionRenewalFailed();
        throw new AccountMismatchError();
      }
      this.saveFreshSession(token, this.expiryFromToken(token));
    };

    if (environment.isLocal) {
      try {
        // Wait for Firebase to restore the user after a reload or wake-up.
        await this.auth.authStateReady();
        ensureActiveSameSession();
        const user = this.auth.currentUser;
        if (!user) {
          throw new Error('Firebase session is no longer available.');
        }
        const token = await user.getIdToken(true);
        saveIfStillSignedIn(token);
        return {token, renewedHere: true};
      } catch (error) {
        if (
          !(error instanceof AccountMismatchError) &&
          !(error instanceof SessionSupersededError)
        ) {
          if (
            generation !== this.sessionGeneration ||
            this.switchingAccount ||
            (this.isBrowser && !this.session.hasSession())
          ) {
            throw new SessionSupersededError(
              'Signed out or switched account during session renewal.',
              previousToken,
            );
          }
          throw attachFailedSessionToken(error, previousToken);
        }
        throw error;
      }
    }

    const renew = async (): Promise<RenewalResult> => {
      ensureActiveSameSession();
      const adopted = this.freshTokenFromOtherTab(previousToken, rejectedToken);
      if (adopted) return {token: adopted, renewedHere: false};
      try {
        const token = await firstValueFrom(
          this.gisClient.prompt$({
            clientId: environment.GOOGLE_CLIENT_ID,
            silent: true,
            startingToken: previousToken,
            onBlockToken: blockedToken => {
              if (
                generation === this.sessionGeneration &&
                this.session.token === blockedToken
              ) {
                this.promptBlockedToken = blockedToken;
              }
            },
          }),
        );
        saveIfStillSignedIn(token);
        return {token, renewedHere: true};
      } catch (error) {
        if (
          generation === this.sessionGeneration &&
          !this.switchingAccount &&
          this.session.hasSession()
        ) {
          const lateAdopted = this.freshTokenFromOtherTab(
            previousToken,
            rejectedToken,
          );
          if (lateAdopted) return {token: lateAdopted, renewedHere: false};
        }
        if (
          !(error instanceof AccountMismatchError) &&
          !(error instanceof SessionSupersededError)
        ) {
          if (
            generation !== this.sessionGeneration ||
            this.switchingAccount ||
            (this.isBrowser && !this.session.hasSession())
          ) {
            throw new SessionSupersededError(
              'Signed out or switched account during session renewal.',
              previousToken,
            );
          }
          throw attachFailedSessionToken(error, previousToken);
        }
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
  private freshTokenFromOtherTab(
    previousToken: string | null,
    rejectedToken?: string,
  ): string | null {
    this.session.syncFromStorage();
    const token = this.session.token;
    if (!token || token === rejectedToken) return null;
    if (!isSameSessionAccount(previousToken, token)) return null;
    if (rejectedToken) {
      return this.session.isValid() ? token : null;
    }
    return !this.session.needsRenewal() ? token : null;
  }

  /** Lets the backend store the fresh token for queued workflows. */
  private handOffTokenToBackend(token: string): void {
    this.syncUserWithBackend$(token).subscribe({
      error: error =>
        console.warn(
          'Could not share the renewed session with the server.',
          error,
        ),
    });
  }

  private getPromptBlockedDelayMs(now: number): number {
    if (
      this.session.isValid(now) &&
      this.promptBlockedToken !== null &&
      this.promptBlockedToken === this.session.token &&
      this.session.expiry !== null
    ) {
      return Math.max(1, this.session.expiry - now + 1000);
    }
    return 0;
  }

  /** Timer / wake / reconnect / in-buffer request trigger. */
  private renewInBackground(trigger: RenewTrigger | 'request'): void {
    if (this.switchingAccount) return;
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
            Math.max(
              1,
              RENEW_RETRY_MS - (now - this.lastFailedRenewalAt),
              this.getPromptBlockedDelayMs(now),
            ),
          );
        }
        return;
      }
      if (
        this.session.isValid(now) &&
        this.promptBlockedToken !== null &&
        this.promptBlockedToken === this.session.token
      ) {
        this.session.scheduleRenewal(this.getPromptBlockedDelayMs(now));
        return;
      }
    }

    this.renewSession$().subscribe({
      error: error => {
        if (error instanceof SessionSupersededError) {
          return;
        }
        if (error instanceof AccountMismatchError || !this.session.isValid()) {
          this.onSessionRenewalFailed(undefined, error);
          return;
        }
        console.warn('Session renewal failed; retrying shortly.', error);
        const delay = Math.max(
          RENEW_RETRY_MS,
          this.getPromptBlockedDelayMs(Date.now()),
        );
        this.session.scheduleRenewal(delay);
      },
    });
  }

  /**
   * Called when an expired session could not be renewed. Idempotent once the
   * session is cleared or superseded by another account/newer valid token.
   * Hidden tabs and offline browsers keep the session and remember `targetUrl`
   * to finish navigating on wake/reconnect; otherwise the user sees a single
   * session-expired notice and is sent to login with returnUrl.
   */
  onSessionRenewalFailed(
    targetUrl?: string,
    errorOrFailedToken?: unknown,
  ): void {
    if (errorOrFailedToken instanceof SessionSupersededError) {
      return;
    }
    if (!this.isBrowser) return;

    this.session.syncFromStorage();
    if (this.switchingAccount || !this.session.hasSession()) {
      return;
    }

    const failedToken =
      typeof errorOrFailedToken === 'string'
        ? errorOrFailedToken
        : getFailedSessionToken(errorOrFailedToken);
    const currentToken = this.session.token;
    if (
      !(errorOrFailedToken instanceof AccountMismatchError) &&
      failedToken &&
      currentToken &&
      currentToken !== failedToken &&
      (!isSameSessionAccount(failedToken, currentToken) ||
        this.session.isValid())
    ) {
      return;
    }

    const candidateUrl = sanitizeReturnUrl(
      this.resolveActiveTargetUrl(targetUrl),
    );
    if (this.isHidden() || this.isOffline()) {
      if (candidateUrl) {
        this.pendingNavigationUrl = candidateUrl;
      }
      return;
    }
    this.pendingNavigationUrl = null;
    this.ngZone.run(() => {
      this.notificationService?.show(
        SESSION_EXPIRED_MESSAGE,
        'info',
        undefined,
        'info',
        SESSION_EXPIRED_DURATION_MS,
      );
      void this.expireSession(LOGIN_ROUTE, candidateUrl);
    });
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
              (!this.isBrowser || this.session.token === token)
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
    this.gisClient.disableAutoSelect();
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
    this.inFlightRenewal$ = null;
    this.lastFailedRenewalAt = null;
    this.promptBlockedToken = null;
    this.pendingNavigationUrl = null;
    this.switchingAccount = false;
    this.accountSwitchSub?.unsubscribe();
    this.accountSwitchSub = null;
    this.gisClient.abortActivePrompt();
    this.currentOAuthAccessToken = null; // Clear stored token on logout
    this.session.clear(); // Removal also signs out other open tabs.
    if (this.isBrowser) {
      localStorage.removeItem(USER_DETAILS);
      localStorage.removeItem('showTooltip');
    }
    const safeReturnUrl = sanitizeReturnUrl(returnUrl);
    this.ngZone.run(() => {
      if (route === LOGIN_ROUTE && safeReturnUrl && safeReturnUrl !== '/') {
        this.redirectToLogin(safeReturnUrl);
      } else {
        void this.router.navigateByUrl(route);
      }
    });
    try {
      if (typeof this.auth?.signOut === 'function') {
        await this.auth.signOut();
      }
    } catch (e) {
      console.error('Sign Out Error', e);
    }
  }

  protected reloadToHome(): void {
    if (this.isBrowser) {
      window.location.assign('/');
    }
  }

  private handleAccountSwitchedElsewhere(incoming: StoredSession): void {
    this.switchingAccount = true;
    const generation = ++this.sessionGeneration;
    this.inFlightRenewal$ = null;
    this.lastFailedRenewalAt = null;
    this.promptBlockedToken = null;
    this.pendingNavigationUrl = null;
    this.accountSwitchSub?.unsubscribe();
    this.accountSwitchSub = null;
    this.gisClient.abortActivePrompt();

    this.accountSwitchSub = this.syncUserWithBackend$(incoming.token)
      .pipe(timeout(ACCOUNT_SWITCH_SYNC_TIMEOUT_MS))
      .subscribe({
        next: () => {
          if (generation !== this.sessionGeneration) return;
          this.switchingAccount = false;
          this.accountSwitchSub = null;
          this.reloadToHome();
        },
        error: () => {
          if (generation !== this.sessionGeneration) return;
          this.purgeStaleUserDetailsIfMismatch(incoming.token);
          this.switchingAccount = false;
          this.accountSwitchSub = null;
          this.reloadToHome();
        },
      });
  }

  private purgeStaleUserDetailsIfMismatch(token: string): void {
    if (!this.isBrowser) return;
    const raw = localStorage.getItem(USER_DETAILS);
    if (!raw) return;

    let incomingEmail: string | null = null;
    try {
      const payload = decodeGoogleJwtPayload(token);
      incomingEmail =
        typeof payload.email === 'string' && payload.email.trim()
          ? payload.email.trim().toLowerCase()
          : null;
    } catch {
      incomingEmail = null;
    }

    let storedEmail: string | null = null;
    try {
      const parsed = JSON.parse(raw) as Partial<UserModel> | null;
      storedEmail =
        typeof parsed?.email === 'string' && parsed.email.trim()
          ? parsed.email.trim().toLowerCase()
          : null;
    } catch {
      storedEmail = null;
    }

    if (!incomingEmail || !storedEmail || storedEmail !== incomingEmail) {
      localStorage.removeItem(USER_DETAILS);
    }
  }

  private saveFreshSession(token: string, expiry: number): void {
    if (
      this.session.token &&
      !isSameSessionAccount(this.session.token, token)
    ) {
      this.sessionGeneration++;
    }
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

  private resolveActiveTargetUrl(explicitUrl?: string | null): string | null {
    if (explicitUrl) {
      return explicitUrl;
    }
    if (this.pendingNavigationUrl) {
      return this.pendingNavigationUrl;
    }
    const nav = this.router?.getCurrentNavigation?.();
    const navUrl = nav?.finalUrl?.toString() ?? nav?.extractedUrl?.toString();
    if (navUrl) {
      return navUrl;
    }
    if (this.router?.url && this.router.url !== '/') {
      return this.router.url;
    }
    return this.readBrowserLocationUrl() ?? this.router?.url ?? null;
  }

  private readBrowserLocationUrl(): string | null {
    if (!this.isBrowser || !(this.router instanceof Router)) {
      return null;
    }
    const pathname = window.location.pathname;
    if (
      !pathname ||
      pathname === '/context.html' ||
      pathname === '/debug.html'
    ) {
      return null;
    }
    return `${pathname}${window.location.search}${window.location.hash}`;
  }

  private navigateToLoginIfNeeded(): void {
    const activeUrl = this.resolveActiveTargetUrl();
    if (
      isLoginPath(activeUrl) ||
      (this.router instanceof Router &&
        this.isBrowser &&
        isLoginPath(window.location.pathname))
    ) {
      return;
    }
    this.redirectToLogin(activeUrl);
  }

  /**
   * True when the current token is still valid. Guards own redirecting
   * unauthenticated navigations; cross-tab sign-out is handled in syncFromStorage.
   */
  isLoggedIn(): boolean {
    if (!this.isBrowser || this.switchingAccount) return false;

    this.session.syncFromStorage();
    if (this.switchingAccount) return false;
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
    return this.isLoggedIn();
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
