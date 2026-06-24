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
import {AuthService} from './common/services/auth.service';
import {environment} from '../environments/environment';

@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  constructor(private authService: AuthService) {}

  intercept(
    request: HttpRequest<unknown>,
    next: HttpHandler,
  ): Observable<HttpEvent<unknown>> {
    let authorizedRequest = request;
    
    // Only attach credentials to our backend
    if (request.url.startsWith(environment.backendURL) || request.url.includes('/api/')) {
      authorizedRequest = request.clone({ withCredentials: true });
    }
    
    return next.handle(authorizedRequest).pipe(
      catchError(error => {
        // If we receive a 401 Unauthorized from the backend, our HttpOnly session
        // cookie has likely expired or is invalid. We log the user out.
        if (error instanceof HttpErrorResponse && error.status === 401) {
          console.error('AuthInterceptor: Session expired (401). Logging out.');
          void this.authService.logout();
        }
        return throwError(() => error);
      }),
    );
  }
}
