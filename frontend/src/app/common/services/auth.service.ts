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
import {Observable, from, throwError, of, firstValueFrom, EMPTY} from 'rxjs';
import {catchError, tap, map, switchMap} from 'rxjs/operators';
import { PublicClientApplication, Configuration, AuthenticationResult } from '@azure/msal-browser';
import {isPlatformBrowser} from '@angular/common';
import {SettingsService} from '../../services/settings.service';

// Declare the 'google' global object from the Google Identity Services script
declare const google: any;

const USER_DETAILS = 'USER_DETAILS';
const LOGIN_ROUTE = '/login';
const INITIAL_HASH = typeof window !== 'undefined' ? window.location.hash : '';
if (typeof window !== 'undefined') {
  (window as any).INITIAL_HASH = INITIAL_HASH;
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
  private msalInstance: PublicClientApplication | null = null;

  get isEntraAuth(): boolean {
    return !!environment.ENTRA_CLIENT_ID && environment.ENTRA_CLIENT_ID !== 'ENTRA_CLIENT_ID_PLACEHOLDER';
  }

  constructor(
    private router: Router,
    private httpClient: HttpClient,
    private userService: UserService,
    private settingsService: SettingsService,
  ) {
    this.provider.setCustomParameters({
      // Set custom params for the provider
      prompt: 'select_account',
    });
    this.loadSessionFromStorage();
    if (isPlatformBrowser(this.platformId) && this.isEntraAuth) {
      this.getMsalInstance();
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

        // Save session details to memory.
        this.firebaseIdToken = token;
        this.firebaseTokenExpiry = expirationTime;

        // Call the backend to get or create the user profile.
        return this.syncUserWithBackend$(token).pipe(
          switchMap(() => from(this.settingsService.loadSettings())),
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
          // Update the in-memory cache and localStorage with the refreshed token info.
          const payload = JSON.parse(atob(token.split('.')[1]));
          const expiry = payload.exp * 1000;

          this.firebaseIdToken = token;
          this.firebaseTokenExpiry = expiry;
        }),
      );
    }

    // Fallback case: The Firebase Auth instance is not yet initialized, but we
    // have a valid token from localStorage. We can use this for the current
    // request. The next request will likely hit the ideal case above.
    return of(this.firebaseIdToken!);
  }

  /**
   * A test sign-in method to get a Google ID token compatible with Identity Platform.
   *
   * @returns An Observable that emits the Identity Platform-compatible ID token.
   */
  signInForGoogleIdentityPlatform(): Observable<string> {
    return this.promptForIdentityPlatformToken$().pipe(
      switchMap(idToken => {
        const payload = JSON.parse(atob(idToken.split('.')[1]));
        const userEmail = payload.email?.toLowerCase();

        // If allowed, proceed to save session and return token
        this.firebaseIdToken = idToken;
        this.firebaseTokenExpiry = payload.exp * 1000;

        // Call the backend to get or create the user profile.
        return this.syncUserWithBackend$(idToken).pipe(
          switchMap(() => from(this.settingsService.loadSettings())),
          map(() => idToken), // Pass the token along for the final result.
        );
      }),
    );
  }

  private msalInitPromise: Promise<PublicClientApplication> | null = null;

  async getMsalInstance(): Promise<PublicClientApplication> {
    if (!this.msalInitPromise) {
      this.msalInitPromise = this._initMsal();
    }
    return this.msalInitPromise;
  }

  private async _initMsal(): Promise<PublicClientApplication> {
    const msalConfig: Configuration = {
      auth: {
        clientId: environment.ENTRA_CLIENT_ID,
        authority: `https://login.microsoftonline.com/${environment.ENTRA_TENANT_ID}/v2.0`,
        redirectUri: window.location.origin,
        navigateToLoginRequestUrl: false
      } as any,
      cache: {
        cacheLocation: 'localStorage',
      }
    };
    this.msalInstance = new PublicClientApplication(msalConfig);
    await this.msalInstance.initialize();

    try {
      if (INITIAL_HASH && !window.location.hash) {
        window.location.hash = INITIAL_HASH;
      }
      const result = await this.msalInstance.handleRedirectPromise();
      if (result) {
        const idToken = result.idToken;
        const payload = JSON.parse(atob(idToken.split('.')[1]));
        
        this.firebaseIdToken = idToken;
        this.firebaseTokenExpiry = payload.exp * 1000;

        this.firebaseIdToken = idToken;
        this.firebaseTokenExpiry = payload.exp * 1000;

        await firstValueFrom(this.syncUserWithBackend$(idToken));
        await this.settingsService.loadSettings();
        // After successfully processing redirect, navigate to home
        this.router.navigate([LOGIN_ROUTE]).then(() => this.router.navigate(['/']));
      }
    } catch (error) {
        localStorage.setItem('MSAL_DEBUG_ERROR', (error as any)?.message || String(error));
        console.error('Error handling MSAL redirect:', error);
    }
    return this.msalInstance;
  }

  signInWithMicrosoftEntra(): Observable<string> {
    return from(this.getMsalInstance()).pipe(
      switchMap(msal => from(msal.loginPopup({ scopes: ['User.Read'] }))),
      switchMap((result: AuthenticationResult) => {
        const idToken = result.idToken;
        const payload = JSON.parse(atob(idToken.split('.')[1]));
        
        this.firebaseIdToken = idToken;
        this.firebaseTokenExpiry = payload.exp * 1000;

        this.firebaseIdToken = idToken;
        this.firebaseTokenExpiry = payload.exp * 1000;

        return this.syncUserWithBackend$(idToken).pipe(
           switchMap(() => from(this.settingsService.loadSettings())),
           map(() => idToken)
        );
      }),
      catchError(error => {
         console.error('Error during MSAL login:', error);
         return throwError(() => error);
      })
    );
  }

  private promptForIdentityPlatformToken$(): Observable<string> {
    const GOOGLE_CLIENT_ID = environment.GOOGLE_CLIENT_ID;

    return new Observable<string>(observer => {
      if (typeof google === 'undefined') {
        return observer.error(
          new Error(
            'Google Identity Services script not loaded. Add it to index.html',
          ),
        );
      }

      const loginTimeout = setTimeout(() => {
        observer.error(
          new Error(
            'Login timed out or third party sign-in may be disabled. Please try again and enable third party sign-in by clicking on the information button at the top left side of the browser.',
          ),
        );
      }, 15000);

      try {
        google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: (response: any) => {
            clearTimeout(loginTimeout);
            const idToken = response.credential;
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
          },
        });

        // Trigger the One Tap prompt.
        // Per new docs, we don't use the notification object for flow control.
        google.accounts.id.prompt();
      } catch (error) {
        clearTimeout(loginTimeout);
        console.error(
          'Error during Google Identity Platform sign-in initialization:',
          error,
        );
        observer.error(error);
      }
    });
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
      console.log('getValidIdentityPlatformToken: isLoggedIn is FALSE');
      return of();
    }

    // Fallback case: The Firebase Auth instance is not yet initialized, but we
    // have a valid token from localStorage. We can use this for the current
    // request. The next request will likely hit the ideal case above.
    console.log('getValidIdentityPlatformToken: isLoggedIn is TRUE, returning token');
    return of(this.firebaseIdToken!);
  }

  checkIapSession(): Observable<boolean> {
    return this.httpClient.get<UserModel>(`${environment.backendURL}/users/me`, {withCredentials: true}).pipe(
      tap((userDetails: UserModel) => {
        localStorage.setItem(USER_DETAILS, JSON.stringify(userDetails));
        console.log('IAP Session detected and synchronized.');
      }),
      map(() => true),
      catchError((error) => {
        console.log('No active IAP session found.', error);
        return of(false);
      })
    );
  }

  private syncUserWithBackend$(token: string): Observable<UserModel> {

    const headers = new HttpHeaders().set('X-Custom-Auth', `Bearer ${token}`);
    
    // First, exchange the token for an HttpOnly session cookie
    return this.httpClient.post(`${environment.backendURL}/auth/session`, {}, {headers, withCredentials: true}).pipe(
      // Then, fetch the user profile using the newly set cookie
      switchMap(() => this.httpClient.get<UserModel>(`${environment.backendURL}/users/me`, {withCredentials: true})),
      tap((userDetails: UserModel) => {
        // The backend is the source of truth. Save the returned profile to local storage.
        localStorage.setItem(USER_DETAILS, JSON.stringify(userDetails));
        console.log('User profile successfully synced with backend.');
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
    this.settingsService.reset();
    
    // Attempt to log out of the backend first to clear the session cookie
    try {
      await firstValueFrom(this.httpClient.post(`${environment.backendURL}/auth/logout`, {}, {withCredentials: true}));
    } catch (e) {
      console.error('Backend logout failed', e);
    }
    
    return this.auth
      .signOut()
      .then(() => {
        this.currentOAuthAccessToken = null; // Clear stored token on logout
        // Clear Firebase session data
        this.firebaseIdToken = null;
        this.firebaseTokenExpiry = null;
        localStorage.removeItem(USER_DETAILS);
        localStorage.removeItem('showTooltip');
        void this.router.navigateByUrl(route);
      })
      .catch(e => {
        console.error('Sign Out Error', e);
        this.settingsService.reset();
        localStorage.removeItem(USER_DETAILS);
        localStorage.removeItem('showTooltip');
        void this.router.navigate([LOGIN_ROUTE]);
      });
  }

  isLoggedIn() {
    if (!isPlatformBrowser(this.platformId)) return false;

    const isTokenValid = localStorage.getItem(USER_DETAILS) !== null;

    if (!isTokenValid && this.router.url !== LOGIN_ROUTE) {
      void this.router.navigate([LOGIN_ROUTE]);
    }

    return isTokenValid;
  }

  private loadSessionFromStorage(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    // Session is now managed via HttpOnly cookies, so we don't load tokens from localStorage.
  }

  isUserLoggedIn() {
    if (!isPlatformBrowser(this.platformId)) return false;

    const isUserLoggedIn = localStorage.getItem(USER_DETAILS) !== null;
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
}
