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
  HttpClient,
  HttpHeaders,
  HttpErrorResponse,
  HttpParams,
} from '@angular/common/http';
import {Observable, throwError} from 'rxjs';
import {catchError, tap} from 'rxjs/operators';
import {environment} from '../../../environments/environment'; // To get backendURL
import {UserModel} from '../../common/models/user.model';

export interface PaginatedResponse {
  count: number;
  data: UserModel[];
  page: number;
  pageSize: number;
  totalPages: number;
}

@Injectable({
  providedIn: 'root',
})
export class UserService {
  private usersApiUrl = `${environment.backendURL}/users`;

  private httpOptions = {
    headers: new HttpHeaders({
      'Content-Type': 'application/json',
    }),
  };

  constructor(private http: HttpClient) {}

  // GET: Fetch all users
  getUsers(
    limit: number,
    filter: string,
    offset?: number,
    includeDeleted = false,
  ): Observable<PaginatedResponse> {
    let params = new HttpParams()
      .set('limit', limit.toString())
      .set('email', filter);

    if (includeDeleted) {
      params = params.set('includeDeleted', 'true');
    }

    if (offset !== undefined) params = params.set('offset', offset.toString());

    return this.http
      .get<PaginatedResponse>(this.usersApiUrl, {params, ...this.httpOptions})
      .pipe(catchError(this.handleError));
  }

  // GET: Fetch a single user by ID
  getUser(id: number | string): Observable<UserModel> {
    const url = `${this.usersApiUrl}/${id}`;
    return this.http
      .get<UserModel>(url, this.httpOptions)
      .pipe(catchError(this.handleError));
  }

  // POST: Add a new user
  addUser(user: UserModel): Observable<UserModel> {
    return this.http
      .post<UserModel>(this.usersApiUrl, user, this.httpOptions)
      .pipe(catchError(this.handleError));
  }

  // PUT: Update an existing user
  updateUser(user: UserModel): Observable<any> {
    const url = `${this.usersApiUrl}/${user.id}`;
    const payload = {roles: user.roles};
    return this.http
      .put(url, payload, this.httpOptions)
      .pipe(catchError(this.handleError));
  }

  // DELETE: Delete a user
  deleteUser(id: number | string): Observable<UserModel> {
    const url = `${this.usersApiUrl}/${id}`;
    return this.http
      .delete<UserModel>(url, this.httpOptions)
      .pipe(catchError(this.handleError));
  }

  // POST: Restore a deleted user
  restoreUser(id: number | string): Observable<UserModel> {
    const url = `${this.usersApiUrl}/${id}/restore`;
    return this.http
      .post<UserModel>(url, {}, this.httpOptions)
      .pipe(catchError(this.handleError));
  }

  // Basic error handling
  private handleError(error: HttpErrorResponse) {
    let errorMessage = 'An unknown error occurred!';
    if (error.error instanceof HttpErrorResponse) {
      errorMessage = `Error: ${error.error.message}`;
    } else {
      errorMessage = `Error Code: ${error.status}\nMessage: ${error.message}`;
      if (
        error.error &&
        typeof error.error === 'object' &&
        error.error.detail
      ) {
        errorMessage += `\nDetails: ${error.error.detail}`;
      } else if (error.error) {
        errorMessage += `\nBackend Error: ${JSON.stringify(error.error)}`;
      }
    }
    console.error(errorMessage);
    return throwError(() => new Error(errorMessage));
  }
}
