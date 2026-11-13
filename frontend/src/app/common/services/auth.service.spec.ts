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
import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import {Router} from '@angular/router';
import {Auth} from '@angular/fire/auth';
import {Observable} from 'rxjs';
import {environment} from '../../../environments/environment';
import {UserModel, UserRolesEnum} from '../models/user.model';
import {AuthService} from './auth.service';
import {UserService} from './user.service';

describe('AuthService', () => {
  let service: AuthService;
  let httpMock: HttpTestingController;
  let routerSpy: {
    url: string;
    navigate: jasmine.Spy;
    navigateByUrl: jasmine.Spy;
  };
  let authSpy: {signOut: jasmine.Spy};

  beforeEach(() => {
    localStorage.removeItem('firebase_session');
    localStorage.removeItem('USER_DETAILS');
    localStorage.removeItem('showTooltip');

    routerSpy = {
      url: '/admin/dashboard',
      navigate: jasmine
        .createSpy('navigate')
        .and.returnValue(Promise.resolve(true)),
      navigateByUrl: jasmine
        .createSpy('navigateByUrl')
        .and.returnValue(Promise.resolve(true)),
    };
    authSpy = {
      signOut: jasmine.createSpy('signOut').and.returnValue(Promise.resolve()),
    };

    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        AuthService,
        {provide: Router, useValue: routerSpy},
        {provide: UserService, useValue: {}},
        {provide: Auth, useValue: authSpy},
      ],
    });
    service = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.removeItem('firebase_session');
    localStorage.removeItem('USER_DETAILS');
    localStorage.removeItem('showTooltip');
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should decode JWT payload with Base64URL and UTF-8 characters correctly', () => {
    const base64UrlPayload =
      'eyJuYW1lIjoiVG9tYXN6IMWad2l0b8WEIiwic3ViIjoiMTIzLTQ1Nl83ODkifQ';
    const fakeToken = `header.${base64UrlPayload}.signature`;

    const decoded = service.decodeJwtPayload(fakeToken);
    expect(decoded.name).toEqual('Tomasz Świtoń');
    expect(decoded.sub).toEqual('123-456_789');
  });

  it('should throw an error for invalid JWT structure', () => {
    expect(() =>
      service.decodeJwtPayload('invalid_token_without_dots'),
    ).toThrow(new Error('Invalid JWT token'));
  });

  it('emits sessionChanged$ and stores USER_DETAILS on syncUserWithBackend$ success', () => {
    let emissions = 0;
    const sub = service.sessionChanged$.subscribe(() => emissions++);
    const mockUser: UserModel = {
      id: 1,
      email: 'admin@example.com',
      name: 'Admin',
      roles: [UserRolesEnum.ADMIN],
    };

    let synced: UserModel | undefined;
    const internalAuth = service as unknown as {
      syncUserWithBackend$: (token: string) => Observable<UserModel>;
    };
    internalAuth
      .syncUserWithBackend$('fake-token')
      .subscribe(user => (synced = user));

    const req = httpMock.expectOne(`${environment.backendURL}/users/me`);
    expect(req.request.method).toBe('GET');
    expect(req.request.headers.get('Authorization')).toBe('Bearer fake-token');
    req.flush(mockUser);

    expect(synced).toEqual(mockUser);
    expect(emissions).toBe(1);
    expect(localStorage.getItem('USER_DETAILS')).toBe(JSON.stringify(mockUser));
    sub.unsubscribe();
  });

  it('emits sessionChanged$ on logout() success', async () => {
    localStorage.setItem(
      'firebase_session',
      JSON.stringify({token: 'tok', expiry: Date.now() + 60_000}),
    );
    localStorage.setItem('USER_DETAILS', JSON.stringify({email: 'a@b.com'}));

    let emissions = 0;
    const sub = service.sessionChanged$.subscribe(() => emissions++);

    await service.logout('/login');

    expect(emissions).toBe(1);
    expect(localStorage.getItem('firebase_session')).toBeNull();
    expect(localStorage.getItem('USER_DETAILS')).toBeNull();
    expect(routerSpy.navigateByUrl).toHaveBeenCalledWith('/login');
    sub.unsubscribe();
  });

  it('emits sessionChanged$ on logout() error', async () => {
    spyOn(console, 'error');
    authSpy.signOut.and.returnValue(Promise.reject(new Error('network')));
    localStorage.setItem(
      'firebase_session',
      JSON.stringify({token: 'tok', expiry: Date.now() + 60_000}),
    );
    localStorage.setItem('USER_DETAILS', JSON.stringify({email: 'a@b.com'}));

    let emissions = 0;
    const sub = service.sessionChanged$.subscribe(() => emissions++);

    await service.logout();

    expect(emissions).toBe(1);
    expect(localStorage.getItem('firebase_session')).toBeNull();
    expect(localStorage.getItem('USER_DETAILS')).toBeNull();
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/login']);
    sub.unsubscribe();
  });

  it('emits sessionChanged$ once when in-memory token expires in isLoggedIn()', () => {
    localStorage.setItem(
      'firebase_session',
      JSON.stringify({token: 'expired-tok', expiry: Date.now() + 60_000}),
    );
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        AuthService,
        {provide: Router, useValue: routerSpy},
        {provide: UserService, useValue: {}},
        {provide: Auth, useValue: authSpy},
      ],
    });
    const freshService = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);

    let emissions = 0;
    const sub = freshService.sessionChanged$.subscribe(() => emissions++);

    const spyNow = spyOn(Date, 'now').and.returnValue(Date.now() + 120_000);
    expect(freshService.isLoggedIn()).toBeFalse();
    expect(emissions).toBe(1);
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/login']);

    // Subsequent check with cleared token should not re-emit
    expect(freshService.isLoggedIn()).toBeFalse();
    expect(emissions).toBe(1);

    spyNow.and.callThrough();
    sub.unsubscribe();
  });
});
