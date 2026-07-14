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
import {environment} from '../../../environments/environment';

export interface TagModel {
  id: number;
  name: string;
  workspaceId: number;
  color?: string;
}

export interface PaginationResponseDto<T> {
  data: T[];
  count: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

@Injectable({
  providedIn: 'root',
})
export class TagsService {
  private apiUrl = `${environment.backendURL}/tags`;

  constructor(private http: HttpClient) {}

  getTags(
    workspaceId: number,
    search?: string,
    page = 1,
    pageSize = 10,
    userId?: number,
  ): Observable<PaginationResponseDto<TagModel>> {
    const url = `${this.apiUrl}/search`;
    const body: any = {
      workspace_id: workspaceId,
      search: search,
      limit: pageSize,
      offset: (page - 1) * pageSize,
    };
    if (userId) {
      body.user_id = userId;
    }
    return this.http.post<PaginationResponseDto<TagModel>>(url, body);
  }

  createTag(
    workspaceId: number,
    name: string,
    color?: string,
  ): Observable<TagModel> {
    return this.http.post<TagModel>(`${this.apiUrl}`, {
      name,
      workspace_id: workspaceId,
      color,
    });
  }

  deleteTag(workspaceId: number, tagId: number): Observable<any> {
    return this.http.delete<any>(
      `${this.apiUrl}/${tagId}?workspace_id=${workspaceId}`,
    );
  }

  updateTag(
    workspaceId: number,
    tagId: number,
    name?: string,
    color?: string,
  ): Observable<TagModel> {
    const body: any = {};
    if (name) body.name = name;
    if (color) body.color = color;
    return this.http.put<TagModel>(
      `${this.apiUrl}/${tagId}?workspace_id=${workspaceId}`,
      body,
    );
  }

  bulkAssign(
    workspaceId: number,
    itemIds: number[],
    itemType: string,
    tagNames: string[],
  ): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/bulk-assign`, {
      workspace_id: workspaceId,
      item_ids: itemIds,
      item_type: itemType,
      tag_names: tagNames,
    });
  }
}
