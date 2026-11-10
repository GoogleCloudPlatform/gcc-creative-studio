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

import {Injectable, PLATFORM_ID, inject} from '@angular/core';
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
import {Observable, from, throwError, of, EMPTY} from 'rxjs';
import {catchError, tap, map, switchMap} from 'rxjs/operators';
import {isPlatformBrowser} from '@angular/common';

export const OIDC_NONCE_KEY = 'creative_studio_oidc_nonce';
const FIREBASE_SESSION_KEY = 'firebase_session';
const USER_DETAILS = 'USER_DETAILS';
const LOGIN_ROUTE = '/login';

interface FirebaseSession {
  token: string;
  expiry: number; // Expiration timestamp in milliseconds
}

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  private readonly auth: Auth = inject(Auth);
  private platformId = inject(PLATFORM_ID);
  private readonly provider: GoogleAuthProvider = new GoogleAuthProvider();

  // Store token temporarily in memory for the session
  private currentOAuthAccessToken: string | null = null;
  private firebaseIdToken: string | null = null; // To store the Firebase token for the test
  private firebaseTokenExpiry: number | null = null; // To store token expiration time (in ms)
  private pendingOidcHash = '';

  constructor(
    private router: Router,
    private httpClient: HttpClient,
    private userService: UserService,
  ) {
    this.provider.setCustomParameters({
      // Set custom params for the provider
      prompt: 'select_account',
    });
    this.loadSessionFromStorage();
    if (isPlatformBrowser(this.platformId)) {
      const hash = window.location.hash || '';
      if (hash && (hash.includes('id_token=') || hash.includes('error='))) {
        this.pendingOidcHash = hash;
      }
    }
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
        const expirationTime = Date.parse(idTokenResult.expirationTime);

        // Save session details to memory and local storage.
        this.firebaseIdToken = token;
        this.firebaseTokenExpiry = expirationTime;
        const session: FirebaseSession = {token, expiry: expirationTime};
        localStorage.setItem(FIREBASE_SESSION_KEY, JSON.stringify(session));

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
   * Asynchronously gets a valid Firebase token.
   * 1. Checks for a valid, non-expired token in memory/cache.
   * 2. If expired or missing, attempts a silent refresh.
   * 3. If silent refresh fails, it emits an error, signaling a required re-login.
   */
  getValidFirebaseToken$(): Observable<string> {
    // First, check our own session info which is loaded from localStorage.
    // This is synchronous and tells us if we have a valid, non-expired token.
    if (!this.isLoggedIn()) {
      return throwError(
        () => new Error('User session is not valid or has expired. 1'),
      );
    }

    // If we have a valid session, check if the Firebase Auth instance is ready.
    const currentUser = this.auth.currentUser;
    if (currentUser) {
      // Ideal case: Auth is ready, so we can force a token refresh to ensure it's fresh.
      return from(currentUser.getIdToken(true)).pipe(
        tap((token: string) => {
          try {
            // Update the in-memory cache and localStorage with the refreshed token info.
            const payload = this.decodeJwtPayload(token);
            const expiry = payload.exp * 1000;

            this.firebaseIdToken = token;
            this.firebaseTokenExpiry = expiry;

            const session: FirebaseSession = {token, expiry};
            localStorage.setItem(FIREBASE_SESSION_KEY, JSON.stringify(session));
          } catch (error) {
            console.error('Error decoding refreshed token payload:', error);
          }
        }),
      );
    }

    // Fallback case: The Firebase Auth instance is not yet initialized, but we
    // have a valid token from localStorage. We can use this for the current
    // request. The next request will likely hit the ideal case above.
    return of(this.firebaseIdToken!);
  }

  /**
   * Redirects browser to a given URL.
   * Separated as a method so unit tests can spy on it without page reloads.
   */
  redirectToUrl(url: string): void {
    if (isPlatformBrowser(this.platformId)) {
      window.location.assign(url);
    }
  }

  /**
   * Builds the standard Google OIDC redirect URL with select_account and nonce.
   */
  buildGoogleOidcRedirectUrl(): string {
    const clientId = environment.GOOGLE_CLIENT_ID;
    if (!clientId) {
      throw new Error('Google Client ID is not configured.');
    }

    const nonce = crypto.randomUUID();
    if (isPlatformBrowser(this.platformId)) {
      try {
        sessionStorage.setItem(OIDC_NONCE_KEY, nonce);
      } catch (e) {
        console.warn('Could not write OIDC nonce to sessionStorage:', e);
      }
      try {
        localStorage.setItem(OIDC_NONCE_KEY, nonce);
      } catch (e) {
        console.warn('Could not write OIDC nonce to localStorage:', e);
      }
    }

    const redirectUri = `${window.location.origin}${LOGIN_ROUTE}`;
    // eslint-disable-next-line n/no-unsupported-features/node-builtins
    const params = new URLSearchParams({
      client_id: clientId,
      redirect_uri: redirectUri,
      response_type: 'id_token',
      scope: 'openid email profile',
      prompt: 'select_account',
      nonce: nonce,
    });

    return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
  }

  /**
   * Initiates Google Sign-In via standard Google OIDC redirect.
   *
   * @returns An Observable that redirects the browser to accounts.google.com.
   */
  signInForGoogleIdentityPlatform(): Observable<string> {
    try {
      const authUrl = this.buildGoogleOidcRedirectUrl();
      this.redirectToUrl(authUrl);
      return EMPTY;
    } catch (error: any) {
      return throwError(() => error);
    }
  }

  hasPendingOidcRedirect(): boolean {
    return !!this.pendingOidcHash;
  }

  /**
   * Completes Google OIDC redirect flow by parsing the URL fragment,
   * validating the nonce, synchronizing with the backend, and cleaning the address bar.
   */
  completeGoogleOidcRedirect$(rawHash?: string): Observable<string> {
    const hash =
      rawHash !== undefined && rawHash !== ''
        ? rawHash
        : this.pendingOidcHash ||
          (isPlatformBrowser(this.platformId) ? window.location.hash : '');
    this.pendingOidcHash = '';

    const cleanHash = hash.startsWith('#') ? hash.substring(1) : hash;
    // eslint-disable-next-line n/no-unsupported-features/node-builtins
    const params = new URLSearchParams(cleanHash);

    // Scrub URL fragment immediately so tokens never linger in browser history
    if (isPlatformBrowser(this.platformId)) {
      window.history.replaceState(
        {},
        document.title,
        window.location.pathname + window.location.search,
      );
    }

    let expectedNonce: string | null = null;
    if (isPlatformBrowser(this.platformId)) {
      try {
        expectedNonce =
          sessionStorage.getItem(OIDC_NONCE_KEY) ||
          localStorage.getItem(OIDC_NONCE_KEY);
      } catch (e) {
        console.warn('Could not read OIDC nonce from storage:', e);
      }
      try {
        sessionStorage.removeItem(OIDC_NONCE_KEY);
        localStorage.removeItem(OIDC_NONCE_KEY);
      } catch (e) {
        console.warn('Could not clear OIDC nonce from storage:', e);
      }
    }

    const error = params.get('error');
    if (error) {
      const errorDescription =
        params.get('error_description') || error || 'Google Sign-In failed.';
      return throwError(() => new Error(errorDescription));
    }

    const idToken = params.get('id_token');
    if (!idToken) {
      return throwError(
        () => new Error('Google Sign-In response did not contain an ID token.'),
      );
    }

    let payload: any;
    try {
      payload = this.decodeJwtPayload(idToken);
    } catch (e) {
      return throwError(() => new Error('Failed to decode Google ID token.'));
    }

    if (!payload) {
      return throwError(() => new Error('Failed to decode Google ID token.'));
    }

    if (!expectedNonce || payload.nonce !== expectedNonce) {
      return throwError(
        () => new Error('Invalid OIDC nonce. Please try signing in again.'),
      );
    }

    // If allowed, proceed to save session and return token
    this.firebaseIdToken = idToken;
    this.firebaseTokenExpiry = payload.exp * 1000;

    const session: FirebaseSession = {
      token: idToken,
      expiry: this.firebaseTokenExpiry,
    };
    if (isPlatformBrowser(this.platformId)) {
      try {
        localStorage.setItem(FIREBASE_SESSION_KEY, JSON.stringify(session));
      } catch (e) {
        console.warn('Could not write Firebase session to localStorage:', e);
      }
    }

    // Call the backend to get or create the user profile.
    return this.syncUserWithBackend$(idToken).pipe(
      map(() => idToken), // Pass the token along for the final result.
      catchError(syncError => {
        // Roll back in-memory and local session so the user is not left in a half-authenticated state
        this.firebaseIdToken = null;
        this.firebaseTokenExpiry = null;
        if (isPlatformBrowser(this.platformId)) {
          try {
            localStorage.removeItem(FIREBASE_SESSION_KEY);
            localStorage.removeItem(USER_DETAILS);
          } catch (e) {
            // ignore
          }
        }
        return throwError(() => syncError);
      }),
    );
  }

  /**
   * Asynchronously gets a valid Identity Platform token.
   * 1. Checks for a valid, non-expired token in memory/cache.
   * 2. If expired or missing, attempts a silent refresh.
   * 3. If silent refresh fails, it emits an error, signaling a required re-login.
   */
  getValidIdentityPlatformToken$(): Observable<string> {
    // First, check our own session info which is loaded from localStorage.
    // This is synchronous and tells us if we have a valid, non-expired token.
    if (!this.isLoggedIn()) {
      return throwError(
        () => new Error('User session is not valid or has expired.'),
      );
    }

    // Fallback case: The Firebase Auth instance is not yet initialized, but we
    // have a valid token from localStorage. We can use this for the current
    // request. The next request will likely hit the ideal case above.
    return of(this.firebaseIdToken!);
  }

  private syncUserWithBackend$(token: string): Observable<UserModel> {
    const headers = new HttpHeaders().set('Authorization', `Bearer ${token}`);
    return this.httpClient
      .get<UserModel>(`${environment.backendURL}/users/me`, {headers})
      .pipe(
        tap((userDetails: UserModel) => {
          // The backend is the source of truth. Save the returned profile to local storage.
          try {
            localStorage.setItem(USER_DETAILS, JSON.stringify(userDetails));
          } catch (e) {
            console.warn('Could not write USER_DETAILS to localStorage:', e);
          }
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

  async logout(route: string = LOGIN_ROUTE) {
    return this.auth
      .signOut()
      .then(() => {
        this.currentOAuthAccessToken = null; // Clear stored token on logout
        // Clear Firebase session data
        this.firebaseIdToken = null;
        this.firebaseTokenExpiry = null;
        localStorage.removeItem(FIREBASE_SESSION_KEY);
        localStorage.removeItem(USER_DETAILS);
        localStorage.removeItem('showTooltip');
        void this.router.navigateByUrl(route);
      })
      .catch(e => {
        console.error('Sign Out Error', e);
        localStorage.removeItem(FIREBASE_SESSION_KEY);
        localStorage.removeItem(USER_DETAILS);
        localStorage.removeItem('showTooltip');
        void this.router.navigate([LOGIN_ROUTE]);
      });
  }

  isLoggedIn() {
    if (!isPlatformBrowser(this.platformId)) return false;

    // Check if the in-memory token is valid
    const now = Date.now();
    const isTokenValid = !!(
      this.firebaseIdToken &&
      this.firebaseTokenExpiry &&
      this.firebaseTokenExpiry > now
    );

    const currentPath = (this.router.url || '').split('?')[0].split('#')[0];
    const isBrowser = isPlatformBrowser(this.platformId);
    const windowPath = isBrowser ? window.location.pathname : '';
    const isOnLogin =
      currentPath === LOGIN_ROUTE ||
      currentPath.startsWith('/login') ||
      windowPath === LOGIN_ROUTE ||
      windowPath.startsWith('/login');

    if (!isTokenValid && !isOnLogin) {
      void this.router.navigate([LOGIN_ROUTE]);
    }

    return isTokenValid;
  }

  private loadSessionFromStorage(): void {
    if (!isPlatformBrowser(this.platformId)) return;

    const sessionStr = localStorage.getItem(FIREBASE_SESSION_KEY);
    if (sessionStr) {
      const session: FirebaseSession = JSON.parse(sessionStr);
      // Check if the stored session is still valid
      if (session.expiry > Date.now()) {
        this.firebaseIdToken = session.token;
        this.firebaseTokenExpiry = session.expiry;
      } else {
        // If expired, remove it from storage.
        localStorage.removeItem(FIREBASE_SESSION_KEY);
      }
    }
  }

  isUserLoggedIn() {
    if (!isPlatformBrowser(this.platformId)) return false;

    const isUserLoggedIn = localStorage.getItem(FIREBASE_SESSION_KEY) !== null;
    return isUserLoggedIn;
  }

  isUserAdmin() {
    if (!isPlatformBrowser(this.platformId)) return false;

    const user_role = this.userService.getUserDetails()?.roles;
    return user_role?.includes(UserRolesEnum.ADMIN) || false;
  }

  isUserWorkflows() {
    if (!isPlatformBrowser(this.platformId)) return false;

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
    // Note: Tokens expire (usually after 1 hour).
    // A robust implementation would check expiry or refresh the token.
    // Firebase Auth automatically handles ID token refresh, but OAuth access token
    // refresh requires re-authentication or more complex flows not covered here.
    // For a simple deploy button click, getting a fresh token on sign-in might suffice.
    return this.currentOAuthAccessToken;
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
