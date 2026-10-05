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

import {Injectable, inject} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {Observable} from 'rxjs';
import {environment} from '../../../environments/environment';
import {
  StoryboardResponse,
  StoryboardUpdate,
  StoryboardUpdateResponse,
} from '../../common/models/workbench.model';

@Injectable({
  providedIn: 'root',
})
export class StoryboardService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.backendURL}/storyboards`;

  getStoryboard(storyboardId: number): Observable<StoryboardResponse> {
    return this.http.get<StoryboardResponse>(`${this.apiUrl}/${storyboardId}`);
  }

  getStoryboardForSession(
    workspaceId: number,
    sessionId: string,
  ): Observable<StoryboardResponse[]> {
    const url = `${this.apiUrl}?workspace_id=${workspaceId}&session_id=${sessionId}`;
    return this.http.get<StoryboardResponse[]>(url);
  }

  /**
   * Persists a human edit. The answer carries `agent_sync`, describing how
   * the Izumi session took the change (`synced`, `busy`, `rejected`, ...).
   */
  updateStoryboard(
    storyboardId: number,
    updateData: StoryboardUpdate,
  ): Observable<StoryboardUpdateResponse> {
    return this.http.put<StoryboardUpdateResponse>(
      `${this.apiUrl}/${storyboardId}`,
      updateData,
    );
  }
}
