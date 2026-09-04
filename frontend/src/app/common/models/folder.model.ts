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

export interface Folder {
  id: number;
  workspaceId: number;
  userId?: number;
  userEmail: string;
  name: string;
  parentId?: number | null;
  color?: string | null;
  itemCount: number;
  subfolderCount: number;
  createdAt?: string;
  updatedAt?: string;
}

export interface FolderBreadcrumb {
  id: number;
  name: string;
  parentId?: number | null;
}

export interface FolderTreeNode {
  id: number;
  name: string;
  parentId?: number | null;
  color?: string | null;
  children: FolderTreeNode[];
}

export interface CreateFolderDto {
  name: string;
  workspaceId: number;
  parentId?: number | null;
  color?: string | null;
}

export interface UpdateFolderDto {
  name?: string;
  parentId?: number | null;
  color?: string | null;
}

export interface MoveItemsDto {
  workspaceId: number;
  mediaItemIds?: number[];
  sourceAssetIds?: number[];
  folderIds?: number[];
  destinationFolderId?: number | null;
}

export interface GalleryDragPayload {
  mediaItemIds: number[];
  sourceAssetIds: number[];
  folderIds?: number[];
  itemCount: number;
}
