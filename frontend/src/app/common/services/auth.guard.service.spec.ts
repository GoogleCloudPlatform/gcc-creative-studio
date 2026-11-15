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
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {
  ActivatedRouteSnapshot,
  Router,
  RouterStateSnapshot,
} from '@angular/router';
import {Observable, Subject, firstValueFrom, of} from 'rxjs';

import {AuthGuardService} from './auth.guard.service';
import {AuthService} from './auth.service';
import {LoadingService} from './loading.service';
import {UserService} from './user.service';
import {UserRolesEnum} from '../models/user.model';

describe('AuthGuardService', () => {
  let service: AuthGuardService;
  let loadingService: LoadingService;
  let router: {navigate: jasmine.Spy};
  let authService: jasmine.SpyObj<AuthService>;
  let userRoles: UserRolesEnum[] | null;

  const route = {data: {}} as unknown as ActivatedRouteSnapshot;
  const state = {url: '/workflows/7'} as RouterStateSnapshot;

  beforeEach(() => {
    userRoles = null;
    router = {navigate: jasmine.createSpy('navigate')};
    authService = jasmine.createSpyObj<AuthService>('AuthService', [
      'isLoggedIn',
      'hasRenewableSession',
      'getValidIdentityPlatformToken$',
      'onSessionRenewalFailed',
      'redirectToLogin',
    ]);
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        AuthGuardService,
        {provide: AuthService, useValue: authService},
        {provide: Router, useValue: router},
        {
          provide: UserService,
          useValue: {
            getUserDetails: () => (userRoles ? {roles: userRoles} : null),
          },
        },
      ],
    });
    service = TestBed.inject(AuthGuardService);
    loadingService = TestBed.inject(LoadingService);
  });

  it('allows navigation with a valid session', () => {
    authService.isLoggedIn.and.returnValue(true);
    expect(service.canActivate(route, state)).toBeTrue();
  });

  it('redirects to login with returnUrl when there is no session', () => {
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(false);
    expect(service.canActivate(route, state)).toBeFalse();
    expect(authService.redirectToLogin).toHaveBeenCalledOnceWith(
      '/workflows/7',
    );
  });

  it('renews an expired session silently and enforces requiredRoles', async () => {
    const roleRoute = {
      data: {requiredRoles: [UserRolesEnum.WORKFLOWS]},
    } as unknown as ActivatedRouteSnapshot;
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(of('fresh'));

    userRoles = [UserRolesEnum.WORKFLOWS];
    const allowed = service.canActivate(
      roleRoute,
      state,
    ) as Observable<boolean>;
    expect(await firstValueFrom(allowed)).toBeTrue();

    userRoles = [];
    const denied = service.canActivate(roleRoute, state) as Observable<boolean>;
    expect(await firstValueFrom(denied)).toBeFalse();
    expect(router.navigate).toHaveBeenCalledWith(['/']);
  });

  it('passes target state.url to onSessionRenewalFailed when renewal fails and hides loading indicator', async () => {
    const token$ = new Subject<string>();
    const loadingStates: boolean[] = [];
    const sub = loadingService.isLoading$.subscribe(v => loadingStates.push(v));
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(
      token$.asObservable(),
    );

    const resultPromise = firstValueFrom(
      service.canActivate(route, state) as Observable<boolean>,
    );
    expect(loadingStates[loadingStates.length - 1]).toBeTrue();

    token$.error(new Error('silent sign-in failed'));
    expect(await resultPromise).toBeFalse();
    expect(loadingStates[loadingStates.length - 1]).toBeFalse();
    expect(authService.onSessionRenewalFailed).toHaveBeenCalledOnceWith(
      '/workflows/7',
      jasmine.any(Error),
    );
    sub.unsubscribe();
  });

  it('shows and clears the loading indicator around successful silent renewal', async () => {
    const token$ = new Subject<string>();
    const loadingStates: boolean[] = [];
    const sub = loadingService.isLoading$.subscribe(v => loadingStates.push(v));
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(
      token$.asObservable(),
    );

    const resultPromise = firstValueFrom(
      service.canActivate(route, state) as Observable<boolean>,
    );
    expect(loadingStates[loadingStates.length - 1]).toBeTrue();

    token$.next('fresh-token');
    token$.complete();
    expect(await resultPromise).toBeTrue();
    expect(loadingStates[loadingStates.length - 1]).toBeFalse();
    sub.unsubscribe();
  });
});
