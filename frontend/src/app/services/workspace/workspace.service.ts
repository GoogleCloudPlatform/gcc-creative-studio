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

import {Inject, Injectable, PLATFORM_ID} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {HttpClient} from '@angular/common/http';
import {Observable, throwError} from 'rxjs';
import {catchError, shareReplay, tap} from 'rxjs/operators';
import {environment} from '../../../environments/environment';
import {WorkspaceRole} from '../../common/models/workspace-member.model';
import {Workspace} from '../../common/models/workspace.model';
import {UserService} from '../../common/services/user.service';

const WORKSPACE_CACHE_TTL_MS = 30_000;

@Injectable({
  providedIn: 'root',
})
export class WorkspaceService {
  private apiUrl = `${environment.backendURL}/workspaces`;
  private cachedWorkspaces$: Observable<Workspace[]> | null = null;
  private cachedUserKey: string | null = null;
  private cacheExpiresAt = 0;

  constructor(
    private http: HttpClient,
    @Inject(PLATFORM_ID) private platformId: object,
    private userService: UserService,
  ) {}

  getWorkspaces(): Observable<Workspace[]> {
    if (!isPlatformBrowser(this.platformId)) {
      return this.http.get<Workspace[]>(this.apiUrl);
    }

    const userKey = this.getCacheScopeKey();
    if (!userKey) {
      this.clearCache();
      return this.http.get<Workspace[]>(this.apiUrl);
    }

    const now = Date.now();
    const isCacheValid =
      this.cachedWorkspaces$ !== null &&
      this.cachedUserKey === userKey &&
      now < this.cacheExpiresAt;

    if (!isCacheValid) {
      this.cachedUserKey = userKey;
      this.cacheExpiresAt = now + WORKSPACE_CACHE_TTL_MS;
      const request$: Observable<Workspace[]> = this.http
        .get<Workspace[]>(this.apiUrl)
        .pipe(
          tap(() => {
            if (this.cachedWorkspaces$ === request$) {
              this.cacheExpiresAt = Date.now() + WORKSPACE_CACHE_TTL_MS;
            }
          }),
          catchError(err => {
            if (this.cachedWorkspaces$ === request$) {
              this.clearCache();
            }
            return throwError(() => err);
          }),
          shareReplay({bufferSize: 1, refCount: false}),
        );
      this.cachedWorkspaces$ = request$;
    }

    return this.cachedWorkspaces$!;
  }

  clearCache(): void {
    this.cachedWorkspaces$ = null;
    this.cachedUserKey = null;
    this.cacheExpiresAt = 0;
  }

  createWorkspace(name: string): Observable<Workspace> {
    return this.http
      .post<Workspace>(this.apiUrl, {name})
      .pipe(tap(() => this.clearCache()));
  }

  inviteUser(
    workspaceId: number,
    email: string,
    role: WorkspaceRole,
  ): Observable<void> {
    return this.http
      .post<void>(`${this.apiUrl}/${workspaceId}/invites`, {
        email,
        role,
      })
      .pipe(tap(() => this.clearCache()));
  }

  private getCacheScopeKey(): string | null {
    try {
      const user = this.userService.getUserDetails() as {
        email?: string;
        id?: number | string;
      } | null;
      if (user?.email) {
        return `user:${user.email}`;
      }
      if (user?.id !== undefined && user?.id !== null) {
        return `user:${user.id}`;
      }
      return null;
    } catch {
      return null;
    }
  }
}
