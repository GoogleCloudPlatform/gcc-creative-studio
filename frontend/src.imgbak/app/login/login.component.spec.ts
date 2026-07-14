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

    setAppInjector(TestBed.inject(Injector));

    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    // fixture.detectChanges(); // No longer needed with autoDetectChanges
    fixture.autoDetectChanges(true); // Enable auto-detection of changes
    authService = TestBed.inject(AuthService) as unknown as MockAuthService; // Inject the mock instance
    router = TestBed.inject(Router);
    ngZone = TestBed.inject(NgZone);
    snackBar = TestBed.inject(MatSnackBar) as jasmine.SpyObj<MatSnackBar>;
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
      expect(notificationService.show).toHaveBeenCalledWith(
        errorMessage.message,
        'error',
        'cross-in-circle-white',
        undefined,
        20000,
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
