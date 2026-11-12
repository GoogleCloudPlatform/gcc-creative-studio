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
import {Auth, IdTokenResult} from '@angular/fire/auth';
import {UserService} from '../services/user.service';
import {
  GoogleAuthProvider,
  signInWithPopup,
  UserCredential,
} from '@angular/fire/auth';
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
  SESSION_STORAGE_KEY,
} from './auth-session.store';

// Declare the 'google' global object from the Google Identity Services script
declare const google: any;

const USER_DETAILS = 'USER_DETAILS';
const LOGIN_ROUTE = '/login';
const RENEW_LOCK_NAME = 'cs-session-renew';
const LOGIN_PROMPT_TIMEOUT_MS = 15000;
const SILENT_PROMPT_TIMEOUT_MS = 10000;

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
  private platformId = inject(PLATFORM_ID);
  private readonly ngZone = inject(NgZone);
  private readonly provider: GoogleAuthProvider = new GoogleAuthProvider();
  private readonly isBrowser = isPlatformBrowser(this.platformId);

  // Store token temporarily in memory for the session
  private currentOAuthAccessToken: string | null = null;
  private readonly session = new AuthSessionStore(
    this.isBrowser,
    {
      onRenewNeeded: () => this.ngZone.run(() => this.renewInBackground()),
      onSignedOutElsewhere: () =>
        this.ngZone.run(() => {
          this.sessionGeneration++;
          this.cancelGooglePrompt();
          this.navigateToLoginIfNeeded();
        }),
    },
    fn => this.ngZone.runOutsideAngular(fn),
  );
  private inFlightRenewal$: Observable<RenewalResult> | null = null;
  /** Bumped on every sign-out so an in-flight renewal cannot revive it. */
  private sessionGeneration = 0;

  constructor(
    private router: Router,
    private httpClient: HttpClient,
    private userService: UserService,
  ) {
    this.provider.setCustomParameters({
      // Set custom params for the provider
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
   * A test sign-in method to get a Google ID token compatible with Firebase.
   *
   * @returns An Observable that emits the Firebase-compatible ID token.
   */
  signInWithGoogleFirebase(): Observable<string> {
    return from(signInWithPopup(this.auth, this.provider)).pipe(
      // Step 1: Get the Firebase ID token from the successful sign-in.
      switchMap((userCredential: UserCredential) => {
        if (!userCredential.user) {
          return throwError(
            () => new Error('Firebase user not found after sign-in.'),
          );
        }
        return from(userCredential.user.getIdTokenResult());
      }),
      // Step 2: Save the session and sync with the backend.
      switchMap((idTokenResult: IdTokenResult) => {
        const token = idTokenResult.token;
        this.session.save(token, Date.parse(idTokenResult.expirationTime));

        // Call the backend to get or create the user profile.
        return this.syncUserWithBackend$(token).pipe(
          map(() => token), // Pass the token along for the final result.
        );
      }),
      catchError((error: any) => {
        console.error('An error occurred during the sign-in process:', error);
        return throwError(
          () => new Error(`Sign-in failed. Please try again. ${error}`),
        );
      }),
    );
  }

  /**
   * Returns a valid Firebase token (local development sign-in path).
   */
  getValidFirebaseToken$(): Observable<string> {
    if (!this.isLoggedIn()) {
      return throwError(
        () => new Error('User session is not valid or has expired. 1'),
      );
    }

    const currentUser = this.auth.currentUser;
    if (currentUser) {
      return from(currentUser.getIdToken(true)).pipe(
        tap((token: string) => {
          try {
            this.session.save(token, this.expiryFromToken(token));
          } catch (error) {
            console.error('Error decoding refreshed token payload:', error);
          }
        }),
      );
    }
    return of(this.firebaseIdToken!);
  }

  /**
   * Sign-in with Google Identity Services, returning a Google ID token that
   * Cloud Run IAM and the backend accept.
   */
  signInForGoogleIdentityPlatform(): Observable<string> {
    return this.promptForIdentityPlatformToken$().pipe(
      switchMap(idToken => {
        this.session.save(idToken, this.expiryFromToken(idToken));

        // Call the backend to get or create the user profile.
        return this.syncUserWithBackend$(idToken).pipe(
          map(() => idToken), // Pass the token along for the final result.
        );
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
      if (typeof google === 'undefined') {
        observer.error(
          new Error(
            'Google Identity Services script not loaded. Add it to index.html',
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
      const failSilently = (reason: string) =>
        settle(() => {
          this.cancelGooglePrompt();
          observer.error(new Error(`Silent sign-in renewal failed: ${reason}`));
        });

      const timeout = setTimeout(
        () => {
          if (silent) {
            failSilently('timed out');
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
        const silentHints = silent ? this.hintsFromStoredSession() : {};
        google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          auto_select: silent,
          use_fedcm_for_prompt: true,
          ...silentHints,
          callback: (response: any) => {
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
          google.accounts.id.prompt((notification: any) => {
            if (notification?.isNotDisplayed?.()) {
              failSilently('prompt not displayed');
            } else if (notification?.isSkippedMoment?.()) {
              failSilently('prompt skipped');
            } else if (
              notification?.isDismissedMoment?.() &&
              notification?.getDismissedReason?.() !== 'credential_returned'
            ) {
              failSilently('prompt dismissed');
            }
          });
        } else {
          // Trigger the One Tap prompt.
          // Per new docs, we don't use the notification object for flow control.
          google.accounts.id.prompt();
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
   * Returns a valid Identity Platform token, renewing it silently when it is
   * within the renewal buffer or already expired.
   * - No session: completes empty (and redirects to login), as before.
   * - Inside the buffer: renews; falls back to the still-valid token.
   * - Expired: renews; errors if renewal fails.
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
    if (!this.session.needsRenewal(now)) {
      return of(this.firebaseIdToken!);
    }

    if (this.session.isValid(now)) {
      const stillValidToken = this.firebaseIdToken!;
      return this.renewSession$().pipe(
        catchError(error => {
          console.warn('Session renewal failed; retrying shortly.', error);
          this.session.scheduleRenewal(RENEW_RETRY_MS);
          return of(stillValidToken);
        }),
      );
    }

    return this.renewSession$();
  }

  /**
   * Renews the session once per tab at a time (concurrent callers share the
   * same attempt) and once across tabs (Web Locks + storage re-check).
   */
  renewSession$(): Observable<string> {
    if (!this.inFlightRenewal$) {
      this.inFlightRenewal$ = defer(() => this.performRenewal()).pipe(
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
        },
        error: () => undefined, // Callers handle the failure.
      });
    }
    return this.inFlightRenewal$.pipe(map(result => result.token));
  }

  private async performRenewal(): Promise<RenewalResult> {
    const generation = this.sessionGeneration;
    // A sign-out while we waited (here or in another tab) wins: never save.
    const saveIfStillSignedIn = (token: string) => {
      if (generation !== this.sessionGeneration) {
        throw new Error('Signed out during session renewal.');
      }
      this.session.save(token, this.expiryFromToken(token));
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
      const adopted = this.freshTokenFromOtherTab();
      if (adopted) return {token: adopted, renewedHere: false};
      try {
        const token = await firstValueFrom(
          this.promptForIdentityPlatformToken$(true),
        );
        saveIfStillSignedIn(token);
        return {token, renewedHere: true};
      } catch (error) {
        const lateAdopted = this.freshTokenFromOtherTab();
        if (lateAdopted) return {token: lateAdopted, renewedHere: false};
        throw error;
      }
    };

    const locks = typeof navigator !== 'undefined' ? navigator.locks : null;
    return locks ? locks.request(RENEW_LOCK_NAME, renew) : renew();
  }

  /** Re-reads storage; returns the token if another tab already renewed. */
  private freshTokenFromOtherTab(): string | null {
    this.session.syncFromStorage();
    return this.session.token && !this.session.needsRenewal()
      ? this.session.token
      : null;
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

  /** Timer / wake-up trigger: renew without blocking any request. */
  private renewInBackground(): void {
    if (!this.session.needsRenewal()) return;
    this.getValidIdentityPlatformToken$().subscribe({
      error: () => this.onSessionRenewalFailed(),
    });
  }

  /**
   * Called when a session could not be renewed. Hidden tabs and offline
   * browsers keep the session and retry on wake/reconnect; otherwise the user
   * is sent to the login page (without disabling silent sign-in).
   */
  onSessionRenewalFailed(): void {
    if (!this.isBrowser) return;
    const hidden =
      typeof document !== 'undefined' && document.visibilityState === 'hidden';
    if (hidden) {
      // The store's visibilitychange/focus listeners retry when it wakes up.
      return;
    }
    const offline = typeof navigator !== 'undefined' && !navigator.onLine;
    if (offline) {
      this.session.scheduleRenewal(RENEW_RETRY_MS);
      return;
    }
    void this.expireSession();
  }

  private syncUserWithBackend$(token: string): Observable<UserModel> {
    const headers = new HttpHeaders().set('Authorization', `Bearer ${token}`);
    return this.httpClient
      .get<UserModel>(`${environment.backendURL}/users/me`, {headers})
      .pipe(
        tap((userDetails: UserModel) => {
          // The backend is the source of truth. Save the returned profile to local storage.
          localStorage.setItem(USER_DETAILS, JSON.stringify(userDetails));
        }),
        catchError((error: HttpErrorResponse) => {
          console.error('Failed to sync user with backend', error);
          // This is a critical error, so we should propagate it.
          return throwError(
            () =>
              new Error(
                error?.error?.detail ||
                  `Could not synchronize user profile with the server. ${error?.error?.detail}`,
              ),
          );
        }),
      );
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
  async expireSession(route: string = LOGIN_ROUTE) {
    return this.endSession(route);
  }

  private async endSession(route: string): Promise<void> {
    this.sessionGeneration++; // Any renewal still in flight must not save.
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
    void this.router.navigateByUrl(route);
  }

  private disableGoogleAutoSelect(): void {
    if (typeof google !== 'undefined') {
      google.accounts?.id?.disableAutoSelect?.();
    }
  }

  private cancelGooglePrompt(): void {
    if (typeof google !== 'undefined') {
      google.accounts?.id?.cancel?.();
    }
  }

  private navigateToLoginIfNeeded(): void {
    if (this.router?.url && this.router.url !== LOGIN_ROUTE) {
      void this.router.navigate([LOGIN_ROUTE]);
    }
  }

  /**
   * True when the current token is still valid. An expired session that can
   * still be renewed does not redirect here; guards renew it first.
   */
  isLoggedIn() {
    if (!this.isBrowser) return false;

    this.session.syncFromStorage();
    const isTokenValid = this.session.isValid();
    if (!isTokenValid && !this.session.hasSession()) {
      this.navigateToLoginIfNeeded();
    }
    return isTokenValid;
  }

  /** True when a (possibly expired) session exists that can be renewed. */
  hasRenewableSession(): boolean {
    return this.isBrowser && this.session.hasSession();
  }

  isUserLoggedIn() {
    if (!this.isBrowser) return false;

    const isUserLoggedIn = localStorage.getItem(SESSION_STORAGE_KEY) !== null;
    return isUserLoggedIn;
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
    // Renamed from getAccessToken for clarity
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
    return this.decodeJwtPayload(token).exp * 1000;
  }

  /**
   * Passes `login_hint` and `hd` from the existing JWT to GIS/FedCM so Chrome
   * narrows multi-account profiles to the exact signed-in account.
   */
  private hintsFromStoredSession(): {login_hint?: string; hd?: string} {
    const token = this.session.token;
    if (!token) return {};
    try {
      const payload = this.decodeJwtPayload(token);
      const hints: {login_hint?: string; hd?: string} = {};
      if (typeof payload?.email === 'string' && payload.email) {
        hints.login_hint = payload.email;
      }
      if (typeof payload?.hd === 'string' && payload.hd) {
        hints.hd = payload.hd;
      }
      return hints;
    } catch {
      return {};
    }
  }

  decodeJwtPayload(token: string): any {
    const base64Url = token.split('.')[1];
    if (!base64Url) {
      throw new Error('Invalid JWT token');
    }
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64.padEnd(
      base64.length + ((4 - (base64.length % 4)) % 4),
      '=',
    );
    const binary = atob(padded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    // eslint-disable-next-line n/no-unsupported-features/node-builtins
    const decoded = new TextDecoder().decode(bytes);
    return JSON.parse(decoded);
  }
}
