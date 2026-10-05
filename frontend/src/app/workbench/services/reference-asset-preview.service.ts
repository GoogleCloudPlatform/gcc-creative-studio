/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {Injectable, Signal, computed, inject, signal} from '@angular/core';
import {GalleryService} from '../../gallery/gallery.service';
import {CampaignReferenceAsset} from '../utils/campaign-details';

/** One image a generated asset was produced from (its "ingredient"). */
export interface ReferenceAssetSource {
  url: string;
  label: string;
}

/** Resolution state of one reference asset thumbnail. */
export interface ReferenceAssetPreview {
  /** Presigned (thumbnail, falling back to full) URL; empty while loading. */
  url: string;
  /** True when the backend refused or no longer has the asset. */
  unavailable: boolean;
  /**
   * For a generated media item: the reference images it was generated from
   * (e.g. the outfit/garment pictures a character headshot used). Empty for
   * uploads and for items generated from a prompt alone.
   */
  sources: ReferenceAssetSource[];
  /** For a generated media item: the prompt the image was generated from. */
  prompt?: string;
}

/**
 * Resolves the Campaign tab's reference assets to presigned URLs.
 *
 * The agent only stores Creative Studio ids (`asset_refs`), never URLs — every
 * image in the app is served through a short-lived presigned GCS URL that
 * `GET /api/media/{id}` (generated → media item) or
 * `GET /api/source_assets/{id}` (uploaded → source asset) hands out. This
 * service fetches each id exactly once per app lifetime and keeps the result
 * in a signal map so the template can stay purely declarative.
 *
 * A failed lookup (deleted asset, or one owned by another workspace member —
 * the backend is owner-scoped) is remembered as `unavailable` and is **never**
 * re-requested: a `campaignDetails` re-emit happens on every streamed delta,
 * and retrying there would hammer the backend with 404s.
 */
@Injectable({providedIn: 'root'})
export class ReferenceAssetPreviewService {
  private galleryService = inject(GalleryService);

  private previews = signal<Record<string, ReferenceAssetPreview>>({});
  private requested = new Set<string>();

  /** Stable cache key for an asset (type + id). */
  static keyOf(asset: Pick<CampaignReferenceAsset, 'assetType' | 'id'>) {
    return `${asset.assetType}:${asset.id}`;
  }

  /** Reactive lookup; `undefined` until {@link ensure} has been called for it. */
  preview(
    asset: Pick<CampaignReferenceAsset, 'assetType' | 'id'>,
  ): Signal<ReferenceAssetPreview | undefined> {
    const key = ReferenceAssetPreviewService.keyOf(asset);
    return computed(() => this.previews()[key]);
  }

  /** Non-reactive snapshot (handy inside templates already tracking `previews`). */
  snapshot(
    asset: Pick<CampaignReferenceAsset, 'assetType' | 'id'>,
  ): ReferenceAssetPreview | undefined {
    return this.previews()[ReferenceAssetPreviewService.keyOf(asset)];
  }

  /** Kicks off resolution for every asset not seen before. Idempotent. */
  ensure(assets: readonly CampaignReferenceAsset[]): void {
    for (const asset of assets) {
      const key = ReferenceAssetPreviewService.keyOf(asset);
      if (this.requested.has(key)) continue;
      this.requested.add(key);

      const numericId = Number(asset.id);
      if (!Number.isFinite(numericId)) {
        this.set(key, {url: '', unavailable: true, sources: []});
        continue;
      }
      this.set(key, {url: '', unavailable: false, sources: []});

      const request$ =
        asset.assetType === 'generated'
          ? this.galleryService.getMedia(numericId)
          : this.galleryService.getAsset(numericId);

      request$.subscribe({
        next: item => {
          const url =
            item?.presignedThumbnailUrls?.[0] || item?.presignedUrls?.[0] || '';
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const rawPrompt = (item as any)?.prompt;
          const prompt =
            typeof rawPrompt === 'string' && rawPrompt.trim()
              ? rawPrompt.trim()
              : undefined;
          this.set(key, {
            url,
            unavailable: !url,
            sources: ReferenceAssetPreviewService.sourcesOf(item),
            ...(prompt ? {prompt} : {}),
          });
        },
        error: err => {
          console.error(
            `Failed to resolve reference asset ${key} for the Campaign tab:`,
            err,
          );
          this.set(key, {url: '', unavailable: true, sources: []});
        },
      });
    }
  }

  /**
   * The images a generated media item was produced from, as the backend
   * enriches them (`enrichedSourceAssets` / `enrichedSourceMediaItems`).
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  static sourcesOf(item: any): ReferenceAssetSource[] {
    const sources: ReferenceAssetSource[] = [];
    for (const s of item?.enrichedSourceAssets ?? []) {
      const url = s?.presignedThumbnailUrl || s?.presignedUrl;
      if (url) sources.push({url, label: `Upload ${s.sourceAssetId ?? ''}`});
    }
    for (const s of item?.enrichedSourceMediaItems ?? []) {
      const url = s?.presignedThumbnailUrl || s?.presignedUrl;
      if (url) sources.push({url, label: `Gallery ${s.mediaItemId ?? ''}`});
    }
    return sources;
  }

  private set(key: string, value: ReferenceAssetPreview) {
    this.previews.update(map => ({...map, [key]: value}));
  }
}
