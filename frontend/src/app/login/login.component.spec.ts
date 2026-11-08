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
import {of, throwError, NEVER} from 'rxjs';
import {LoginComponent} from './login.component';
import {AuthService} from './../common/services/auth.service';
import {UserModel} from './../common/models/user.model';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Router} from '@angular/router';
import {Injector, NgZone} from '@angular/core';
import {environment} from '../../environments/environment';
import {MatCardModule} from '@angular/material/card';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {AppInjector, setAppInjector} from '../app-injector';
import {NotificationService} from '../common/services/notification.service';

// Define a MockAuthService class
class MockAuthService {
  signInWithGoogleFirebase = jasmine.createSpy('signInWithGoogleFirebase');
  signInForGoogleIdentityPlatform = jasmine.createSpy(
    'signInForGoogleIdentityPlatform',
  );
  completeGoogleOidcRedirect$ = jasmine.createSpy(
    'completeGoogleOidcRedirect$',
  );
  hasPendingOidcRedirect = jasmine
    .createSpy('hasPendingOidcRedirect')
    .and.returnValue(false);
  // Add any other methods from AuthService that are called in LoginComponent
}

describe('LoginComponent', () => {
  let component: LoginComponent;
  let fixture: ComponentFixture<LoginComponent>;
  let authService: MockAuthService; // Use the mocked service
  let router: Router;
  let ngZone: NgZone;
  let snackBar: jasmine.SpyObj<MatSnackBar>;
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
        NoopAnimationsModule,
      ],
      declarations: [LoginComponent],
      providers: [
        {provide: AuthService, useClass: MockAuthService}, // Use useClass for the mock
        {provide: MatSnackBar, useValue: snackBarSpy},
        {provide: NotificationService, useValue: notificationServiceSpy},
      ],
    }).compileComponents();

    notificationService = TestBed.inject(
      NotificationService,
    ) as jasmine.SpyObj<NotificationService>;

    if (AppInjector) {
      spyOn(AppInjector, 'get').and.callFake((token: any) => {
        if (token === NotificationService) {
          return notificationService;
        }
        return null as any;
      });
    } else {
      setAppInjector(TestBed.inject(Injector));
    }

    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    // fixture.detectChanges(); // No longer needed with autoDetectChanges
    fixture.autoDetectChanges(true); // Enable auto-detection of changes
    authService = TestBed.inject(AuthService) as unknown as MockAuthService; // Inject the mock instance
    router = TestBed.inject(Router);
    ngZone = TestBed.inject(NgZone);
    snackBar = TestBed.inject(MatSnackBar) as jasmine.SpyObj<MatSnackBar>;
  });

  it('should create the component', () => {
    expect(component).toBeTruthy();
  });

  describe('ngOnInit (OIDC redirect callback handling)', () => {
    it('should not call completeGoogleOidcRedirect$ if hash has neither id_token nor error', () => {
      (component as any).initialOidcHash = '';
      authService.completeGoogleOidcRedirect$.calls.reset();

      component.ngOnInit();

      expect(authService.completeGoogleOidcRedirect$).not.toHaveBeenCalled();
    });

    it('should call completeGoogleOidcRedirect$ and navigate to home when id_token is present in hash', fakeAsync(() => {
      const fakeHash = '#id_token=fake-token&token_type=Bearer';
      (component as any).initialOidcHash = fakeHash;
      authService.completeGoogleOidcRedirect$.and.returnValue(of('fake-token'));
      spyOn(router, 'navigate');

      component.ngOnInit();
      tick();

      expect(authService.completeGoogleOidcRedirect$).toHaveBeenCalledWith(
        fakeHash,
      );
      expect(component.loader).toBeFalse();
      expect(router.navigate).toHaveBeenCalledWith(['/']);
    }));

    it('should call completeGoogleOidcRedirect$ and handle login error when error is present in hash', fakeAsync(() => {
      spyOn(console, 'error');
      const fakeHash = '#error=access_denied&error_description=Consent+denied';
      const oidcError = new Error('Consent denied');
      (component as any).initialOidcHash = fakeHash;
      authService.completeGoogleOidcRedirect$.and.returnValue(
        throwError(() => oidcError),
      );
      spyOn(component as any, 'handleLoginError');

      component.ngOnInit();
      tick();

      expect(authService.completeGoogleOidcRedirect$).toHaveBeenCalledWith(
        fakeHash,
      );
      expect(component.loader).toBeFalse();
      expect((component as any).handleLoginError).toHaveBeenCalledWith(
        oidcError,
      );
    }));

    it('should fall back to router fragment if initialOidcHash and window.location.hash are empty', fakeAsync(() => {
      (component as any).initialOidcHash = '';
      spyOn(router, 'parseUrl').and.returnValue({
        fragment: 'id_token=router-token&token_type=Bearer',
      } as any);
      authService.completeGoogleOidcRedirect$.and.returnValue(
        of('router-token'),
      );
      spyOn(router, 'navigate');

      component.ngOnInit();
      tick();

      expect(authService.completeGoogleOidcRedirect$).toHaveBeenCalledWith(
        '#id_token=router-token&token_type=Bearer',
      );
      expect(component.loader).toBeFalse();
      expect(router.navigate).toHaveBeenCalledWith(['/']);
    }));

    it('should complete redirect when authService.hasPendingOidcRedirect() is true even if hash is empty', fakeAsync(() => {
      (component as any).initialOidcHash = '';
      authService.hasPendingOidcRedirect.and.returnValue(true);
      authService.completeGoogleOidcRedirect$.and.returnValue(
        of('cached-token'),
      );
      spyOn(router, 'navigate');

      component.ngOnInit();
      tick();

      expect(authService.completeGoogleOidcRedirect$).toHaveBeenCalled();
      expect(component.loader).toBeFalse();
      expect(router.navigate).toHaveBeenCalledWith(['/']);
    }));
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
        (environment as any).isLocal = true;
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
        spyOn(component, 'handleLoginError' as any);

        component.loginWithGoogle();
        tick();

        expect(component.loader).toBeFalse();
        expect((component as any).handleLoginError).toHaveBeenCalledWith(error);
      }));

      it('should handle string error from signInWithGoogleFirebase', fakeAsync(() => {
        consoleErrorSpy.and.stub();
        const error = 'An unexpected error occurred';
        authService.signInWithGoogleFirebase.and.returnValue(
          throwError(() => error),
        );
        spyOn(component, 'handleLoginError' as any);

        component.loginWithGoogle();
        tick();

        expect(component.loader).toBeFalse();
        expect((component as any).handleLoginError).toHaveBeenCalledWith(error);
      }));
    });

    describe('in non-local environment', () => {
      beforeEach(() => {
        (environment as any).isLocal = false;
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
        spyOn(component, 'handleLoginError' as any);

        component.loginWithGoogle();
        tick();

        expect(component.loader).toBeFalse();
        expect((component as any).handleLoginError).toHaveBeenCalledWith(error);
      }));

      it('should handle string error from signInForGoogleIdentityPlatform', fakeAsync(() => {
        consoleErrorSpy.and.stub();
        const error = 'An unexpected error occurred';
        authService.signInForGoogleIdentityPlatform.and.returnValue(
          throwError(() => error),
        );
        spyOn(component, 'handleLoginError' as any);

        component.loginWithGoogle();
        tick();

        expect(component.loader).toBeFalse();
        expect((component as any).handleLoginError).toHaveBeenCalledWith(error);
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
      expect(component.invalidLogin).toBeTrue();
      expect(component.errorMessage).toEqual(errorMessage.message);
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
  });
});
