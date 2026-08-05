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
  HttpRequest,
  HttpHandler,
  HttpEvent,
  HttpInterceptor,
  HttpErrorResponse,
} from '@angular/common/http';
import {Observable, throwError} from 'rxjs';
import {catchError, switchMap} from 'rxjs/operators';
import {AuthService, SessionExpiredError} from './common/services/auth.service';
import {environment} from '../environments/environment';

@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  constructor(private authService: AuthService) {}

  intercept(
    request: HttpRequest<unknown>,
    next: HttpHandler,
  ): Observable<HttpEvent<unknown>> {
    // Asynchronously get a valid token. This will use the cache or trigger a silent refresh.
    return this.authService.getValidIdentityPlatformToken$().pipe(
      switchMap(token => {
        // Token was retrieved successfully. Clone the request and add the auth header.
        const authorizedRequest = request.clone({
          setHeaders: {Authorization: `Bearer ${token}`},
        });
        return next.handle(authorizedRequest);
      }),
      catchError(error => {
        // Sign out only when the session is genuinely unrecoverable.
        //
        // This used to log out on any error that was not an HttpErrorResponse,
        // which is far broader than intended: a dropped connection or a DNS
        // hiccup during token refresh is not an HttpErrorResponse either, so a
        // brief loss of connectivity would end the session with no explanation.
        if (error instanceof SessionExpiredError) {
          console.error('AuthInterceptor: %s Logging out.', error.message);
          void this.authService.logout();
        }

        // Everything else - backend errors and transport failures alike - is
        // passed through for the calling service to surface. The session stays.
        return throwError(() => error);
      }),
    );
  }
}
