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

import {TestBed} from '@angular/core/testing';
import {ActivatedRouteSnapshot, RouterStateSnapshot} from '@angular/router';
import {Observable, Subject, firstValueFrom, of, throwError} from 'rxjs';
import {MatSnackBar} from '@angular/material/snack-bar';
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {AdminAuthGuard} from './admin-auth.guard';
import {AuthService} from '../common/services/auth.service';
import {LoadingService} from '../common/services/loading.service';
import {UserService} from '../common/services/user.service';

describe('AdminAuthGuard', () => {
  let service: AdminAuthGuard;
  let loadingService: LoadingService;
  let authService: jasmine.SpyObj<AuthService>;

  const route = {} as ActivatedRouteSnapshot;
  const state = {url: '/admin'} as RouterStateSnapshot;

  beforeEach(() => {
    authService = jasmine.createSpyObj<AuthService>('AuthService', [
      'isLoggedIn',
      'hasRenewableSession',
      'getValidIdentityPlatformToken$',
      'onSessionRenewalFailed',
      'redirectToLogin',
      'isUserAdmin',
      'expireSession',
      'logout',
    ]);
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        AdminAuthGuard,
        {provide: AuthService, useValue: authService},
        {
          provide: UserService,
          useValue: {getUserDetails: () => ({email: 'admin@example.com'})},
        },
        {provide: MatSnackBar, useValue: {}},
      ],
    });
    service = TestBed.inject(AdminAuthGuard);
    loadingService = TestBed.inject(LoadingService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('redirects to login with returnUrl when there is no session', () => {
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(false);
    expect(service.canActivate(route, state)).toBeFalse();
    expect(authService.redirectToLogin).toHaveBeenCalledOnceWith('/admin');
  });

  it('renews an expired admin session silently while showing loading indicator', async () => {
    const token$ = new Subject<string>();
    const loadingStates: boolean[] = [];
    const sub = loadingService.isLoading$.subscribe(v => loadingStates.push(v));
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(
      token$.asObservable(),
    );
    authService.isUserAdmin.and.returnValue(true);

    const resultPromise = firstValueFrom(
      service.canActivate(route, state) as Observable<boolean>,
    );
    expect(loadingStates[loadingStates.length - 1]).toBeTrue();

    token$.next('fresh');
    token$.complete();
    expect(await resultPromise).toBeTrue();
    expect(loadingStates[loadingStates.length - 1]).toBeFalse();
    expect(authService.logout).not.toHaveBeenCalled();
    sub.unsubscribe();
  });

  it('calls expireSession (never logout) when renewed user is not an admin', async () => {
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(of('fresh'));
    authService.isUserAdmin.and.returnValue(false);

    const result = service.canActivate(route, state) as Observable<boolean>;

    expect(await firstValueFrom(result)).toBeFalse();
    expect(authService.expireSession).toHaveBeenCalled();
    expect(authService.logout).not.toHaveBeenCalled();
  });

  it('passes target state.url to onSessionRenewalFailed when renewal fails', async () => {
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(
      throwError(() => new Error('silent sign-in failed')),
    );

    const result = service.canActivate(route, state) as Observable<boolean>;

    expect(await firstValueFrom(result)).toBeFalse();
    expect(authService.onSessionRenewalFailed).toHaveBeenCalledOnceWith(
      '/admin',
      jasmine.any(Error),
    );
  });
});
