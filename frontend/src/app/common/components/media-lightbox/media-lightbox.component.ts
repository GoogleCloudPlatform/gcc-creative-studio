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
  AfterViewInit,
  Component,
  ElementRef,
  Input,
  NgZone,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  ViewChild,
  computed,
  signal,
} from '@angular/core';
import {
  AudioTrackAnalysis,
  MediaItem,
  SongStructureEntry,
  formatAudioClock,
  formatSongStructureEntries,
  formatTrackAnalysisForCopy,
  getAudioTrackAnalysis,
  getAudioTrackCaption,
  getAudioTrackLyrics,
  getAudioTrackWaveform,
} from '../../models/media-item.model';
import {GalleryItem} from '../../models/gallery-item.model';
import PhotoSwipeLightbox from 'photoswipe/lightbox';
import {Clipboard} from '@angular/cdk/clipboard';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatDialog} from '@angular/material/dialog';
import {ActivatedRoute, Router} from '@angular/router';
import {EventEmitter} from '@angular/core';
import {Location} from '@angular/common';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../../utils/handleMessageSnackbar';
import {AssignTagsDialogComponent} from '../assign-tags-dialog/assign-tags-dialog.component';
import {TagsService} from '../../services/tags.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {MoveToFolderDialogComponent} from '../move-to-folder-dialog/move-to-folder-dialog.component';
import {FolderService} from '../../services/folder.service';

@Component({
  selector: 'app-media-lightbox',
  templateUrl: './media-lightbox.component.html',
  styleUrls: ['./media-lightbox.component.scss'],
})
export class MediaLightboxComponent
  implements OnChanges, AfterViewInit, OnDestroy
{
  private readonly mediaItemSignal = signal<
    MediaItem | GalleryItem | undefined
  >(undefined);
  private readonly selectedIndexSignal = signal<number>(0);

  @Input() set mediaItem(val: MediaItem | GalleryItem | undefined) {
    this.mediaItemSignal.set(val);
  }
  get mediaItem(): MediaItem | GalleryItem | undefined {
    return this.mediaItemSignal();
  }
  @Input() initialIndex = 0;
  @Input() showSeeMoreInfoButton = false;
  @Input() showShareButton = true;
  @Input() showDownloadButton = true;
  @Input() showDeleteButton = false;
  @Input() showMoveButton = false;

  get isImage(): boolean {
    return this.mediaItem?.mimeType?.startsWith('image/') ?? false;
  }

  get showOmni(): boolean {
    return true;
  }

  get showEditButton(): boolean {
    return this.isImage;
  }

  get showGenerateVideoButton(): boolean {
    return this.isImage;
  }

  get showVtoButton(): boolean {
    return this.isImage;
  }
  @Output() editClicked = new EventEmitter<number>();
  @Output() generateVideoClicked = new EventEmitter<{
    role: 'start' | 'end';
    index: number;
  }>();
  @Output() sendToVtoClicked = new EventEmitter<number>();
  @Output() editWithOmniClicked = new EventEmitter<{
    mediaItem: MediaItem;
    selectedIndex: number;
  }>();
  @Output() extendWithAiClicked = new EventEmitter<{
    mediaItem: MediaItem;
    selectedIndex: number;
  }>();
  @Output() concatenateClicked = new EventEmitter<{
    mediaItem: MediaItem;
    selectedIndex: number;
  }>();
  @Output() deleteClicked = new EventEmitter<number>();
  @Output() tagsChanged = new EventEmitter<any>();
  @Output() slideChanged = new EventEmitter<number>();
  /** Emits the destination folder id (null = All Media) after a successful move. */
  @Output() moved = new EventEmitter<number | null>();

  get selectedIndex(): number {
    return this.selectedIndexSignal();
  }
  set selectedIndex(val: number) {
    this.selectedIndexSignal.set(val);
  }
  selectedUrl: string | undefined;

  // Properties for NgOptimizedImage
  imageWidth = 1920; // A sensible default max width
  imageHeight = 1920;

  public isShareMenuOpen = false;
  public isDownloading = false;
  private lightbox: PhotoSwipeLightbox | undefined;

  @ViewChild('audioPlayer') audioPlayerRef!: ElementRef<HTMLAudioElement>;
  @ViewChild('videoPlayer') videoPlayerRef!: ElementRef<HTMLVideoElement>;
  @ViewChild('waveformPlayhead')
  waveformPlayheadRef?: ElementRef<HTMLElement>;
  isPlaying = false;
  currentTime = '0:00';
  duration = '0:00';
  progressValue = 0;

  readonly hoverProgress = signal<number | null>(null);
  readonly isScrubbing = signal<boolean>(false);
  readonly durationSeconds = signal<number>(0);
  readonly hoverTimeLabel = computed<string | null>(() => {
    const pct = this.hoverProgress();
    const dur = this.durationSeconds();
    return pct === null || !dur || !Number.isFinite(dur)
      ? null
      : formatAudioClock((pct / 100) * dur);
  });

  readonly currentTrackAnalysis = computed<AudioTrackAnalysis | null>(() => {
    const item = this.mediaItemSignal();
    if (!item?.mimeType?.startsWith('audio/')) return null;
    return getAudioTrackAnalysis(item, this.selectedIndexSignal());
  });

  readonly currentTrackWaveform = computed<number[] | null>(() =>
    getAudioTrackWaveform(this.currentTrackAnalysis()),
  );

  readonly currentTrackLyrics = computed<string | null>(() =>
    getAudioTrackLyrics(this.currentTrackAnalysis()),
  );

  readonly currentTrackCaption = computed<string | null>(() =>
    getAudioTrackCaption(this.currentTrackAnalysis()),
  );

  readonly currentTrackStructureEntries = computed<SongStructureEntry[]>(() =>
    formatSongStructureEntries(this.currentTrackAnalysis()),
  );

  readonly hasCurrentTrackText = computed<boolean>(() =>
    Boolean(
      this.currentTrackLyrics() ||
        this.currentTrackStructureEntries().length > 0 ||
        this.currentTrackCaption(),
    ),
  );

  private playheadRafId: number | null = null;

  constructor(
    private clipboard: Clipboard,
    private snackBar: MatSnackBar,
    private router: Router,
    private location: Location,
    private route: ActivatedRoute,
    public dialog: MatDialog,
    private tagsService: TagsService,
    private workspaceStateService: WorkspaceStateService,
    private folderService: FolderService,
    private ngZone: NgZone,
  ) {}

  ngAfterViewInit(): void {
    this.initializePhotoSwipe();
  }

  ngOnDestroy(): void {
    this.stopPlayheadAnimation();
    this.lightbox?.destroy();
    this.lightbox = undefined;
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['mediaItem'] || changes['initialIndex']) {
      this.initialize();
      // If switching media types, ensure lightbox is destroyed for non-images
      if (this.isAudio || this.isVideo) {
        this.lightbox?.destroy();
        this.lightbox = undefined;
      } else {
        if (this.lightbox) {
          this.lightbox.destroy();
        }
        this.initializePhotoSwipe();
      }
    }
  }

  private initialize(): void {
    if (this.mediaItem?.presignedUrls?.length) {
      const indexFromQuery = this.route.snapshot.queryParamMap.get('img_index');
      const queryIndex = indexFromQuery ? parseInt(indexFromQuery, 10) : -1;

      let startIndex = this.initialIndex;
      if (queryIndex >= 0 && queryIndex < this.mediaItem.presignedUrls.length) {
        startIndex = queryIndex;
      }

      this.selectedIndex =
        startIndex < this.mediaItem.presignedUrls.length ? startIndex : 0;
      this.selectedUrl = this.mediaItem.presignedUrls[this.selectedIndex];
      this.updateImageDimensions();
    } else {
      this.selectedIndex = 0;
      this.selectedUrl = undefined;
    }

    if (this.isAudio) {
      this.resetAudioState();
    } else {
      this.stopPlayheadAnimation();
    }
  }

  private initializePhotoSwipe(): void {
    if (this.mediaItem?.presignedUrls && !this.isVideo && !this.isAudio) {
      this.lightbox = new PhotoSwipeLightbox({
        dataSource: this.mediaItem.presignedUrls.map((url, index) => {
          // If this is the currently selected image and we have its natural dimensions, use them.
          // Otherwise, fall back to calculated defaults.
          const isSelected = index === this.selectedIndex;
          const width = isSelected ? this.imageWidth : 1920;
          const height = isSelected ? this.imageHeight : 1080;

          return {
            src: url,
            width,
            height,
            alt:
              (this.mediaItem as any).originalPrompt || this.mediaItem?.prompt,
          };
        }),
        pswpModule: () => import('photoswipe'),
      });

      this.lightbox.on('close', () => {
        this.isShareMenuOpen = false;
      });

      this.lightbox.on('change', () => {
        if (this.lightbox?.pswp) {
          this.selectMedia(this.lightbox.pswp.currIndex);
        }
      });

      this.lightbox.init();
    } else {
      this.lightbox?.destroy();
      this.lightbox = undefined;
    }
  }

  onImageLoad(event: Event): void {
    const img = event.target as HTMLImageElement;
    if (img && img.naturalWidth && img.naturalHeight) {
      this.imageWidth = img.naturalWidth;
      this.imageHeight = img.naturalHeight;

      // Update the lightbox data source with genuine dimensions if it exists
      if (this.lightbox) {
        // We re-initialize to ensure PhotoSwipe picks up the new dimensions
        // for the data source.
        this.initializePhotoSwipe();
      }
    }
  }

  private updateImageDimensions(): void {
    // We no longer enforce dimensions here as we'll use 'fill' mode
    // but we can keep some defaults for PhotoSwipe if needed.
    if (this.mediaItem) {
      const aspectRatioStr =
        this.mediaItem.aspectRatio || (this.mediaItem as any).aspect || '1:1';
      const [w, h] = aspectRatioStr.split(':').map(Number);
      if (w && h) {
        this.imageHeight = (h / w) * this.imageWidth;
      }
    }
  }

  toggleShareMenu(): void {
    this.isShareMenuOpen = !this.isShareMenuOpen;
  }

  openBatchMoveDialog(): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (!workspaceId || !this.mediaItem) return;

    const dialogRef = this.dialog.open(MoveToFolderDialogComponent, {
      data: {
        workspaceId,
        itemCount: 1,
        currentFolderId: this.mediaItem.folderId,
      },
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result && result.destinationFolderId !== undefined) {
        const destName =
          result.destinationFolderId === null
            ? 'All Media'
            : result.folderName || 'Folder';
        this.executeMove(workspaceId, result.destinationFolderId, destName);
      }
    });
  }

  private executeMove(
    workspaceId: number,
    destinationFolderId: number | null,
    destinationName: string,
  ): void {
    if (!this.mediaItem || this.mediaItem.folderId === destinationFolderId)
      return;

    const assetType = (this.mediaItem as any).itemType || 'media_item';

    this.folderService
      .moveItems({
        workspaceId,
        mediaItemIds: assetType === 'media_item' ? [this.mediaItem.id] : [],
        sourceAssetIds: assetType === 'source_asset' ? [this.mediaItem.id] : [],
        folderIds: [],
        destinationFolderId,
      })
      .subscribe({
        next: res => {
          this.snackBar.open(
            `${res.total_moved} item${res.total_moved === 1 ? '' : 's'} moved to "${destinationName}"`,
            'Close',
            {duration: 3000},
          );
          this.mediaItem!.folderId = destinationFolderId;
          this.moved.emit(destinationFolderId);
        },
        error: err => {
          console.error('Error moving items via drag and drop:', err);
          this.snackBar.open('Failed to move items', 'Close', {
            duration: 3000,
          });
        },
      });
  }

  get currentImageUrl(): string {
    return this.selectedUrl || '';
  }

  openInNewTab(): void {
    if (!this.selectedUrl || this.isDownloading) {
      return;
    }

    this.isDownloading = true;

    const link = document.createElement('a');
    link.href = this.selectedUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    setTimeout(() => {
      this.isDownloading = false;
    }, 200);
  }

  shareTo(
    platform:
      | 'facebook'
      | 'twitter'
      | 'pinterest'
      | 'reddit'
      | 'whatsapp'
      | 'linkedin'
      | 'telegram',
  ): void {
    const url = this.getShareUrl(platform);
    window.open(url, '_blank');
    this.isShareMenuOpen = false;
  }

  getShareUrl(
    platform:
      | 'facebook'
      | 'twitter'
      | 'pinterest'
      | 'reddit'
      | 'whatsapp'
      | 'linkedin'
      | 'telegram',
  ): string {
    const url = encodeURIComponent(this.currentImageUrl);
    const text = encodeURIComponent(
      (this.mediaItem as any).originalPrompt ||
        this.mediaItem?.prompt ||
        'Check out this image!',
    );
    switch (platform) {
      case 'facebook':
        return `https://www.facebook.com/sharer/sharer.php?u=${url}`;
      case 'twitter':
        return `https://twitter.com/intent/tweet?url=${url}&text=${text}`;
      case 'pinterest':
        return `https://pinterest.com/pin/create/button/?url=${window.location.href}&media=${url}&description=${text}`;
      case 'reddit':
        return `https://reddit.com/submit?url=${url}&title=${text}`;
      case 'whatsapp':
        return `https://api.whatsapp.com/send?text=${text}%20${url}`;
      case 'linkedin':
        return `https://www.linkedin.com/sharing/share-offsite/?url=${url}`;
      case 'telegram':
        return `https://t.me/share/url?url=${url}&text=${text}`;
    }
  }

  copyLink(): void {
    if (!this.mediaItem?.id) {
      handleErrorSnackbar(
        this.snackBar,
        {message: 'Cannot generate link: Media item has no ID.'},
        'Copy Link',
      );
      return;
    }

    // Create a URL tree with the path and query parameters for the specific image
    const urlTree = this.router.createUrlTree(['/gallery', this.mediaItem.id], {
      queryParams: {
        img_index: this.selectedIndex > 0 ? this.selectedIndex : null,
      },
    });
    // Serialize the tree to a relative path string (e.g., /gallery/123?img_index=2)
    const relativeUrl = this.router.serializeUrl(urlTree);
    // Combine with the window's origin to get the full, absolute URL
    const fullUrl = `${window.location.origin}${relativeUrl}`;

    this.clipboard.copy(fullUrl);
    handleSuccessSnackbar(this.snackBar, 'Link copied to clipboard!');
    this.isShareMenuOpen = false;
  }

  openPhotoSwipe(index: number): void {
    if (this.lightbox) {
      this.lightbox.loadAndOpen(index);
    }
  }

  selectMedia(index: number): void {
    if (this.mediaItem?.presignedUrls) {
      this.selectedIndex = index;
      this.selectedUrl = this.mediaItem.presignedUrls[index];
      this.updateUrlWithImageIndex(index);
      this.slideChanged.emit(index);

      // If Audio, we need to reload the player
      if (this.isAudio) {
        this.resetAudioState();
        // Allow DOM to update src, then load
        setTimeout(() => {
          if (this.audioPlayerRef) {
            this.audioPlayerRef.nativeElement.load();
            this.togglePlay(); // Auto-play on switch
          }
        }, 50);
      }
    }
  }

  private updateUrlWithImageIndex(index: number): void {
    // This component is used on multiple pages (VTO, Home, Gallery).
    // We should ONLY manipulate the URL when on the gallery detail page.
    // Otherwise, it can cause unintended navigations and state loss.
    if (!this.router.url.startsWith('/gallery/')) {
      // MediaLightbox: Skipping URL update because we are not on a gallery detail page.
      return;
    }
    const url = this.router
      .createUrlTree([], {
        relativeTo: this.route,
        // If index is 0, we can remove the query param.
        queryParams: {img_index: index > 0 ? index : null},
        queryParamsHandling: 'merge',
      })
      .toString();

    this.location.replaceState(url);
  }

  seeMoreInfo(): void {
    if (this.mediaItem?.id) {
      const url = this.router.serializeUrl(
        this.router.createUrlTree(['/gallery', this.mediaItem.id], {
          queryParams: {
            img_index: this.selectedIndex > 0 ? this.selectedIndex : null,
          },
        }),
      );
      window.open(url, '_blank');
    }
  }

  get isVideo(): boolean {
    return this.mediaItem?.mimeType?.startsWith('video/') ?? false;
  }

  get isYoutubeVideo(): boolean {
    return (this.mediaItem as any)?.metadata?.assetType === 'youtube_video';
  }

  get isAudio(): boolean {
    return this.mediaItem?.mimeType?.startsWith('audio/') ?? false;
  }

  get posterUrl(): string | undefined {
    if (this.isVideo && this.mediaItem?.presignedThumbnailUrls?.length) {
      return this.mediaItem.presignedThumbnailUrls[this.selectedIndex];
    }
    return undefined;
  }

  get aspectRatioClass(): string {
    // Allow the audio stage to grow cleanly when lyrics / structure are shown.
    if (this.isAudio) {
      return this.hasCurrentTrackText() ? 'h-auto' : 'aspect-video h-auto';
    }

    // For Videos, we can still use the aspect ratio if available
    if (this.isVideo) {
      const ratio =
        this.mediaItem?.aspectRatio || (this.mediaItem as any).aspect;
      if (ratio === '1:1') return 'aspect-square';
      if (ratio === '16:9') return 'aspect-video';
      if (ratio && ratio.includes(':'))
        return `aspect-[${ratio.replace(':', '/')}]`;
      return 'aspect-video'; // Default for video
    }

    // For Images, we don't want to enforce an aspect ratio on the container
    // as it causes stretching. We'll let the image's natural ratio prevail.
    return '';
  }

  copyCurrentTrackText(): void {
    const text = formatTrackAnalysisForCopy(this.currentTrackAnalysis());
    if (!text) return;
    this.clipboard.copy(text);
    handleSuccessSnackbar(this.snackBar, 'Copied to clipboard!');
  }

  // --- AUDIO PLAYER & WAVEFORM LOGIC ---
  togglePlay() {
    const audio = this.audioPlayerRef?.nativeElement;
    if (!audio) return;

    if (audio.paused) {
      void audio.play().catch(err => {
        console.warn('Audio playback prevented:', err);
        this.onAudioPause();
      });
      this.onAudioPlay();
    } else {
      audio.pause();
      this.onAudioPause();
    }
  }

  onAudioPlay(): void {
    this.isPlaying = true;
    this.startPlayheadAnimation();
  }

  onAudioPause(): void {
    this.isPlaying = false;
    this.stopPlayheadAnimation();
  }

  private setDurationSeconds(dur: number): void {
    if (this.durationSeconds() !== dur) {
      this.durationSeconds.set(dur);
      this.duration = formatAudioClock(dur);
    }
  }

  onTimeUpdate() {
    const audio = this.audioPlayerRef?.nativeElement;
    if (!audio?.duration || !Number.isFinite(audio.duration)) return;

    this.setDurationSeconds(audio.duration);
    this.progressValue = (audio.currentTime / audio.duration) * 100;
    this.currentTime = formatAudioClock(audio.currentTime);
  }

  seek(value: number) {
    const clamped = Math.max(0, Math.min(100, value));
    this.progressValue = clamped;

    const audio = this.audioPlayerRef?.nativeElement;
    if (audio?.duration && Number.isFinite(audio.duration)) {
      audio.currentTime = (clamped / 100) * audio.duration;
      this.currentTime = formatAudioClock(audio.currentTime);
    }
  }

  onAudioLoaded() {
    const audio = this.audioPlayerRef?.nativeElement;
    if (!audio) return;

    this.isPlaying = !audio.paused;
    if (Number.isFinite(audio.duration) && audio.duration > 0) {
      this.setDurationSeconds(audio.duration);
    }
  }

  onAudioEnded() {
    this.onAudioPause();
    this.progressValue = 0;
    this.currentTime = '0:00';
  }

  trackByIndex(index: number): number {
    return index;
  }

  private barMidpointPct(index: number, totalBars: number): number {
    return ((index + 0.5) / Math.max(1, totalBars)) * 100;
  }

  isBarPlayed(index: number, totalBars: number): boolean {
    return this.barMidpointPct(index, totalBars) <= this.progressValue;
  }

  isBarHovered(index: number, totalBars: number): boolean {
    const hover = this.hoverProgress();
    if (hover === null) return false;
    const mid = this.barMidpointPct(index, totalBars);
    return mid > this.progressValue && mid <= hover;
  }

  private updateScrubFromPointer(
    event: PointerEvent,
    startScrub = false,
  ): void {
    const target = event.currentTarget as HTMLElement | null;
    if (!target) return;
    if (startScrub) {
      try {
        target.setPointerCapture?.(event.pointerId);
      } catch {
        // Synthetic PointerEvents in headless tests may not have an active pointerId.
      }
      this.isScrubbing.set(true);
    }
    const pct = this.computePointerPercentage(event, target);
    this.hoverProgress.set(pct);
    if (this.isScrubbing()) {
      this.seek(pct);
    }
  }

  onWaveformPointerDown(event: PointerEvent): void {
    this.updateScrubFromPointer(event, true);
  }

  onWaveformPointerMove(event: PointerEvent): void {
    this.updateScrubFromPointer(event);
  }

  onWaveformPointerUp(event: PointerEvent): void {
    const target = event.currentTarget as HTMLElement | null;
    if (target && this.isScrubbing()) {
      try {
        if (target.hasPointerCapture?.(event.pointerId)) {
          target.releasePointerCapture(event.pointerId);
        }
      } catch {
        // Ignore synthetic test events without active pointer capture.
      }
    }
    this.isScrubbing.set(false);
  }

  onWaveformPointerLeave(): void {
    if (!this.isScrubbing()) {
      this.hoverProgress.set(null);
    }
  }

  onWaveformKeyDown(event: KeyboardEvent): void {
    const seekTargets: Record<string, number> = {
      ArrowRight: this.progressValue + 5,
      ArrowUp: this.progressValue + 5,
      ArrowLeft: this.progressValue - 5,
      ArrowDown: this.progressValue - 5,
      Home: 0,
      End: 100,
    };
    if (event.key in seekTargets) {
      event.preventDefault();
      this.seek(seekTargets[event.key]);
    } else if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      this.togglePlay();
    }
  }

  private computePointerPercentage(
    event: MouseEvent | PointerEvent,
    element: HTMLElement,
  ): number {
    const rect = element.getBoundingClientRect();
    if (!rect.width) return 0;
    return Math.max(
      0,
      Math.min(100, ((event.clientX - rect.left) / rect.width) * 100),
    );
  }

  /**
   * Moves the waveform playhead smoothly between `timeupdate` events.
   *
   * Runs outside Angular and only writes the playhead's `left` style: a
   * zone-patched rAF loop would run app-wide change detection on every frame.
   * `onTimeUpdate()` keeps `progressValue`, the played bars and the time label
   * up to date inside the zone.
   */
  private startPlayheadAnimation(): void {
    this.stopPlayheadAnimation();
    if (typeof requestAnimationFrame === 'undefined') return;
    const step = () => {
      const audio = this.audioPlayerRef?.nativeElement;
      if (!audio || audio.paused) {
        this.playheadRafId = null;
        return;
      }
      const playhead = this.waveformPlayheadRef?.nativeElement;
      if (playhead && audio.duration && Number.isFinite(audio.duration)) {
        playhead.style.left = `${(audio.currentTime / audio.duration) * 100}%`;
      }
      this.playheadRafId = requestAnimationFrame(step);
    };
    this.ngZone.runOutsideAngular(() => {
      this.playheadRafId = requestAnimationFrame(step);
    });
  }

  private stopPlayheadAnimation(): void {
    if (
      this.playheadRafId !== null &&
      typeof cancelAnimationFrame !== 'undefined'
    ) {
      cancelAnimationFrame(this.playheadRafId);
      this.playheadRafId = null;
    }
  }

  private resetAudioState() {
    this.onAudioPause();
    this.progressValue = 0;
    this.currentTime = '0:00';
    this.duration = '0:00';
    this.durationSeconds.set(0);
    this.hoverProgress.set(null);
    this.isScrubbing.set(false);
  }

  onEditClick(): void {
    this.editClicked.emit(this.selectedIndex);
  }

  onGenerateVideoClick(role: 'start' | 'end'): void {
    this.generateVideoClicked.emit({role, index: this.selectedIndex});
  }

  onSendToVtoClick(): void {
    this.sendToVtoClicked.emit(this.selectedIndex);
  }

  onEditWithOmniClick(): void {
    if (this.mediaItem) {
      this.editWithOmniClicked.emit({
        mediaItem: this.mediaItem as MediaItem,
        selectedIndex: this.selectedIndex,
      });
    }
  }

  onExtendWithAiClick() {
    if (this.mediaItem) {
      this.extendWithAiClicked.emit({
        mediaItem: this.mediaItem as MediaItem,
        selectedIndex: this.selectedIndex,
      });
    }
  }

  onConcatenateClick() {
    if (this.mediaItem) {
      this.concatenateClicked.emit({
        mediaItem: this.mediaItem as MediaItem,
        selectedIndex: this.selectedIndex,
      });
    }
  }

  toggleVideoPlay() {
    const video = this.videoPlayerRef?.nativeElement;
    if (!video) return;

    if (video.paused) {
      void video.play();
    } else {
      video.pause();
    }
  }

  openAssignTagsDialog(): void {
    const dialogRef = this.dialog.open(AssignTagsDialogComponent, {
      data: {
        assetId: this.mediaItem?.id,
        assetType: (this.mediaItem as any).itemType || 'media_item',
        existingTags: ((this.mediaItem as any)?.tags || []).map((t: any) =>
          typeof t === 'object' ? t.name : t,
        ),
      },
      width: '400px',
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (this.mediaItem) {
          const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
          if (!workspaceId) return;

          this.tagsService
            .bulkAssign(
              workspaceId,
              [this.mediaItem.id],
              (this.mediaItem as any).itemType || 'media_item',
              result,
            )
            .subscribe({
              next: () => {
                this.snackBar.open('Tags assigned successfully', 'Close', {
                  duration: 3000,
                });
                this.tagsChanged.emit(result);
              },
              error: err =>
                handleErrorSnackbar(this.snackBar, err, 'Assign tags'),
            });
        }
      }
    });
  }

  onDeleteClick() {
    this.deleteClicked.emit(this.selectedIndex);
  }
}
