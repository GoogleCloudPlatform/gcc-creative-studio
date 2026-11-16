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

import {Injectable} from '@angular/core';
import {
  HttpContextToken,
  HttpErrorResponse,
  HttpEvent,
  HttpHandler,
  HttpInterceptor,
  HttpRequest,
} from '@angular/common/http';
import {EMPTY, Observable, throwError} from 'rxjs';
import {catchError, defaultIfEmpty, switchMap} from 'rxjs/operators';
import {AuthService} from './common/services/auth.service';
import {
  SessionSupersededError,
  UNAUTHORIZED_ORG_DETAIL,
  markSessionHandled,
  renewAfterUnauthorizedWithHandling$,
  toAuthRenewalError,
} from './common/services/auth-token.utils';
import {environment} from '../environments/environment';

const RETRIED_AFTER_401 = new HttpContextToken<boolean>(() => false);

@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  constructor(private authService: AuthService) {}

  intercept(
    request: HttpRequest<unknown>,
    next: HttpHandler,
  ): Observable<HttpEvent<unknown>> {
    const isBackendUrl =
      (request.url.startsWith('/') && !request.url.startsWith('//')) ||
      (environment.backendURL.startsWith('http') &&
        request.url.startsWith(environment.backendURL));
    if (!isBackendUrl || request.headers.has('Authorization')) {
      return next.handle(request);
    }

    return this.authService.getValidIdentityPlatformToken$().pipe(
      defaultIfEmpty(null),
      switchMap(token => {
        if (!token) {
          return EMPTY;
        }
        const authorizedRequest = request.clone({
          setHeaders: {Authorization: `Bearer ${token}`},
        });
        return next.handle(authorizedRequest).pipe(
          catchError(httpError => {
            if (this.shouldRetryUnauthorized(httpError, request)) {
              return this.retryAfterUnauthorized(
                request,
                next,
                token,
                httpError,
              );
            }
            return throwError(() => httpError);
          }),
        );
      }),
      catchError(error => {
        // Non-HTTP errors come from session renewal failures in AuthService.
        if (!(error instanceof HttpErrorResponse)) {
          const renewalError = toAuthRenewalError(error);
          if (!(renewalError instanceof SessionSupersededError)) {
            console.error(
              'AuthInterceptor: Session expired and could not be renewed.',
              renewalError.message,
            );
          }
          this.authService.onSessionRenewalFailed(undefined, renewalError);
          return throwError(() => markSessionHandled(renewalError));
        }
        return throwError(() => error);
      }),
    );
  }

  private shouldRetryUnauthorized(
    error: unknown,
    request: HttpRequest<unknown>,
  ): error is HttpErrorResponse {
    if (!(error instanceof HttpErrorResponse) || error.status !== 401) {
      return false;
    }
    if (request.context.get(RETRIED_AFTER_401)) {
      return false;
    }
    return error.error?.detail !== UNAUTHORIZED_ORG_DETAIL;
  }

  private retryAfterUnauthorized(
    request: HttpRequest<unknown>,
    next: HttpHandler,
    rejectedToken: string,
    original401: HttpErrorResponse,
  ): Observable<HttpEvent<unknown>> {
    return renewAfterUnauthorizedWithHandling$(
      this.authService,
      rejectedToken,
      'AuthInterceptor: Session renewal after 401 failed.',
    ).pipe(
      catchError(() => throwError(() => markSessionHandled(original401))),
      switchMap(freshToken => {
        const retried = request.clone({
          setHeaders: {Authorization: `Bearer ${freshToken}`},
          context: request.context.set(RETRIED_AFTER_401, true),
        });
        return next.handle(retried).pipe(
          catchError((retryErr: unknown) => {
            if (
              retryErr instanceof HttpErrorResponse &&
              retryErr.status === 401
            ) {
              this.authService.recordRejectedRenewedToken(freshToken);
            }
            return throwError(() => retryErr);
          }),
        );
      }),
    );
  }
}
