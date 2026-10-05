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

import {Component, OnDestroy} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatDialog} from '@angular/material/dialog';
import {DomSanitizer, SafeHtml} from '@angular/platform-browser';
import {ActivatedRoute, NavigationExtras, Router} from '@angular/router';
import {first, Subscription} from 'rxjs';
import {
  EnrichedSourceAsset,
  MediaItem,
} from '../../common/models/media-item.model';
import {GalleryItem} from '../../common/models/gallery-item.model';
import {CreatePromptMediaDto} from '../../common/models/prompt.model';
import {SourceMediaItemLink} from '../../common/models/search.model';
import {AuthService} from '../../common/services/auth.service';
import {LoadingService} from '../../common/services/loading.service';
import {MimeTypeEnum} from '../../fun-templates/media-template.model';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../utils/handleMessageSnackbar';
import {GalleryService} from '../gallery.service';
import {ConfirmationDialogComponent} from '../../common/components/confirmation-dialog/confirmation-dialog.component';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {FolderService} from '../../common/services/folder.service';
import {FolderBreadcrumb} from '../../common/models/folder.model';

/**
 * One segment of the location trail shown above the media details.
 * `id === null` marks the collapsed "…" segment that stands in for the
 * folders hidden between the root folder and the last two ancestors.
 */
export interface LocationCrumb {
  id: number | null;
  name: string;
  tooltip?: string;
}

/** Folder segments shown before the trail collapses the middle into "…". */
export const MAX_VISIBLE_FOLDER_CRUMBS = 3;

@Component({
  selector: 'app-media-detail',
  templateUrl: './media-detail.component.html',
  styleUrls: ['./media-detail.component.scss'],
})
export class MediaDetailComponent implements OnDestroy {
  private routeSub?: Subscription;
  private mediaSub?: Subscription;

  public isLoading = true;
  public mediaItem: GalleryItem | undefined;
  public isAdmin = false;
  public initialSlideIndex = 0;
  public currentImageIndex = 0;
  promptJson: any | undefined;
  isPromptExpanded = false;
  public isIdentityExpanded = false;
  public selectedAssetForLightbox: GalleryItem | null = null;
  public lightboxInitialIndex = 0;

  /**
   * Root→leaf ancestors of the folder that holds this item ([] = All Media).
   * Assigning recomputes `locationCrumbs` exactly once: the trail is rendered
   * with `*ngFor`, and a getter returning fresh objects on every change
   * detection would re-create the buttons between mousedown and mouseup,
   * silently swallowing clicks.
   */
  get folderBreadcrumbs(): FolderBreadcrumb[] {
    return this._folderBreadcrumbs;
  }
  set folderBreadcrumbs(crumbs: FolderBreadcrumb[]) {
    this._folderBreadcrumbs = crumbs ?? [];
    this.locationCrumbs = MediaDetailComponent.buildLocationCrumbs(
      this._folderBreadcrumbs,
    );
  }
  private _folderBreadcrumbs: FolderBreadcrumb[] = [];
  private breadcrumbSub?: Subscription;

  /** Stable, memoised folder segments for the location trail. */
  public locationCrumbs: LocationCrumb[] = [];

  /**
   * Long paths keep the first folder and the last two, and collapse
   * everything in between into a single "…" segment whose tooltip lists
   * the hidden folder names.
   */
  private static buildLocationCrumbs(
    crumbs: FolderBreadcrumb[],
  ): LocationCrumb[] {
    if (crumbs.length <= MAX_VISIBLE_FOLDER_CRUMBS) {
      return crumbs.map(c => ({id: c.id, name: c.name}));
    }
    const first = crumbs[0];
    const tail = crumbs.slice(-2);
    const hidden = crumbs.slice(1, -2);
    return [
      {id: first.id, name: first.name},
      {id: null, name: '…', tooltip: hidden.map(h => h.name).join(' › ')},
      ...tail.map(c => ({id: c.id, name: c.name})),
    ];
  }

  trackCrumb(_index: number, crumb: LocationCrumb): number | string {
    return crumb.id ?? 'ellipsis';
  }

  get identityFields(): {label: string; value: any; type: string}[] {
    if (!this.mediaItem) return [];

    const isAsset = this.mediaItem.itemType === 'source_asset';

    const fields: {label: string; value: any; type: string}[] = [
      {
        label: 'Status',
        value: this.mediaItem.status
          ? this.mediaItem.status.toUpperCase()
          : null,
        type: 'status',
      },
      {label: 'Mime Type', value: this.mediaItem.mimeType, type: 'text'},
      {label: 'Aspect Ratio', value: this.mediaItem.aspectRatio, type: 'text'},
      {label: 'Resolution', value: this.mediaItem.resolution, type: 'text'},
    ];

    if (this.isIdentityExpanded) {
      fields.push(
        {label: 'Model', value: this.mediaItem.model, type: 'text'},
        {label: 'Created At', value: this.mediaItem.createdAt, type: 'date'},
        {label: 'Created By', value: this.mediaItem.userEmail, type: 'text'},
        {
          label: 'Generation Time',
          value: this.mediaItem.generationTime
            ? `${this.mediaItem.generationTime.toFixed(2)}s`
            : undefined,
          type: 'text',
        },
      );

      if (!isAsset) {
        fields.push(
          {label: 'Voice', value: this.mediaItem.voiceName, type: 'text'},
          {label: 'Language', value: this.mediaItem.languageCode, type: 'text'},
          {label: 'Seed', value: this.mediaItem.seed, type: 'text'},
          {label: 'Num Media', value: this.mediaItem.numMedia, type: 'text'},
          {
            label: 'Duration',
            value: this.mediaItem.duration
              ? `${this.mediaItem.duration}s`
              : undefined,
            type: 'text',
          },
          {
            label: 'Google Search',
            value:
              this.mediaItem.googleSearch !== undefined
                ? this.mediaItem.googleSearch
                  ? 'Enabled'
                  : 'Disabled'
                : undefined,
            type: 'text',
          },
        );

        const originalPrompt =
          this.mediaItem.originalPrompt ||
          (this.promptJson ? this.formattedPrompt : this.mediaItem.prompt);
        fields.push({
          label: 'Original Prompt',
          value: originalPrompt,
          type: 'prompt',
        });

        if (
          this.mediaItem.prompt &&
          this.mediaItem.prompt !== this.mediaItem.originalPrompt
        ) {
          fields.push({
            label: 'Prompt Used',
            value: this.mediaItem.prompt,
            type: 'prompt',
          });
        }
      }
    }

    return fields.filter(
      f =>
        f.value !== null &&
        f.value !== undefined &&
        f.value !== '' &&
        (Array.isArray(f.value) ? f.value.length > 0 : true),
    );
  }

  get isYoutubeVideo(): boolean {
    return (this.mediaItem as any)?.metadata?.assetType === 'youtube_video';
  }

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private galleryService: GalleryService,
    private loadingService: LoadingService,
    private _snackBar: MatSnackBar,
    private authService: AuthService,
    private sanitizer: DomSanitizer,
    private workspaceStateService: WorkspaceStateService,
    private folderService: FolderService,
    public dialog: MatDialog,
  ) {
    // Check if user is admin
    this.isAdmin = this.authService.isUserAdmin() ?? false;

    // Always trigger fetch to get full source assets, metadata, etc.
    this.fetchMediaItem();
  }

  fetchMediaItem() {
    this.routeSub = this.route.paramMap.subscribe(params => {
      const id = params.get('id');
      if (id) {
        // Check if we are on the asset-detail or gallery route
        const isAsset = this.router.url.includes('/asset-detail');
        this.fetchMediaDetails(Number(id), isAsset);
      }
    });
  }

  ngOnDestroy(): void {
    this.routeSub?.unsubscribe();
    this.mediaSub?.unsubscribe();
    this.breadcrumbSub?.unsubscribe();
  }

  fetchMediaDetails(id: number, isAsset = false): void {
    const fetchObs = isAsset
      ? this.galleryService.getAsset(id)
      : this.galleryService.getMedia(id);

    this.mediaSub = fetchObs.subscribe({
      next: (data: GalleryItem) => {
        this.mediaItem = data;
        this.isLoading = false;
        this.loadingService.hide();
        this.readInitialIndexFromUrl();
        this.parsePrompt();
        this.loadFolderBreadcrumbs();
      },
      error: err => {
        console.error('Failed to fetch media details', err);
        this.isLoading = false;
        this.loadingService.hide();
        handleErrorSnackbar(this._snackBar, err, 'Fetch details');
      },
    });
  }

  /**
   * Resolves the folder path of the current item for the location trail.
   * Uses the item's own workspace (not the active one) so direct links to
   * items in other workspaces still render where the file lives. Failures
   * only degrade the trail to "All Media" — they never block the page.
   */
  private loadFolderBreadcrumbs(): void {
    this.breadcrumbSub?.unsubscribe();
    const folderId = this.mediaItem?.folderId;
    if (!folderId) {
      this.folderBreadcrumbs = [];
      return;
    }
    this.breadcrumbSub = this.folderService
      .getBreadcrumbs(folderId, this.mediaItem?.workspaceId)
      .subscribe({
        next: crumbs => {
          this.folderBreadcrumbs = crumbs ?? [];
        },
        error: err => {
          console.warn('Could not resolve folder location for media', err);
          this.folderBreadcrumbs = [];
        },
      });
  }

  /** Called by the lightbox after a successful "Move to folder". */
  onMediaMoved(folderId: number | null): void {
    if (!this.mediaItem) return;
    this.mediaItem.folderId = folderId ?? undefined;
    this.loadFolderBreadcrumbs();
  }

  /** Navigates to a folder in the gallery; `null` means "All Media". */
  navigateToFolder(crumb: LocationCrumb | null): void {
    if (crumb && crumb.id === null) return; // collapsed "…" segment
    void this.router.navigate(crumb ? ['/folders', crumb.id] : ['/gallery']);
  }

  private parsePrompt(): void {
    const rawToParse = this.mediaItem?.prompt || this.mediaItem?.originalPrompt;
    if (!rawToParse) {
      this.promptJson = undefined;
      return;
    }
    try {
      if (typeof rawToParse === 'string') {
        const parsed = JSON.parse(rawToParse);
        if (parsed && typeof parsed === 'object') {
          this.promptJson = parsed;
        }
      } else if (typeof rawToParse === 'object') {
        // It's already an object, just cast it.
        this.promptJson = rawToParse as CreatePromptMediaDto;
      }
    } catch (e) {
      // Not a valid JSON string.
      this.promptJson = undefined;
    }
  }

  private readInitialIndexFromUrl(): void {
    const indexStr = this.route.snapshot.queryParamMap.get('img_index');
    if (indexStr) {
      const index = parseInt(indexStr, 10);
      if (
        !isNaN(index) &&
        index >= 0 &&
        index < (this.mediaItem?.presignedUrls?.length || 0)
      ) {
        this.initialSlideIndex = index;
        this.currentImageIndex = index;
      }
    }
  }

  get currentTitle(): string {
    if (!this.mediaItem) return 'Details';
    const index = this.currentImageIndex;
    const titles = this.mediaItem.titles;
    if (titles && titles[index]) {
      return titles[index];
    }
    return titles?.[0] || 'Details';
  }

  get currentDescription(): string | undefined {
    if (!this.mediaItem) return undefined;
    const index = this.currentImageIndex;
    const descriptions = this.mediaItem.descriptions;
    if (descriptions && descriptions[index]) {
      return descriptions[index];
    }
    return descriptions?.[0];
  }

  /**
   * Gets the prompt, formatted as a beautified JSON string if it's a
   * valid JSON object or stringified JSON. Otherwise, returns the original prompt.
   */
  get formattedPrompt(): string {
    const rawPrompt = this.mediaItem?.prompt || this.mediaItem?.originalPrompt;
    if (!rawPrompt) {
      return 'N/A';
    }

    if (this.promptJson) {
      return JSON.stringify(this.promptJson, null, 2);
    }

    // Return the original string if it's not an object or valid stringified JSON.
    return rawPrompt;
  }

  /**
   * Converts a GCS URI (gs://...) to a clickable console URL.
   * @param uri The GCS URI.
   * @returns A URL to the GCS object in the Google Cloud Console.
   */
  public getGcsLink(uri: string): string {
    if (!uri || !uri.startsWith('gs://')) {
      return '#';
    }
    return `https://console.cloud.google.com/storage/browser/${uri.substring(5)}`;
  }

  /**
   * Creates a new template from the current media item.
   * This is intended for admin users.
   */
  createTemplateFromMediaItem(): void {
    if (!this.mediaItem?.id) {
      return;
    }

    this.loadingService.show();

    // Note: The 'createTemplateFromMediaItem' method should be implemented in a relevant service (e.g., TemplateService or GalleryService).
    // It should perform a POST request to the `/from-media-item/{media_item_id}` endpoint.
    this.galleryService
      .createTemplateFromMediaItem(this.mediaItem.id)
      .pipe(first())
      .subscribe({
        next: (newTemplate: {id: string}) => {
          this.loadingService.hide();
          handleSuccessSnackbar(
            this._snackBar,
            'Template created successfully!',
          );
          void this.router.navigate(['/admin/media-templates']);
        },
        error: err => {
          this.loadingService.hide();
          console.error('Failed to create template from media item', err);
          handleErrorSnackbar(this._snackBar, err, 'Create template');
        },
      });
  }

  togglePromptExpansion(): void {
    this.isPromptExpanded = !this.isPromptExpanded;
  }

  toggleIdentityExpansion(): void {
    this.isIdentityExpanded = !this.isIdentityExpanded;
  }

  generateWithThisImage(index: number): void {
    if (!this.mediaItem) {
      return;
    }

    const sourceMediaItem: SourceMediaItemLink = {
      mediaItemId: this.mediaItem.id,
      mediaIndex: index,
      role: 'input',
    };

    const navigationExtras: NavigationExtras = {
      state: {
        remixState: {
          sourceMediaItems: [sourceMediaItem],
          prompt: this.mediaItem.prompt,
          previewUrl: this.mediaItem.presignedUrls?.[index],
        },
      },
    };
    void this.router.navigate(['/'], navigationExtras);
  }

  generateVideoWithImage(event: {role: 'start' | 'end'; index: number}): void {
    if (!this.mediaItem) {
      return;
    }

    const sourceMediaItem: SourceMediaItemLink = {
      mediaItemId: this.mediaItem.id,
      mediaIndex: event.index,
      role: event.role === 'start' ? 'start_frame' : 'end_frame',
    };

    const remixState = {
      prompt: this.mediaItem.prompt,
      sourceMediaItems: [sourceMediaItem],
      startImagePreviewUrl:
        event.role === 'start'
          ? this.mediaItem.presignedUrls?.[event.index]
          : undefined,
      endImagePreviewUrl:
        event.role === 'end'
          ? this.mediaItem.presignedUrls?.[event.index]
          : undefined,
    };

    const navigationExtras: NavigationExtras = {
      state: {remixState},
    };
    void this.router.navigate(['/video'], navigationExtras);
  }

  handleEditWithOmni(event: {mediaItem: any; selectedIndex: number}): void {
    if (!this.mediaItem) {
      return;
    }

    const index = event.selectedIndex;
    const mime = this.mediaItem.mimeType || '';
    const isAudio = mime.startsWith('audio/');

    const remixState: any = {
      parentMediaItemId: this.mediaItem.id,
      parentMediaIndex: index,
      generationModel: 'gemini-omni',
      isOmniMode: true,
    };

    if (isAudio) {
      remixState.referenceAudio = {
        id: this.mediaItem.id,
        type: this.mediaItem.itemType || 'media_item',
        index: index,
        name:
          this.mediaItem.originalPrompt || `Audio Input ${this.mediaItem.id}`,
      };
    } else {
      remixState.referenceVideo = {
        id: this.mediaItem.id,
        type: this.mediaItem.itemType || 'media_item',
        index: index,
        name:
          this.mediaItem.originalPrompt || `Video Input ${this.mediaItem.id}`,
        previewUrl:
          this.mediaItem.presignedThumbnailUrls?.[index] ||
          this.mediaItem.presignedUrls?.[index] ||
          '',
      };
    }

    const navigationExtras: NavigationExtras = {
      state: {remixState},
    };
    void this.router.navigate(['/video'], navigationExtras);
  }

  sendToVto(index: number): void {
    if (!this.mediaItem) {
      return;
    }

    const navigationExtras: NavigationExtras = {
      state: {
        remixState: {
          modelImageAssetId: this.mediaItem.id,
          modelImagePreviewUrl: this.mediaItem.presignedUrls?.[index],
          modelImageMediaIndex: index,
          modelImageGcsUri: this.mediaItem.gcsUris?.[index],
        },
      },
    };
    void this.router.navigate(['/vto'], navigationExtras);
  }

  handleExtendWithAi(event: {
    mediaItem: MediaItem;
    selectedIndex: number;
  }): void {
    if (!this.mediaItem) {
      return;
    }

    const sourceMediaItem: SourceMediaItemLink = {
      mediaItemId: this.mediaItem.id,
      mediaIndex: event.selectedIndex,
      role: 'video_extension_source',
    };

    const remixState = {
      prompt: this.mediaItem.prompt,
      sourceMediaItems: [sourceMediaItem],
      // Since it's a video, we can use the thumbnail as a preview.
      startImagePreviewUrl:
        this.mediaItem.presignedThumbnailUrls?.[event.selectedIndex],
      generationModel: 'veo-3.1-generate-001', // Switch to Veo 3.1 for video input
    };

    const navigationExtras: NavigationExtras = {
      state: {remixState},
    };
    void this.router.navigate(['/video'], navigationExtras);
  }

  handleConcatenate(event: {
    mediaItem: MediaItem;
    selectedIndex: number;
  }): void {
    if (!this.mediaItem) {
      return;
    }

    const sourceMediaItem: SourceMediaItemLink = {
      mediaItemId: this.mediaItem.id,
      mediaIndex: event.selectedIndex,
      role: 'concatenation_source', // Generic role for concatenation
    };

    const remixState = {
      sourceMediaItems: [sourceMediaItem],
      startImagePreviewUrl:
        this.mediaItem.presignedThumbnailUrls?.[event.selectedIndex],
      startConcatenation: true,
    };

    void this.router.navigate(['/video'], {state: {remixState}});
  }

  public openSourceAssetInLightbox(
    sourceAsset: EnrichedSourceAsset,
    event: MouseEvent,
  ): void {
    event.preventDefault();
    event.stopPropagation();

    const isVideo =
      sourceAsset.mimeType?.startsWith('video/') === true ||
      sourceAsset.presignedUrl.includes('.mp4');

    if (isVideo) {
      // PhotoSwipe lightbox doesn't support videos, so open in a new tab.
      window.open(sourceAsset.presignedUrl, '_blank');
      return;
    }

    // Existing logic for images
    // Construct a MediaItem-like object for the lightbox
    // Construct a GalleryItem-like object for the lightbox
    const mediaItem: GalleryItem = {
      id: Number(sourceAsset.sourceAssetId),
      workspaceId: 0,
      createdAt: new Date().toISOString(),
      itemType: 'media_item',
      status: 'COMPLETED',
      mimeType: MimeTypeEnum.IMAGE,
      prompt: `Input: ${sourceAsset.role}`,
      gcsUris: [sourceAsset.gcsUri],
      thumbnailUris: [sourceAsset.presignedThumbnailUrl],
      presignedUrls: [sourceAsset.presignedUrl],
      presignedThumbnailUrls: [sourceAsset.presignedThumbnailUrl],
      metadata: {},
    };
    this.selectedAssetForLightbox = mediaItem;
    this.lightboxInitialIndex = 0;
  }

  public closeLightbox(): void {
    this.selectedAssetForLightbox = null;
  }

  public getSafeHtml(html: string): SafeHtml {
    return this.sanitizer.bypassSecurityTrustHtml(html);
  }

  public onTagsChanged(tags: any[]): void {
    if (this.mediaItem) {
      this.fetchMediaDetails(
        this.mediaItem.id,
        this.mediaItem.itemType === 'source_asset',
      );
    }
  }

  public deleteCurrentMedia(): void {
    if (!this.mediaItem?.id) return;

    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId === null) return;

    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      data: {
        title: 'Delete Media',
        message: 'Are you sure you want to delete this media item?',
      },
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.galleryService
          .bulkDelete(
            [{id: this.mediaItem!.id, type: this.mediaItem!.itemType}],
            workspaceId,
          )
          .subscribe({
            next: () => {
              handleSuccessSnackbar(
                this._snackBar,
                'Media deleted successfully',
              );
              void this.router.navigate(['/gallery']);
            },
            error: err => {
              handleErrorSnackbar(this._snackBar, err, 'Delete media');
            },
          });
      }
    });
  }
}
