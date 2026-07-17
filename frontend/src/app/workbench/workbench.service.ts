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
import {environment} from '../../environments/environment';
import {TimelineDTO} from '../common/models/workbench.model';
import {MediaItem} from '../common/models/media-item.model';

export interface RenderTimelineRequest {
  timeline_id: number;
  output_filename?: string;
}

@Injectable({
  providedIn: 'root',
})
export class WorkbenchService {
  private apiUrl = `${environment.backendURL}/workbench`;

  constructor(private http: HttpClient) {}

  renderVideo(request: RenderTimelineRequest): Observable<MediaItem> {
    return this.http.post<MediaItem>(`${this.apiUrl}/render`, request);
  }

  getTimeline(timelineId: number | string): Observable<TimelineDTO> {
    return this.http.get<TimelineDTO>(`${this.apiUrl}/timelines/${timelineId}`);
  }

  updateTimeline(
    timelineId: number | string,
    timeline: TimelineDTO,
  ): Observable<TimelineDTO> {
    return this.http.put<TimelineDTO>(
      `${this.apiUrl}/timelines/${timelineId}`,
      timeline,
    );
  }
}
