/**
 * Copyright 2026 Google LLC
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

import {HttpClient, HttpParams} from '@angular/common/http';
import {Injectable} from '@angular/core';
import {Observable} from 'rxjs';
import {environment} from '../../../../environments/environment';
import {
  Project,
  ProjectCreate,
  ProjectResolveQuery,
} from '../../../common/models/project.model';

@Injectable({
  providedIn: 'root',
})
export class ProjectService {
  constructor(private http: HttpClient) {}

  list(workspaceId: number): Observable<Project[]> {
    const params = new HttpParams().set('workspace_id', workspaceId.toString());
    return this.http.get<Project[]>(`${environment.backendURL}/projects`, {
      params,
    });
  }

  ensureDefault(workspaceId: number): Observable<Project> {
    const params = new HttpParams().set('workspace_id', workspaceId.toString());
    return this.http.post<Project>(
      `${environment.backendURL}/projects/default`,
      {},
      {params},
    );
  }

  get(id: number): Observable<Project> {
    return this.http.get<Project>(`${environment.backendURL}/projects/${id}`);
  }

  create(workspaceId: number, name: string): Observable<Project> {
    const body: ProjectCreate = {workspace_id: workspaceId, name};
    return this.http.post<Project>(`${environment.backendURL}/projects`, body);
  }

  rename(id: number, name: string): Observable<Project> {
    return this.http.patch<Project>(
      `${environment.backendURL}/projects/${id}`,
      {name},
    );
  }

  delete(id: number): Observable<void> {
    return this.http.delete<void>(`${environment.backendURL}/projects/${id}`);
  }

  resolve(query: ProjectResolveQuery): Observable<Project> {
    let params = new HttpParams();
    if ('session_id' in query) {
      params = params.set('session_id', query.session_id);
    } else if ('storyboard_id' in query) {
      params = params.set('storyboard_id', query.storyboard_id.toString());
    } else if ('timeline_id' in query) {
      params = params.set('timeline_id', query.timeline_id.toString());
    }
    return this.http.get<Project>(
      `${environment.backendURL}/projects/resolve`,
      {params},
    );
  }
}
