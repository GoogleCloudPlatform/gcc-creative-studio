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

import {HttpClient} from '@angular/common/http';
import {Injectable, OnDestroy} from '@angular/core';
import {
  BehaviorSubject,
  combineLatest,
  Observable,
  of,
  Subscription,
} from 'rxjs';
import {
  catchError,
  debounceTime,
  shareReplay,
  switchMap,
  map,
} from 'rxjs/operators';
import {environment} from '../../environments/environment';
import {MediaItem} from '../common/models/media-item.model';
import {
  GalleryItem,
  PaginatedGalleryResponse,
} from '../common/models/gallery-item.model';
import {
  GalleryFiltersState,
  GallerySearchDto,
} from '../common/models/search.model';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';

@Injectable({
  providedIn: 'root',
})
export class GalleryService implements OnDestroy {
  private imagesCache$ = new BehaviorSubject<GalleryItem[]>([]);
  public isLoading$ = new BehaviorSubject<boolean>(false);
  private allImagesLoaded$ = new BehaviorSubject<boolean>(false);
  private currentPage = 0;
  private pageSize = 40;
  private allFetchedImages: GalleryItem[] = [];
  private filters$ = new BehaviorSubject<GallerySearchDto | null>(null);
  private uiFiltersState: GalleryFiltersState | null = null;
  private dataLoadingSubscription: Subscription;

  constructor(
    private http: HttpClient,
    private workspaceStateService: WorkspaceStateService,
  ) {
    this.dataLoadingSubscription = combineLatest([
      this.workspaceStateService.activeWorkspaceId$,
      this.filters$,
    ])
      .pipe(
        debounceTime(50),
        switchMap(([workspaceId, filters]) => {
          if (!filters) {
            return of(null);
          }
          this.isLoading$.next(true);
          this.resetCache();

          const body: GallerySearchDto = {
            ...filters,
            workspaceId: workspaceId || undefined,
          };

          return this.fetchImages(body).pipe(
            catchError(err => {
              console.error('Failed to fetch gallery images', err);
              this.isLoading$.next(false);
              this.allImagesLoaded$.next(true);
              return of(null);
            }),
          );
        }),
      )
      .subscribe(response => {
        if (response) {
          this.processFetchResponse(response);
        }
      });
  }

  get images$(): Observable<GalleryItem[]> {
    return this.imagesCache$.asObservable();
  }

  get allImagesLoaded(): Observable<boolean> {
    return this.allImagesLoaded$.asObservable();
  }

  ngOnDestroy() {
    this.dataLoadingSubscription.unsubscribe();
  }

  setFilters(filters: GallerySearchDto) {
    this.filters$.next(filters);
  }

  loadGallery(reset = false): void {
    if (this.isLoading$.value) {
      return;
    }

    if (reset) {
      this.resetCache();
    }

    if (this.allImagesLoaded$.value) {
      return;
    }

    const body: GallerySearchDto = {
      ...this.filters$.value,
      workspaceId:
        this.workspaceStateService.getActiveWorkspaceId() || undefined,
      offset: this.currentPage * this.pageSize,
      limit: this.pageSize,
    };

    this.fetchImages(body)
      .pipe(
        catchError(err => {
          console.error('Failed to fetch gallery images', err);
          this.isLoading$.next(false);
          this.allImagesLoaded$.next(true);
          return of(null);
        }),
      )
      .subscribe(response => {
        if (response) {
          this.processFetchResponse(response, true);
        }
      });
  }

  public fetchImages(
    body: GallerySearchDto,
  ): Observable<PaginatedGalleryResponse> {
    this.isLoading$.next(true);

    const galleryUrl = `${environment.backendURL}/gallery/search`;
    return this.http
      .post<PaginatedGalleryResponse>(galleryUrl, body)
      .pipe(shareReplay(1));
  }

  private resetCache() {
    this.allFetchedImages = [];
    this.currentPage = 0;
    this.allImagesLoaded$.next(false);
    this.imagesCache$.next([]);
  }

  private processFetchResponse(
    response: PaginatedGalleryResponse,
    append = false,
  ) {
    this.currentPage++;
    this.allFetchedImages = append
      ? [...this.allFetchedImages, ...this.mapUnifiedResponse(response.data)]
      : this.mapUnifiedResponse(response.data);
    this.imagesCache$.next(this.allFetchedImages);

    if (this.currentPage >= response.totalPages) {
      this.allImagesLoaded$.next(true);
    }
    this.isLoading$.next(false);
  }

  getMedia(id: number): Observable<GalleryItem> {
    const detailUrl = `${environment.backendURL}/gallery/item/${id}`;
    return this.http
      .get<any>(detailUrl)
      .pipe(
        map(response =>
          this.mapUnifiedItem({...response, itemType: 'media_item'}),
        ),
      );
  }

  getAsset(id: number): Observable<GalleryItem> {
    const assetUrl = `${environment.backendURL}/source_assets/${id}`;
    return this.http.get<any>(assetUrl).pipe(
      map(asset => {
        const item = {
          ...asset,
          itemType: 'source_asset',
          gcsUris:
            asset.gcsUris ||
            (asset.gcsUri
              ? [asset.gcsUri]
              : asset.gcs_uri
                ? [asset.gcs_uri]
                : []),
          thumbnailUris:
            asset.thumbnailUris ||
            (asset.thumbnailGcsUri
              ? [asset.thumbnailGcsUri]
              : asset.thumbnail_gcs_uri
                ? [asset.thumbnail_gcs_uri]
                : []),
          presignedUrls:
            asset.presignedUrls ||
            (asset.presignedUrl
              ? [asset.presignedUrl]
              : asset.presigned_url
                ? [asset.presigned_url]
                : []),
          presignedThumbnailUrls:
            asset.presignedThumbnailUrls ||
            (asset.presignedThumbnailUrl
              ? [asset.presignedThumbnailUrl]
              : asset.presigned_thumbnail_url
                ? [asset.presigned_thumbnail_url]
                : []),
          metadata: asset.metadata || {
            assetType: asset.assetType || asset.asset_id || asset.asset_type,
            original_filename: asset.filename || asset.original_filename,
            mime_type: asset.mimeType || asset.mime_type,
          },
        };
        return this.mapUnifiedItem(item);
      }),
    );
  }

  private mapUnifiedResponse(data: any[]): GalleryItem[] {
    return data.map(item => this.mapUnifiedItem(item));
  }

  public mapUnifiedItem(item: any): GalleryItem {
    const metadata = item.metadata || {};
    const galleryItem: GalleryItem = {
      id: item.id,
      tags: item.tags,
      workspaceId: item.workspaceId,
      userId: item.userId,
      createdAt: item.createdAt,
      itemType: item.itemType || 'media_item',
      status: item.status,
      gcsUris: item.gcsUris,
      thumbnailUris: item.thumbnailUris,
      presignedUrls: item.presignedUrls,
      presignedThumbnailUrls: item.presignedThumbnailUrls,
      metadata: metadata,
      mimeType: metadata.mimeType || metadata.mime_type || item.mimeType,
      aspectRatio:
        metadata.aspectRatio || metadata.aspect_ratio || item.aspectRatio,
      prompt:
        item.prompt ||
        metadata.prompt ||
        metadata.originalFilename ||
        metadata.original_filename ||
        'Asset',
      originalPrompt:
        item.originalPrompt ||
        metadata.originalPrompt ||
        metadata.original_prompt ||
        metadata.originalFilename ||
        metadata.original_filename ||
        'Asset',
      model: item.model || metadata.model,
      userEmail:
        item.userEmail ||
        item.user_email ||
        metadata.userEmail ||
        metadata.user_email,
      userPicture: item.userPicture || item.user_picture,

      generationTime:
        item.generationTime ||
        metadata.generationTime ||
        metadata.generation_time,
      voiceName: item.voiceName || metadata.voiceName || metadata.voice_name,
      languageCode:
        item.languageCode || metadata.languageCode || metadata.language_code,
      seed: item.seed || metadata.seed,
      numMedia: item.numMedia || metadata.numMedia || metadata.num_media,
      duration: item.duration || metadata.duration,
      resolution: item.resolution || metadata.resolution,
      googleSearch:
        item.googleSearch ?? metadata.googleSearch ?? metadata.google_search,
      groundingMetadata:
        item.groundingMetadata ||
        metadata.groundingMetadata ||
        metadata.grounding_metadata,
      rewrittenPrompt:
        item.rewrittenPrompt ||
        metadata.rewrittenPrompt ||
        metadata.rewritten_prompt,
      negativePrompt:
        item.negativePrompt ||
        metadata.negativePrompt ||
        metadata.negative_prompt,
      enrichedSourceAssets:
        item.enrichedSourceAssets || metadata.enriched_source_assets,
      enrichedSourceMediaItems:
        item.enrichedSourceMediaItems || metadata.enriched_source_media_items,
      style: item.style || metadata.style,
      lighting: item.lighting || metadata.lighting,
      colorAndTone: item.colorAndTone || metadata.color_and_tone,
      composition: item.composition || metadata.composition,
      modifiers: item.modifiers || metadata.modifiers,
      comment: item.comment || metadata.comment,
      critique: item.critique || metadata.critique,
      rawData: item.rawData || metadata.raw_data,
      audioAnalysis: item.audioAnalysis || metadata.audio_analysis,
      errorMessage:
        item.errorMessage ||
        item.error_message ||
        metadata.errorMessage ||
        metadata.error_message,
      addWatermark: item.addWatermark ?? metadata.add_watermark,
      originalGcsUris: item.originalGcsUris || item.original_gcs_uris || [],
      originalPresignedUrls:
        item.originalPresignedUrls || item.original_presigned_urls || [],
      deletedAt: item.deletedAt || item.deleted_at || metadata.deleted_at, // Added mapping for soft delete
    };
    return galleryItem;
  }

  createTemplateFromMediaItem(mediaItemId: number): Observable<{id: string}> {
    return this.http.post<{id: string}>(
      `${environment.backendURL}/media-templates/from-media-item/${mediaItemId}`,
      {},
    );
  }

  bulkDelete(
    items: {id: number; type: string}[],
    workspaceId: number,
  ): Observable<{deleted_count: number}> {
    const url = `${environment.backendURL}/gallery/bulk-delete`;
    return this.http.post<{deleted_count: number}>(url, {
      items,
      workspace_id: workspaceId,
    });
  }

  bulkDownload(
    items: {id: number; type: string}[],
    workspaceId: number,
  ): Observable<Blob> {
    const url = `${environment.backendURL}/gallery/bulk-download`;
    return this.http.post(
      url,
      {items, workspace_id: workspaceId},
      {responseType: 'blob'},
    );
  }

  bulkCopy(
    items: {id: number; type: string}[],
    targetWorkspaceId: number,
  ): Observable<{copied_count: number}> {
    const url = `${environment.backendURL}/gallery/bulk-copy`;
    return this.http.post<{copied_count: number}>(url, {
      items,
      target_workspace_id: targetWorkspaceId,
    });
  }

  restoreMediaItem(id: number, itemType: string): Observable<any> {
    const url = `${environment.backendURL}/gallery/items/${id}/restore?item_type=${itemType}`;
    return this.http.post(url, {});
  }

  get filtersState(): GalleryFiltersState | null {
    return this.uiFiltersState;
  }

  setFiltersState(state: GalleryFiltersState | null): void {
    this.uiFiltersState = state;
  }
}
