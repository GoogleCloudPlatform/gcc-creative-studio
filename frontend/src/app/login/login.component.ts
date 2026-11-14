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

import {
  ChangeDetectorRef,
  Component,
  ElementRef,
  Inject,
  NgZone,
  OnDestroy,
  PLATFORM_ID,
  QueryList,
  ViewChildren,
  inject,
} from '@angular/core';
import {ActivatedRoute, Router} from '@angular/router';
import {Subscription} from 'rxjs';
import {AuthService} from './../common/services/auth.service';
import {
  GisPromptSuppressedError,
  sanitizeReturnUrl,
} from './../common/services/auth-token.utils';
import {UserModel} from './../common/models/user.model';
import {MatSnackBar} from '@angular/material/snack-bar';
import {handleErrorSnackbar} from '../utils/handleMessageSnackbar';
import {environment} from '../../environments/environment';
import {isPlatformBrowser} from '@angular/common';

const HOME_ROUTE = '/';

@Component({
  selector: 'app-login',
  templateUrl: './login.component.html',
  styleUrls: ['./login.component.scss'],
})
export class LoginComponent implements OnDestroy {
  private readonly route = inject(ActivatedRoute, {optional: true});
  private readonly cdr = inject(ChangeDetectorRef);
  private signInSub: Subscription | null = null;
  private fallbackSub: Subscription | null = null;
  private destroyed = false;

  @ViewChildren('googleFallbackBtn')
  fallbackContainers?: QueryList<ElementRef<HTMLElement>>;

  loader = false;
  invalidLogin = false;
  errorMessage = '';
  showFallbackGoogleButton = false;
  isBrowser: boolean;

  constructor(
    private authService: AuthService,
    private router: Router,
    public ngZone: NgZone,
    private _snackBar: MatSnackBar,
    @Inject(PLATFORM_ID) platformId: object,
  ) {
    this.isBrowser = isPlatformBrowser(platformId);
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.signInSub?.unsubscribe();
    this.signInSub = null;
    this.fallbackSub?.unsubscribe();
    this.fallbackSub = null;
  }

  loginWithGoogle() {
    this.loader = true;
    this.invalidLogin = false;
    this.errorMessage = '';
    this.showFallbackGoogleButton = false;
    this.signInSub?.unsubscribe();
    this.signInSub = null;
    this.fallbackSub?.unsubscribe();
    this.fallbackSub = null;

    const signIn$ = environment?.isLocal
      ? this.authService.signInWithGoogleFirebase()
      : this.authService.signInForGoogleIdentityPlatform();

    this.signInSub = signIn$.subscribe({
      next: () => {
        this.ngZone.run(() => this.navigateAfterLogin());
      },
      error: (error: unknown) => {
        this.ngZone.run(() => this.handleSignInAttemptError(error));
      },
    });
  }

  private handleSignInAttemptError(error: unknown): void {
    if (error instanceof GisPromptSuppressedError) {
      this.activateFallbackGoogleButton();
      return;
    }

    this.loader = false;
    console.error('Login failed', error);
    this.handleLoginError(
      error || {
        message:
          'An unexpected error occurred during sign-in. Please try again.',
      },
    );
  }

  private activateFallbackGoogleButton(): void {
    this.loader = false;
    this.showFallbackGoogleButton = true;
    this.cdr.detectChanges();
    this.renderFallbackGoogleButton();
  }

  private renderFallbackGoogleButton(isRetryAfterError = false): void {
    this.fallbackSub?.unsubscribe();
    this.fallbackSub = null;
    if (this.destroyed || !this.showFallbackGoogleButton) return;

    const elements =
      this.fallbackContainers?.toArray().map(ref => ref.nativeElement) ?? [];
    if (elements.length === 0) return;

    let synchronous = true;
    let credentialStarted = false;
    this.fallbackSub = this.authService
      .renderGoogleSignInButton$(elements, () => {
        credentialStarted = true;
        this.ngZone.run(() => {
          this.loader = true;
        });
      })
      .subscribe({
        next: () => {
          this.ngZone.run(() => this.navigateAfterLogin());
        },
        error: (error: unknown) => {
          if (isRetryAfterError && synchronous) {
            return;
          }
          this.ngZone.run(() => {
            this.handleLoginError(error);
            if (
              !synchronous &&
              credentialStarted &&
              this.showFallbackGoogleButton &&
              !this.destroyed
            ) {
              this.renderFallbackGoogleButton(true);
            }
          });
        },
      });
    synchronous = false;
  }

  private handleLoginError(error: unknown, postErrorAction?: () => void) {
    this.loader = false;
    handleErrorSnackbar(this._snackBar, error, 'Login Error');
    if (postErrorAction) {
      postErrorAction();
    }
  }

  redirect(user: UserModel) {
    if (this.isBrowser) {
      localStorage.setItem('USER_DETAILS', JSON.stringify(user));
    }
    this.navigateAfterLogin();
  }

  private navigateAfterLogin(): void {
    this.loader = false;
    const returnUrl = sanitizeReturnUrl(
      this.route?.snapshot?.queryParamMap?.get('returnUrl'),
    );
    if (returnUrl && returnUrl !== HOME_ROUTE) {
      void this.router.navigateByUrl(returnUrl);
      return;
    }
    void this.router.navigate([HOME_ROUTE]);
  }
}
