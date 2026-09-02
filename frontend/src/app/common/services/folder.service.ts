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
import {environment} from '../../../environments/environment';
import {
  CreateFolderDto,
  Folder,
  FolderBreadcrumb,
  FolderTreeNode,
  MoveItemsDto,
  UpdateFolderDto,
} from '../models/folder.model';

@Injectable({
  providedIn: 'root',
})
export class FolderService {
  private readonly apiUrl = `${environment.backendURL}/folders`;

  constructor(private readonly http: HttpClient) {}

  getFolders(
    workspaceId: number,
    parentId?: number | null,
  ): Observable<Folder[]> {
    let params = new HttpParams().set('workspace_id', workspaceId.toString());
    if (parentId !== undefined && parentId !== null) {
      params = params.set('parent_id', parentId.toString());
    }
    return this.http.get<Folder[]>(this.apiUrl, {params});
  }

  getFolderTree(workspaceId: number): Observable<FolderTreeNode[]> {
    const params = new HttpParams().set('workspace_id', workspaceId.toString());
    return this.http.get<FolderTreeNode[]>(`${this.apiUrl}/tree`, {params});
  }

  getBreadcrumbs(
    folderId: number,
    workspaceId?: number,
  ): Observable<FolderBreadcrumb[]> {
    let params = new HttpParams();
    if (workspaceId !== undefined && workspaceId !== null) {
      params = params.set('workspace_id', workspaceId.toString());
    }
    return this.http.get<FolderBreadcrumb[]>(
      `${this.apiUrl}/${folderId}/breadcrumbs`,
      {params},
    );
  }

  getFolderById(folderId: number, workspaceId?: number): Observable<Folder> {
    let params = new HttpParams();
    if (workspaceId !== undefined && workspaceId !== null) {
      params = params.set('workspace_id', workspaceId.toString());
    }
    return this.http.get<Folder>(`${this.apiUrl}/${folderId}`, {params});
  }

  createFolder(dto: CreateFolderDto): Observable<Folder> {
    return this.http.post<Folder>(this.apiUrl, dto);
  }

  updateFolder(folderId: number, dto: UpdateFolderDto): Observable<Folder> {
    return this.http.patch<Folder>(`${this.apiUrl}/${folderId}`, dto);
  }

  deleteFolder(folderId: number): Observable<{success: boolean}> {
    return this.http.delete<{success: boolean}>(`${this.apiUrl}/${folderId}`);
  }

  moveItems(dto: MoveItemsDto): Observable<{total_moved: number}> {
    return this.http.post<{total_moved: number}>(
      `${this.apiUrl}/move-items`,
      dto,
    );
  }
}
