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
import {Observable, firstValueFrom, of, throwError} from 'rxjs';

import {AuthGuardService} from './auth.guard.service';
import {AuthService} from './auth.service';
import {UserService} from './user.service';

describe('AuthGuardService', () => {
  let service: AuthGuardService;
  let router: {navigate: jasmine.Spy};
  let authService: jasmine.SpyObj<AuthService>;

  const route = {data: {}} as unknown as ActivatedRouteSnapshot;
  const state = {} as RouterStateSnapshot;

  beforeEach(() => {
    router = {navigate: jasmine.createSpy('navigate')};
    authService = jasmine.createSpyObj<AuthService>('AuthService', [
      'isLoggedIn',
      'hasRenewableSession',
      'getValidIdentityPlatformToken$',
      'onSessionRenewalFailed',
    ]);
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        AuthGuardService,
        {provide: AuthService, useValue: authService},
        {provide: Router, useValue: router},
        {provide: UserService, useValue: {getUserDetails: () => null}},
      ],
    });
    service = TestBed.inject(AuthGuardService);
  });

  it('allows navigation with a valid session', () => {
    authService.isLoggedIn.and.returnValue(true);
    expect(service.canActivate(route, state)).toBeTrue();
  });

  it('redirects to login when there is no session', () => {
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(false);
    expect(service.canActivate(route, state)).toBeFalse();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });

  it('renews an expired session silently before allowing navigation', async () => {
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(of('fresh'));

    const result = service.canActivate(route, state) as Observable<boolean>;

    expect(await firstValueFrom(result)).toBeTrue();
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('hands a failed renewal to AuthService and blocks navigation', async () => {
    authService.isLoggedIn.and.returnValue(false);
    authService.hasRenewableSession.and.returnValue(true);
    authService.getValidIdentityPlatformToken$.and.returnValue(
      throwError(() => new Error('silent sign-in failed')),
    );

    const result = service.canActivate(route, state) as Observable<boolean>;

    expect(await firstValueFrom(result)).toBeFalse();
    expect(authService.onSessionRenewalFailed).toHaveBeenCalled();
  });
});
