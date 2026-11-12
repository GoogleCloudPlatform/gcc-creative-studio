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

import {
  Component,
  Input,
  Optional,
  Output,
  EventEmitter,
  OnDestroy,
  Inject,
  PLATFORM_ID,
  computed,
  signal,
} from '@angular/core';
import {Router} from '@angular/router';
import {isPlatformBrowser} from '@angular/common';
import {Subscription} from 'rxjs';
import {GalleryItem} from '../../models/gallery-item.model';
import {MediaItemSelection} from '../image-selector/image-selector.component';
import {UserService} from '../../services/user.service';
import {MatDialog} from '@angular/material/dialog';
import {UserRolesEnum} from '../../models/user.model';
import {AssignTagsDialogComponent} from '../assign-tags-dialog/assign-tags-dialog.component';
import {
  AudioAnalysis,
  AudioTrackAnalysis,
  MediaItem,
  formatAudioDuration,
  getAudioTrackAnalysis,
  getAudioTrackBpm,
  getAudioTrackDurationSeconds,
  getAudioTrackWaveform,
} from '../../models/media-item.model';
import {TagModel} from '../../services/tags.service';
import {GalleryDragPayload} from '../../models/folder.model';
import {GalleryService} from '../../../gallery/gallery.service';

@Component({
  selector: 'app-gallery-card',
  templateUrl: './gallery-card.component.html',
  styleUrls: ['./gallery-card.component.scss'],
})
export class GalleryCardComponent implements OnDestroy {
  isAdmin = false;
  readonly loadedAudioAnalysis = signal<AudioAnalysis | null>(null);
  readonly probedTrackDurations = signal<Record<number, number>>({});
  private readonly itemSignal = signal<GalleryItem | undefined>(undefined);
  private readonly currentImageIndexSignal = signal<number>(0);
  private audioAnalysisSub?: Subscription;
  private audioAnalysisInFlight = false;
  private activeMetadataAudio: HTMLAudioElement | null = null;
  private activeMetadataProbeIndex: number | null = null;
  private probedAudioIndices = new Set<number>();
  private _item!: GalleryItem;

  constructor(
    private router: Router,
    private userService: UserService,
    public dialog: MatDialog,
    @Inject(PLATFORM_ID) private platformId: Object,
    @Optional() private galleryService?: GalleryService,
  ) {
    const userDetails = this.userService.getUserDetails();
    this.isAdmin = userDetails?.roles?.includes(UserRolesEnum.ADMIN) || false;
  }
  @Input() set item(val: GalleryItem) {
    if (val?.id !== this._item?.id) {
      this.resetHoverAudioState();
    }
    this._item = val;
    this.itemSignal.set(val);
  }
  get item(): GalleryItem {
    return this._item;
  }
  @Input() isSelectionMode = false;
  @Input() isSelectorMode = false;
  @Input() isSelected = false;
  @Input() anyItemSelected = false;
  @Input() selectedItems: Set<string> = new Set();
  @Input() filteredTags: string[] = [];
  /**
   * When true the card shows only the first image of a multi-image item and
   * hides the carousel, so any selection reports `selectedIndex: 0`. Used by
   * pickers whose consumer can only address the first index of a media item.
   */
  @Input() set firstIndexOnly(value: boolean) {
    this._firstIndexOnly = value;
    if (value) this.currentImageIndex = 0;
  }
  get firstIndexOnly(): boolean {
    return this._firstIndexOnly;
  }
  private _firstIndexOnly = false;

  @Output() mediaItemSelected = new EventEmitter<MediaItemSelection>();
  @Output() mediaSelected = new EventEmitter<GalleryItem>();
  @Output() selectionToggled = new EventEmitter<{
    item: GalleryItem;
    event: MouseEvent;
    selectedIndex: number;
  }>();

  isDragging = false;
  private wasDragged = false;
  get currentImageIndex(): number {
    return this.currentImageIndexSignal();
  }
  set currentImageIndex(val: number) {
    this.currentImageIndexSignal.set(val);
  }
  loadedMedia: Record<number, boolean> = {};
  hoveredVideoId: number | null = null;
  hoveredAudioId: number | null = null;

  get displayUrls(): string[] {
    if (
      this.item.presignedThumbnailUrls &&
      this.item.presignedThumbnailUrls.length > 0
    ) {
      return this.item.presignedThumbnailUrls;
    }
    return this.item.presignedUrls || [];
  }

  get hasThumbnail(): boolean {
    return (
      !!this.item.presignedThumbnailUrls &&
      this.item.presignedThumbnailUrls.length > 0
    );
  }

  get displayPaddingBottom(): string {
    const rawRatio =
      this.item.aspectRatio ||
      (this.item as any).aspect ||
      this.item.metadata?.aspectRatio;
    const gap = 16; // gap-4 is 1rem = 16px

    // Default handles for no ratio
    if (!rawRatio) {
      if (this.item.mimeType?.startsWith('audio/')) {
        return `calc(50% - ${gap / 2}px)`; // 2:1 for audio
      }
      if (this.item.mimeType?.startsWith('video/')) {
        return '100%'; // 1:1 default for video if unknown (16:9 would be closer to 2:1)
      }
      return '100%'; // 1:1 default
    }

    const parts = rawRatio.split(':').map(Number);
    if (
      parts.length !== 2 ||
      isNaN(parts[0]) ||
      isNaN(parts[1]) ||
      parts[1] === 0
    ) {
      return '100%';
    }
    const ratio = parts[0] / parts[1];

    // Thresholds:
    // 2:1 if ratio >= 2
    // 1:2 if ratio <= 0.5
    // 1:1 otherwise
    if (ratio >= 2) {
      return `calc(50% - ${gap / 2}px)`; // 2:1
    } else if (ratio <= 0.5) {
      return `calc(200% + ${gap}px)`; // 1:2
    } else {
      return '100%'; // 1:1
    }
  }

  get isYoutubeVideo(): boolean {
    const meta = this.item?.metadata as any;
    return (
      meta?.assetType === 'youtube_video' ||
      meta?.asset_type === 'youtube_video'
    );
  }

  readonly currentAudioTrack = computed<AudioTrackAnalysis | null>(() => {
    const loaded = this.loadedAudioAnalysis();
    const item = this.itemSignal();
    return getAudioTrackAnalysis(
      loaded ? {audioAnalysis: loaded} : item,
      this.currentImageIndexSignal(),
    );
  });

  readonly currentAudioWaveform = computed<number[] | null>(() =>
    getAudioTrackWaveform(this.currentAudioTrack()),
  );

  readonly currentAudioBpmLabel = computed<string | null>(() =>
    getAudioTrackBpm(this.currentAudioTrack()),
  );

  readonly currentAudioDurationLabel = computed<string | null>(() => {
    const item = this.itemSignal();
    const idx = this.currentImageIndexSignal();
    const itemAny = item as any;
    const metaAny = item?.metadata as any;
    const itemDuration =
      itemAny?.durationSeconds ??
      itemAny?.duration_seconds ??
      item?.duration ??
      metaAny?.durationSeconds ??
      metaAny?.duration_seconds ??
      null;
    const seconds =
      getAudioTrackDurationSeconds(
        this.currentAudioTrack(),
        idx === 0 ? itemDuration : null,
      ) ?? this.probedTrackDurations()[idx];
    return formatAudioDuration(seconds);
  });

  trackByIndex(index: number): number {
    return index;
  }

  openAssignTagsDialog(event: Event): void {
    event.stopPropagation();
    event.preventDefault();

    const dialogRef = this.dialog.open(AssignTagsDialogComponent, {
      data: {
        assetId: this.item.id,
        assetType: this.item.itemType,
        existingTags: this.item.metadata?.tags || [],
      },
      width: '400px',
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (!this.item.metadata) {
          this.item.metadata = {};
        }
        this.item.metadata.tags = result;
      }
    });
  }

  ngOnDestroy() {
    this.resetHoverAudioState();
  }

  onMouseEnter() {
    if (this.item.mimeType?.startsWith('video/')) {
      this.hoveredVideoId = this.item.id;
    }
    if (this.item.mimeType?.startsWith('audio/')) {
      this.hoveredAudioId = this.item.id;
      if (!this.ensureAudioWaveformLoaded()) {
        this.ensureAudioDurationLoaded();
      }
    }
  }

  onMouseLeave() {
    this.hoveredVideoId = null;
    this.hoveredAudioId = null;
    if (this.activeMetadataAudio && this.activeMetadataProbeIndex !== null) {
      this.probedAudioIndices.delete(this.activeMetadataProbeIndex);
      this.cleanupMetadataAudio();
    }
  }

  private resetHoverAudioState(): void {
    this.audioAnalysisSub?.unsubscribe();
    this.audioAnalysisInFlight = false;
    this.loadedAudioAnalysis.set(null);
    this.probedAudioIndices.clear();
    this.probedTrackDurations.set({});
    this.cleanupMetadataAudio();
  }

  private ensureAudioWaveformLoaded(): boolean {
    if (
      !this.galleryService ||
      this.item.itemType !== 'media_item' ||
      this.loadedAudioAnalysis() !== null ||
      getAudioTrackAnalysis(this.item, 0)
    ) {
      return false;
    }
    if (this.audioAnalysisInFlight) return true;

    const requestedId = this.item.id;
    this.audioAnalysisInFlight = true;
    this.audioAnalysisSub?.unsubscribe();
    this.audioAnalysisSub = this.galleryService
      .getAudioAnalysis(requestedId)
      .subscribe(analysis => {
        this.audioAnalysisInFlight = false;
        if (this.item?.id !== requestedId) return;
        if (analysis) {
          this.loadedAudioAnalysis.set(analysis);
        }
        if (this.hoveredAudioId === requestedId) {
          this.ensureAudioDurationLoaded();
        }
      });
    return true;
  }

  private ensureAudioDurationLoaded(): void {
    const itemId = this.item?.id;
    const trackIndex = this.currentImageIndex;
    const url = this.item?.presignedUrls?.[trackIndex];
    if (
      this.currentAudioDurationLabel() ||
      !url ||
      itemId === undefined ||
      !isPlatformBrowser(this.platformId) ||
      typeof Audio === 'undefined' ||
      this.probedAudioIndices.has(trackIndex)
    ) {
      return;
    }

    this.probedAudioIndices.add(trackIndex);
    this.cleanupMetadataAudio();
    try {
      const audio = new Audio();
      audio.preload = 'metadata';
      this.activeMetadataAudio = audio;
      this.activeMetadataProbeIndex = trackIndex;

      const cleanup = () => {
        audio.onloadedmetadata = null;
        audio.onerror = null;
        if (this.activeMetadataAudio === audio) {
          this.cleanupMetadataAudio();
        }
      };

      audio.onloadedmetadata = () => {
        const dur = audio.duration;
        cleanup();
        if (this.item?.id === itemId && Number.isFinite(dur) && dur > 0) {
          this.probedTrackDurations.update(prev => ({
            ...prev,
            [trackIndex]: dur,
          }));
        }
      };
      audio.onerror = cleanup;
      audio.src = url;
    } catch (err) {
      console.warn('Failed to probe audio metadata duration:', err);
      this.probedAudioIndices.delete(trackIndex);
      this.cleanupMetadataAudio();
    }
  }

  private cleanupMetadataAudio(): void {
    this.activeMetadataProbeIndex = null;
    if (!this.activeMetadataAudio) return;
    try {
      this.activeMetadataAudio.onloadedmetadata = null;
      this.activeMetadataAudio.onerror = null;
      this.activeMetadataAudio.removeAttribute('src');
      this.activeMetadataAudio.load();
    } catch {
      // Ignore cleanup errors on detached audio elements
    }
    this.activeMetadataAudio = null;
  }

  nextImageItem(event: Event) {
    event.stopPropagation();
    event.preventDefault();
    const total = this.displayUrls.length;
    this.currentImageIndex = (this.currentImageIndex + 1) % total;
    if (this.hoveredAudioId === this.item.id) {
      this.ensureAudioDurationLoaded();
    }
  }

  prevImageItem(event: Event) {
    event.stopPropagation();
    event.preventDefault();
    const total = this.displayUrls.length;
    this.currentImageIndex = (this.currentImageIndex - 1 + total) % total;
    if (this.hoveredAudioId === this.item.id) {
      this.ensureAudioDurationLoaded();
    }
  }

  onMediaLoad(index = 0): void {
    this.loadedMedia[index] = true;
  }

  isMediaLoaded(index = 0): boolean {
    return !!this.loadedMedia[index];
  }

  toggleSelection(event: MouseEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.selectionToggled.emit({
      item: this.item,
      event,
      selectedIndex: this.currentImageIndex,
    });
  }

  selectMedia(event: Event): void {
    if (this.isSelectionMode || this.anyItemSelected) {
      event.preventDefault();

      if (this.isSelectionMode) {
        this.mediaItemSelected.emit({
          mediaItem: this.item as unknown as MediaItem,
          selectedIndex: this.currentImageIndex,
        });
      }
    }
  }

  onSelectionClick(event: Event): void {
    event.preventDefault();
  }

  getRoute(): any[] {
    return this.item.itemType === 'source_asset'
      ? ['/asset-detail', this.item.id]
      : ['/gallery', this.item.id];
  }

  onDragStart(event: DragEvent): void {
    if (this.isSelectorMode) {
      event.preventDefault();
      return;
    }
    event.stopPropagation();

    this.isDragging = true;

    // Determine if this item or multi-selected items are being dragged
    let mediaItemIds: number[] = [];
    let sourceAssetIds: number[] = [];
    let itemCount = 1;

    const currentKey = `${this.item.itemType}:${this.item.id}`;
    if (
      this.isSelected &&
      this.selectedItems &&
      this.selectedItems.size > 0 &&
      this.selectedItems.has(currentKey)
    ) {
      const selected = Array.from(this.selectedItems);
      mediaItemIds = selected
        .filter(id => id.startsWith('media_item:'))
        .map(id => parseInt(id.split(':')[1]));
      sourceAssetIds = selected
        .filter(id => id.startsWith('source_asset:'))
        .map(id => parseInt(id.split(':')[1]));
      itemCount = this.selectedItems.size;
    } else {
      if (this.item.itemType === 'media_item') {
        mediaItemIds = [this.item.id];
      } else if (this.item.itemType === 'source_asset') {
        sourceAssetIds = [this.item.id];
      }
      itemCount = 1;
    }

    const payload: GalleryDragPayload = {
      mediaItemIds,
      sourceAssetIds,
      itemCount,
    };

    if (event.dataTransfer) {
      event.dataTransfer.setData('application/json', JSON.stringify(payload));
      event.dataTransfer.effectAllowed = 'move';

      if (isPlatformBrowser(this.platformId)) {
        const ghost = document.createElement('div');
        ghost.style.position = 'absolute';
        ghost.style.top = '-9999px';
        ghost.style.left = '-9999px';
        ghost.style.padding = '6px 14px';
        ghost.style.borderRadius = '20px';
        ghost.style.background = 'rgba(30, 31, 32, 0.95)';
        ghost.style.backdropFilter = 'blur(10px)';
        ghost.style.border = '1px solid #8ab4f8';
        ghost.style.color = '#ffffff';
        ghost.style.fontSize = '12px';
        ghost.style.fontWeight = '600';
        ghost.style.display = 'flex';
        ghost.style.alignItems = 'center';
        ghost.style.gap = '6px';
        ghost.style.boxShadow = '0 6px 20px rgba(0, 0, 0, 0.4)';
        ghost.style.zIndex = '99999';
        ghost.innerHTML = `<span>📁 Moving ${itemCount} ${itemCount === 1 ? 'item' : 'items'}</span>`;
        document.body.appendChild(ghost);
        event.dataTransfer.setDragImage(ghost, 20, 20);
        setTimeout(() => {
          if (ghost.parentNode) {
            ghost.parentNode.removeChild(ghost);
          }
        }, 0);
      }
    }
  }

  onDragEnd(event: DragEvent): void {
    this.isDragging = false;
    this.wasDragged = true;
    setTimeout(() => {
      this.wasDragged = false;
    }, 150);
  }

  onCardClick(event: MouseEvent): void {
    if (this.wasDragged) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }

    if (this.isSelectionMode || this.anyItemSelected) {
      event.preventDefault();
      event.stopPropagation();

      if (this.isSelectionMode) {
        this.mediaItemSelected.emit({
          mediaItem: this.item as unknown as MediaItem,
          selectedIndex: this.currentImageIndex,
        });
        this.selectionToggled.emit({
          item: this.item,
          event,
          selectedIndex: this.currentImageIndex,
        });
        return;
      }

      if (this.anyItemSelected) {
        this.selectionToggled.emit({
          item: this.item,
          event,
          selectedIndex: this.currentImageIndex,
        });
        return;
      }
    }
  }

  get displayedTags(): TagModel[] {
    if (!this.item.tags) return [];

    let tagsToDisplay = this.item.tags;

    if (this.filteredTags && this.filteredTags.length > 0) {
      tagsToDisplay = this.item.tags.filter(tag =>
        this.filteredTags.includes(tag.name),
      );
    }

    let totalLength = 0;
    const maxChars = 20; // Heuristic for card width
    const result = [];

    for (const tag of tagsToDisplay) {
      if (totalLength + tag.name.length <= maxChars || result.length === 0) {
        result.push(tag);
        totalLength += tag.name.length + 3; // +3 for gap/padding estimate
      } else {
        break;
      }
    }

    return result;
  }

  get hiddenTagsCount(): number {
    if (!this.item.tags) return 0;

    let tagsToDisplay = this.item.tags;
    if (this.filteredTags && this.filteredTags.length > 0) {
      tagsToDisplay = this.item.tags.filter(tag =>
        this.filteredTags.includes(tag.name),
      );
    }

    return tagsToDisplay.length - this.displayedTags.length;
  }

  getShortPrompt(prompt: string | undefined | null, wordLimit = 20): string {
    if (!prompt) return 'Generated media';
    let textToTruncate = prompt;
    try {
      const parsedPrompt = JSON.parse(prompt);
      if (
        parsedPrompt &&
        typeof parsedPrompt === 'object' &&
        parsedPrompt.prompt_name
      ) {
        textToTruncate = parsedPrompt.prompt_name;
      }
    } catch (e) {
      // Ignore JSON parsing errors and fall back to raw prompt
    }
    const words = textToTruncate.split(/\s+/);
    if (words.length > wordLimit)
      return words.slice(0, wordLimit).join(' ') + '...';
    return textToTruncate;
  }
}
