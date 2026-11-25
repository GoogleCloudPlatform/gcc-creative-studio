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

import {PromotionSummary} from './media-item.model';
import {PaginatedResponse} from './paginated-response.model';
import {TagModel} from '../services/tags.service';

export type {PromotionSummary};

export interface BulkCopyItem {
  id: number;
  type: string;
}

export interface PromoteTargetWorkspace {
  workspaceId: number;
  workspaceName: string;
  scope: string;
  currentUserRole?: string | null;
  existingCount: number;
  newCount: number;
  existingPromotion?: PromotionSummary | null;
}

export interface PromoteItemsRequest {
  items: BulkCopyItem[];
  sourceWorkspaceId: number;
  targetWorkspaceId: number;
  targetFolderId?: number | null;
  clearTargetFolder?: boolean;
  mode?: 'update_or_create' | 'create_new';
}

export interface PromoteResultItem {
  sourceId: number;
  sourceType: string;
  targetId: number;
  targetWorkspaceId: number;
  targetFolderId?: number | null;
  action: string;
}

export interface PromoteResponse {
  promotedCount: number;
  updatedCount: number;
  createdCount: number;
  targetWorkspaceId: number;
  targetFolderId?: number | null;
  promotedItems: PromoteResultItem[];
}

export interface BaseGalleryItem {
  id: number;
  workspaceId: number;
  workspaceName?: string;
  workspaceScope?: string;
  folderId?: number;
  userId?: number;
  createdAt: string;
  status?: string;
  deletedAt?: string;
  tags?: TagModel[];

  revisionRootId?: number | null;
  revisionParentId?: number | null;
  revisionNumber?: number;
  revisionCount?: number;
  isLatestRevision?: boolean;
  promotedFromMediaItemId?: number | null;
  promotedFromRootId?: number | null;
  promotions?: PromotionSummary[];

  // Display fields
  titles?: string[];
  descriptions?: string[];
  mimeType?: string;
  aspectRatio?: string;
  prompt?: string;
  originalPrompt?: string;

  // Unified arrays
  gcsUris?: string[];
  originalGcsUris?: string[];
  thumbnailUris?: string[];

  // Presigned URLs (injected by service)
  presignedUrls?: string[];
  originalPresignedUrls?: string[];
  presignedThumbnailUrls?: string[];

  errorMessage?: string;

  // Flat fields for backwards compatibility with older components
  enrichedSourceAssets?: any[];
  enrichedSourceMediaItems?: any[];
  model?: string;
  userEmail?: string;
  userPicture?: string;

  generationTime?: number;
  voiceName?: string;
  languageCode?: string;
  seed?: number;
  numMedia?: number;
  duration?: number;
  resolution?: string;
  googleSearch?: boolean;
  groundingMetadata?: any;
  rewrittenPrompt?: string;
  negativePrompt?: string;
  style?: string;
  lighting?: string;
  colorAndTone?: string;
  composition?: string;
  modifiers?: string[];
  comment?: string;
  critique?: string;
  rawData?: any;
  audioAnalysis?: any;
  addWatermark?: boolean;
}

export interface MediaItemMetadata {
  tags?: string[];
  titles?: string[];
  descriptions?: string[];
  model?: string;
  style?: string;
  prompt?: string;
  isAudio?: boolean;
  isVideo?: boolean;
  lighting?: string;
  mimeType?: string;
  numMedia?: number;
  userEmail?: string;
  aspectRatio?: string;
  generationTime?: number;
  negativePrompt?: string;
  originalPrompt?: string;
  rewrittenPrompt?: string;
  googleSearch?: boolean;
  groundingMetadata?: any;
  enrichedSourceAssets?: any[];
  enrichedSourceMediaItems?: any[];
  style_modifiers?: string[];
  comment?: string;
  critique?: string;
  rawData?: any;
  audioAnalysis?: any;
  addWatermark?: boolean;
}

export interface SourceAssetMetadata {
  tags?: string[];
  titles?: string[];
  descriptions?: string[];
  isAudio?: boolean;
  isVideo?: boolean;
  mimeType?: string;
  assetType?: string;
  userEmail?: string;
  aspectRatio?: string;
  originalFilename?: string;
}

export interface MediaItemGallery extends BaseGalleryItem {
  itemType: 'media_item';
  metadata: MediaItemMetadata;
}

export interface SourceAssetGallery extends BaseGalleryItem {
  itemType: 'source_asset';
  metadata: SourceAssetMetadata;
}

export type GalleryItem = MediaItemGallery | SourceAssetGallery;
export type PaginatedGalleryResponse = PaginatedResponse<GalleryItem>;

export interface RevisionHistoryResponse {
  rootId: number;
  revisionCount: number;
  takes: GalleryItem[];
  promotions?: PromotionSummary[];
}
