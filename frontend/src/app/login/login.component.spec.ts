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
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
} from '@angular/core/testing';
import {RouterTestingModule} from '@angular/router/testing';
import {of, throwError, NEVER, Subject} from 'rxjs';
import {LoginComponent} from './login.component';
import {AuthService} from './../common/services/auth.service';
import {GisPromptSuppressedError} from './../common/services/auth-token.utils';
import {UserModel} from './../common/models/user.model';
import {MatSnackBar} from '@angular/material/snack-bar';
import {ActivatedRoute, Router, convertToParamMap} from '@angular/router';
import {environment} from '../../environments/environment';
import {MatCardModule} from '@angular/material/card';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {useTestBedAppInjector} from '../testing/app-injector.testing';
import {NotificationService} from '../common/services/notification.service';

// Define a MockAuthService class
class MockAuthService {
  signInWithGoogleFirebase = jasmine.createSpy('signInWithGoogleFirebase');
  signInForGoogleIdentityPlatform = jasmine.createSpy(
    'signInForGoogleIdentityPlatform',
  );
  renderGoogleSignInButton$ = jasmine.createSpy('renderGoogleSignInButton$');
}

describe('LoginComponent', () => {
  let component: LoginComponent;
  let fixture: ComponentFixture<LoginComponent>;
  let authService: MockAuthService;
  let router: Router;
  let notificationService: jasmine.SpyObj<NotificationService>;
  let consoleErrorSpy: jasmine.Spy;

  const mockUser: UserModel = {
    id: '123',
    name: 'Test User',
    email: 'test@example.com',
    picture:
      'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  };

  beforeEach(async () => {
    const snackBarSpy = jasmine.createSpyObj('MatSnackBar', ['open']);
    const notificationServiceSpy = jasmine.createSpyObj('NotificationService', [
      'show',
    ]);

    await TestBed.configureTestingModule({
      imports: [
        RouterTestingModule.withRoutes([{path: '', component: LoginComponent}]),
        MatCardModule,
        MatFormFieldModule,
        MatInputModule,
        MatProgressSpinnerModule,
        NoopAnimationsModule,
      ],
      declarations: [LoginComponent],
      providers: [
        {provide: AuthService, useClass: MockAuthService},
        {provide: MatSnackBar, useValue: snackBarSpy},
        {provide: NotificationService, useValue: notificationServiceSpy},
      ],
    }).compileComponents();

    useTestBedAppInjector();

    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    fixture.autoDetectChanges(true);
    authService = TestBed.inject(AuthService) as unknown as MockAuthService;
    router = TestBed.inject(Router);
    notificationService = TestBed.inject(
      NotificationService,
    ) as jasmine.SpyObj<NotificationService>;
  });

  it('should create the component', () => {
    expect(component).toBeTruthy();
  });

  describe('loginWithGoogle', () => {
    beforeEach(() => {
      consoleErrorSpy = spyOn(console, 'error');
    });
    it('should show loader and reset error flags', fakeAsync(() => {
      authService.signInWithGoogleFirebase.and.returnValue(NEVER); // Use NEVER to prevent completion or error
      authService.signInForGoogleIdentityPlatform.and.returnValue(NEVER); // Use NEVER
      component.loader = false;
      component.invalidLogin = true;
      component.errorMessage = 'Old error';

      component.loginWithGoogle();
      // fixture.detectChanges(); // autoDetectChanges is true

      expect(component.loader).toBeTrue();
      expect(component.invalidLogin).toBeFalse();
      expect(component.errorMessage).toBe('');
    }));
    describe('in local environment', () => {
      beforeEach(() => {
        (environment as {isLocal: boolean}).isLocal = true;
      });

      it('should call signInWithGoogleFirebase and navigate on success', fakeAsync(() => {
        authService.signInWithGoogleFirebase.and.returnValue(of('test-token'));
        spyOn(router, 'navigate');

        component.loginWithGoogle();
        tick();

        expect(authService.signInWithGoogleFirebase).toHaveBeenCalled();
        expect(component.loader).toBeFalse();
        expect(router.navigate).toHaveBeenCalledWith(['/']);
      }));

      it('should handle error from signInWithGoogleFirebase', fakeAsync(() => {
        consoleErrorSpy.and.stub();
        const error = new Error('Access Denied');
        authService.signInWithGoogleFirebase.and.returnValue(
          throwError(() => error),
        );
        const handleSpy = spyOn(
          component as unknown as {handleLoginError: (err: unknown) => void},
          'handleLoginError',
        );

        component.loginWithGoogle();
        tick();

        expect(component.loader).toBeFalse();
        expect(handleSpy).toHaveBeenCalledWith(error);
      }));

      it('should handle string error from signInWithGoogleFirebase', fakeAsync(() => {
        consoleErrorSpy.and.stub();
        const error = 'An unexpected error occurred';
        authService.signInWithGoogleFirebase.and.returnValue(
          throwError(() => error),
        );
        const handleSpy = spyOn(
          component as unknown as {handleLoginError: (err: unknown) => void},
          'handleLoginError',
        );

        component.loginWithGoogle();
        tick();

        expect(component.loader).toBeFalse();
        expect(handleSpy).toHaveBeenCalledWith(error);
      }));
    });

    describe('in non-local environment', () => {
      beforeEach(() => {
        (environment as {isLocal: boolean}).isLocal = false;
      });

      it('should call signInForGoogleIdentityPlatform and navigate on success', fakeAsync(() => {
        authService.signInForGoogleIdentityPlatform.and.returnValue(
          of('test-token'),
        );
        spyOn(router, 'navigate');

        component.loginWithGoogle();
        tick();

        expect(authService.signInForGoogleIdentityPlatform).toHaveBeenCalled();
        expect(component.loader).toBeFalse();
        expect(router.navigate).toHaveBeenCalledWith(['/']);
      }));

      it('should handle error from signInForGoogleIdentityPlatform', fakeAsync(() => {
        consoleErrorSpy.and.stub();
        const error = new Error(
          'An unexpected error occurred during sign-in. Please try again.',
        );
        authService.signInForGoogleIdentityPlatform.and.returnValue(
          throwError(() => error),
        );
        const handleSpy = spyOn(
          component as unknown as {handleLoginError: (err: unknown) => void},
          'handleLoginError',
        );

        component.loginWithGoogle();
        tick();

        expect(component.loader).toBeFalse();
        expect(handleSpy).toHaveBeenCalledWith(error);
      }));

      it('should handle string error from signInForGoogleIdentityPlatform', fakeAsync(() => {
        consoleErrorSpy.and.stub();
        const error = 'An unexpected error occurred';
        authService.signInForGoogleIdentityPlatform.and.returnValue(
          throwError(() => error),
        );
        const handleSpy = spyOn(
          component as unknown as {handleLoginError: (err: unknown) => void},
          'handleLoginError',
        );

        component.loginWithGoogle();
        tick();

        expect(component.loader).toBeFalse();
        expect(handleSpy).toHaveBeenCalledWith(error);
      }));

      it('renders fallback Google buttons across containers on GisPromptSuppressedError without a toast and navigates on success', fakeAsync(() => {
        const activatedRoute = TestBed.inject(ActivatedRoute);
        (activatedRoute as {snapshot: unknown}).snapshot = {
          queryParamMap: convertToParamMap({
            returnUrl: '/gallery?filter=video',
          }),
        };
        const navByUrlSpy = spyOn(router, 'navigateByUrl');
        const fallback$ = new Subject<string>();
        let capturedStartCb: (() => void) | undefined;
        let capturedContainers: readonly HTMLElement[] = [];

        authService.signInForGoogleIdentityPlatform.and.returnValue(
          throwError(() => new GisPromptSuppressedError()),
        );
        authService.renderGoogleSignInButton$.and.callFake(
          (containers: readonly HTMLElement[], onStart?: () => void) => {
            capturedContainers = containers;
            capturedStartCb = onStart;
            return fallback$.asObservable();
          },
        );

        component.loginWithGoogle();
        tick();

        expect(component.loader).toBeFalse();
        expect(component.showFallbackGoogleButton).toBeTrue();
        expect(notificationService.show).not.toHaveBeenCalled();
        expect(consoleErrorSpy).not.toHaveBeenCalled();

        const host = fixture.nativeElement as HTMLElement;
        expect(host.textContent).toContain(
          'Single sign-on was skipped. Click below to continue with Google:',
        );
        expect(host.textContent).not.toContain('Login with Google');
        expect(authService.renderGoogleSignInButton$).toHaveBeenCalledTimes(1);
        expect(capturedContainers.length).toBe(2);

        capturedStartCb?.();
        expect(component.loader).toBeTrue();

        fallback$.next('fallback-token');
        tick();
        expect(component.loader).toBeFalse();
        expect(navByUrlSpy).toHaveBeenCalledWith('/gallery?filter=video');
      }));

      it('keeps fallback button interactive and shows snackbar on /users/me 403 error, then succeeds on retry', fakeAsync(() => {
        consoleErrorSpy.and.stub();
        const navSpy = spyOn(router, 'navigate');
        const attempt1$ = new Subject<string>();
        const attempt2$ = new Subject<string>();
        const startCallbacks: Array<(() => void) | undefined> = [];

        authService.signInForGoogleIdentityPlatform.and.returnValue(
          throwError(() => new GisPromptSuppressedError()),
        );
        let callIndex = 0;
        authService.renderGoogleSignInButton$.and.callFake(
          (_containers: readonly HTMLElement[], onStart?: () => void) => {
            startCallbacks.push(onStart);
            const stream = callIndex === 0 ? attempt1$ : attempt2$;
            callIndex++;
            return stream.asObservable();
          },
        );

        component.loginWithGoogle();
        tick();

        startCallbacks[0]?.();
        expect(component.loader).toBeTrue();
        attempt1$.error(new Error('Forbidden (403)'));
        tick();

        expect(component.loader).toBeFalse();
        expect(component.showFallbackGoogleButton).toBeTrue();
        expect(notificationService.show).toHaveBeenCalledTimes(1);
        expect(authService.renderGoogleSignInButton$).toHaveBeenCalledTimes(2);

        startCallbacks[1]?.();
        expect(component.loader).toBeTrue();
        attempt2$.next('retry-token');
        tick();
        expect(component.loader).toBeFalse();
        expect(navSpy).toHaveBeenCalledWith(['/']);
      }));
    });
  });

  describe('handleLoginError', () => {
    beforeEach(() => {
      consoleErrorSpy = spyOn(console, 'error');
    });
    it('should hide loader and show snackbar', () => {
      component.loader = true;
      const errorMessage = {message: 'Test error message'};

      component['handleLoginError'](errorMessage);

      expect(component.loader).toBeFalse();
      expect(notificationService.show).toHaveBeenCalledWith(
        errorMessage.message,
        'error',
        'cross-in-circle-white',
        undefined,
        5000,
      );
    });

    it('should execute postErrorAction if provided', () => {
      const postErrorAction = jasmine.createSpy('postErrorAction');
      const errorMessage = {message: 'Test error'};
      component['handleLoginError'](errorMessage, postErrorAction);
      expect(postErrorAction).toHaveBeenCalled();
    });
  });

  describe('redirect', () => {
    it('should store user details in localStorage, hide loader and navigate', () => {
      spyOn(localStorage, 'setItem');
      spyOn(router, 'navigate');
      component.loader = true;

      component.redirect(mockUser);

      expect(localStorage.setItem).toHaveBeenCalledWith(
        'USER_DETAILS',
        JSON.stringify(mockUser),
      );
      expect(component.loader).toBeFalse();
      expect(router.navigate).toHaveBeenCalledWith(['/']);
    });

    it('navigates to safe internal returnUrl after login and rejects external URLs', fakeAsync(() => {
      (environment as {isLocal: boolean}).isLocal = false;
      const activatedRoute = TestBed.inject(ActivatedRoute);
      (activatedRoute as {snapshot: unknown}).snapshot = {
        queryParamMap: convertToParamMap({
          returnUrl: '/workbench?sessionId=42',
        }),
      };
      authService.signInForGoogleIdentityPlatform.and.returnValue(
        of('test-token'),
      );
      const navByUrlSpy = spyOn(router, 'navigateByUrl');
      const navSpy = spyOn(router, 'navigate');

      component.loginWithGoogle();
      tick();

      expect(navByUrlSpy).toHaveBeenCalledWith('/workbench?sessionId=42');
      expect(navSpy).not.toHaveBeenCalled();

      navByUrlSpy.calls.reset();
      (activatedRoute as {snapshot: unknown}).snapshot = {
        queryParamMap: convertToParamMap({
          returnUrl: 'https://evil.example/phish',
        }),
      };
      component.loginWithGoogle();
      tick();

      expect(navByUrlSpy).not.toHaveBeenCalled();
      expect(navSpy).toHaveBeenCalledWith(['/']);
    }));
  });

  it('unsubscribes in-flight signIn$ on ngOnDestroy without navigating', () => {
    (environment as {isLocal: boolean}).isLocal = false;
    const pendingSignIn$ = new Subject<string>();
    const navSpy = spyOn(router, 'navigate');
    authService.signInForGoogleIdentityPlatform.and.returnValue(
      pendingSignIn$.asObservable(),
    );

    component.loginWithGoogle();
    expect(pendingSignIn$.observed).toBeTrue();

    fixture.destroy();
    expect(pendingSignIn$.observed).toBeFalse();

    pendingSignIn$.next('late-token');
    expect(navSpy).not.toHaveBeenCalled();
  });
});
