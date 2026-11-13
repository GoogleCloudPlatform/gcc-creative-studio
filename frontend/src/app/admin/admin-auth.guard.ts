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

import {inject, Injectable, PLATFORM_ID} from '@angular/core';
import {
  CanActivate,
  ActivatedRouteSnapshot,
  RouterStateSnapshot,
  UrlTree,
} from '@angular/router';
import {isPlatformBrowser} from '@angular/common';
import {Observable, of} from 'rxjs';
import {catchError, defaultIfEmpty, map} from 'rxjs/operators';
import {UserService} from '../common/services/user.service';
import {MatSnackBar} from '@angular/material/snack-bar';
import {AuthService} from '../common/services/auth.service';
import {handleErrorSnackbar} from '../utils/handleMessageSnackbar';

@Injectable({
  providedIn: 'root',
})
export class AdminAuthGuard implements CanActivate {
  private platformId = inject(PLATFORM_ID);

  constructor(
    private authService: AuthService,
    private userService: UserService,
    private _snackBar: MatSnackBar,
  ) {}

  canActivate(
    _route: ActivatedRouteSnapshot,
    state: RouterStateSnapshot,
  ):
    | Observable<boolean | UrlTree>
    | Promise<boolean | UrlTree>
    | boolean
    | UrlTree {
    if (!isPlatformBrowser(this.platformId)) {
      // --- SERVER SIDE ---
      // Allow navigation to render the basic app shell.
      // The client will verify localStorage and redirect if necessary.
      return true;
    }

    // --- BROWSER SIDE ---
    if (this.authService.isLoggedIn()) {
      return this.isAdmin();
    }

    // Expired but renewable (e.g. waking from sleep): renew silently first.
    if (this.authService.hasRenewableSession()) {
      return this.authService.getValidIdentityPlatformToken$().pipe(
        defaultIfEmpty(null),
        map(token => {
          if (!token) {
            this.authService.redirectToLogin(state?.url);
            return false;
          }
          return this.isAdmin();
        }),
        catchError(() => {
          this.authService.onSessionRenewalFailed(state?.url);
          return of(false);
        }),
      );
    }

    this.authService.redirectToLogin(state?.url);
    return false;
  }

  private isAdmin(): boolean {
    const userDetails = this.userService.getUserDetails(); // Get user details from localStorage
    const userEmail = userDetails?.email?.toLowerCase();

    if (userEmail && this.authService.isUserAdmin()) {
      return true; // User is authenticated and email is in the allowed list
    }
    // User is not authenticated or not an allowed admin
    console.warn('Access denied to admin area.');

    handleErrorSnackbar(
      this._snackBar,
      {
        message: `Access Denied: Your email (${userEmail}) is not authorized or login session expired.`,
      },
      'Access Denied',
    );

    // Automatic sign-out (not user-initiated): keeps Google silent sign-in on.
    void this.authService.expireSession();
    return false; // Prevent navigation
  }
}
