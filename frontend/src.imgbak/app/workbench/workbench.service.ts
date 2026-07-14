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

export interface Clip {
  assetId: string;
  url: string;
  startTime: number;
  duration: number;
  offset: number;
  trackIndex: number;
  type: 'video' | 'audio';
}

export interface TimelineRequest {
  clips: Clip[];
  output_format?: string;
  width?: number;
  height?: number;
}

@Injectable({
  providedIn: 'root',
})
export class WorkbenchService {
  private apiUrl = `${environment.backendURL}/workbench`;

  constructor(private http: HttpClient) {}

  renderVideo(request: TimelineRequest): Observable<Blob> {
    return this.http.post(`${this.apiUrl}/render`, request, {
      responseType: 'blob',
    });
  }
}
