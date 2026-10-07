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
  HTTP_INTERCEPTORS,
  HttpClient,
  provideHttpClient,
  withInterceptorsFromDi,
} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import {AuthInterceptor} from './auth.interceptor';
import {AuthService} from './common/services/auth.service';

describe('AuthInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authService: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    authService = jasmine.createSpyObj<AuthService>('AuthService', ['logout']);
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
        {provide: HTTP_INTERCEPTORS, useClass: AuthInterceptor, multi: true},
        {provide: AuthService, useValue: authService},
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('sends credentials with backend API requests', () => {
    http.get('/api/users/me').subscribe();

    const req = httpMock.expectOne('/api/users/me');
    expect(req.request.withCredentials).toBeTrue();
    req.flush({});
  });

  // A 401 means the backend refused this user. Logging out sends the browser
  // through IAP, which signs the same user straight back in, so the page
  // reloads forever. The error must reach the page instead.
  it('passes a 401 to the caller without logging the user out', () => {
    let status = 0;
    http.get('/api/users/me').subscribe({error: e => (status = e.status)});

    httpMock
      .expectOne('/api/users/me')
      .flush('Not allowed', {status: 401, statusText: 'Unauthorized'});

    expect(status).toBe(401);
    expect(authService.logout).not.toHaveBeenCalled();
  });
});
