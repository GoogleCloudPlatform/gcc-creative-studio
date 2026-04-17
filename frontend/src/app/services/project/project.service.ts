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

import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Observable} from 'rxjs';
import {
  StoryboardResponse,
  StoryboardCreate,
  StoryboardCreateResponse,
  StoryboardUpdate,
} from '../../common/models/storyboard.model';

@Injectable({
  providedIn: 'root',
})
export class ProjectService {
  private apiUrl = '/api/projects';

  constructor(private http: HttpClient) {}

  getProjects(workspaceId: number): Observable<StoryboardResponse[]> {
    return this.http.get<StoryboardResponse[]>(
      `${this.apiUrl}/?workspace_id=${workspaceId}`,
    );
  }

  getProject(projectId: number): Observable<StoryboardResponse> {
    return this.http.get<StoryboardResponse>(`${this.apiUrl}/${projectId}`);
  }

  createProject(data: StoryboardCreate): Observable<StoryboardCreateResponse> {
    return this.http.post<StoryboardCreateResponse>(`${this.apiUrl}/`, data);
  }

  updateProject(
    projectId: number,
    data: StoryboardUpdate,
  ): Observable<StoryboardResponse> {
    return this.http.put<StoryboardResponse>(
      `${this.apiUrl}/${projectId}`,
      data,
    );
  }

  deleteProject(projectId: number): Observable<any> {
    return this.http.delete<any>(`${this.apiUrl}/${projectId}`);
  }
}
