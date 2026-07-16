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
  signal,
  computed,
  ViewChild,
  ViewChildren,
  QueryList,
  ElementRef,
  OnDestroy,
  HostListener,
  effect,
  inject,
  OnInit,
  Inject,
  PLATFORM_ID,
} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {HttpClient} from '@angular/common/http';
import {MatIconRegistry} from '@angular/material/icon';
import {
  DomSanitizer,
  SafeResourceUrl,
  SafeUrl,
} from '@angular/platform-browser';
import {MatDialog} from '@angular/material/dialog';
import {
  ImageSelectorComponent,
  MediaItemSelection,
} from '../common/components/image-selector/image-selector.component';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../common/services/source-asset.service';
// --- Interfaces ---
import {WorkbenchService, RenderTimelineRequest} from './workbench.service';
import {AgentChatService} from './services/agent-chat.service';
import {TimeRulerComponent} from './components/time-ruler/time-ruler.component';
import {TimelineStateService} from './services/timeline-state.service';
import {PlayheadSyncService} from './services/playhead-sync.service';
import {
  TimelineDTO,
  VideoClipDTO,
  AudioClipDTO,
  TransitionType,
  TimelineClip,
  MediaAsset,
} from '../common/models/workbench.model';
import {ActivatedRoute} from '@angular/router';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {
  Subject,
  Subscription,
  of,
  Observable,
  interval,
  throwError,
} from 'rxjs';
import {debounceTime, switchMap, takeWhile, catchError} from 'rxjs/operators';
import {StoryboardService} from '../services/storyboard/storyboard.service';
import {GalleryService} from '../gallery/gallery.service';
import {MediaItem} from '../common/models/media-item.model';

@Component({
  selector: 'app-workbench',
  templateUrl: './workbench.component.html',
  styleUrls: ['./workbench.component.scss'],
})
export class WorkbenchComponent implements OnInit, OnDestroy {
  // Signals for State

  activeToolButton = signal<
    'gallery' | 'audio' | 'stories' | 'edit' | 'agent' | null
  >(null);
  isVideoHidden = signal<boolean>(false);
  lockedTracks = signal<Set<number>>(new Set());
  mutedTracks = signal<Set<number>>(new Set());

  currentScroll = signal<number>(0);
  containerWidthSignal = signal<number>(0);
  isPausing = false;

  // Simple tab between video/audio assets (UX only)
  activeTab = signal<'video' | 'audio'>('video');

  // Visual Settings (Lighting & Zoom)
  exposureVal = 100;
  contrastVal = 100;
  saturateVal = 100;

  // Filtered assets list based on active tab
  filteredAssets = computed(() => {
    const tab = this.activeTab();
    return this.timelineState.assets().filter(a => a.type === tab);
  });

  videoTrackEnd = computed(() => {
    const clips = this.timelineState.videoClips();
    return clips.length > 0
      ? Math.max(...clips.map(c => c.startTime + c.duration))
      : 0;
  });

  timelineWidth = computed(() => {
    // Ensure timeline is at least screen width or longer based on content
    return (
      this.timelineState.totalDuration() *
        this.timelineState.pixelsPerSecond() +
      this.containerWidthSignal()
    );
  });

  selectedClipIndex = computed(() => {
    const id = this.timelineState.selectedClipId();
    if (!id) return -1;
    return this.timelineState.videoClips().findIndex(c => c.id === id);
  });

  activeVideoSrc = computed(() => {
    const clip = this.timelineState.activeVideoClip();
    if (!clip) return '';
    const asset = this.timelineState.assets().find(a => a.id === clip.assetId);
    return asset ? asset.safeUrl : '';
  });

  activeAudioSrcs = computed(() => {
    return this.timelineState.activeAudioClips().map(clip => {
      if (!clip) return '';
      const asset = this.timelineState
        .assets()
        .find(a => a.id === clip.assetId);
      return asset ? asset.safeUrl : '';
    });
  });

  videoFilter = computed(() => {
    return `brightness(${this.exposureVal}%) contrast(${this.contrastVal}%) saturate(${this.saturateVal}%)`;
  });

  // View Children
  @ViewChildren('timelineVideo') timelineVideos!: QueryList<
    ElementRef<HTMLVideoElement>
  >;

  private applyVideoFilter() {
    const filterValue = this.videoFilter();
    this.timelineVideos?.forEach(video => {
      if (video.nativeElement) {
        video.nativeElement.style.filter = filterValue;
      }
    });
  }
  @ViewChildren('bgAudio') bgAudios!: QueryList<ElementRef<HTMLAudioElement>>;
  @ViewChild(TimeRulerComponent) timeRuler!: TimeRulerComponent;
  @ViewChild('timelineContainer')
  timelineContainer!: ElementRef<HTMLDivElement>;
  @ViewChild('dummyScrollContainer')
  dummyScrollContainer!: ElementRef<HTMLDivElement>;

  // Services
  private sanitizer = inject(DomSanitizer);
  private workbenchService = inject(WorkbenchService);
  private http = inject(HttpClient);
  private agentChatService = inject(AgentChatService);
  protected timelineState = inject(TimelineStateService);
  protected playbackService = inject(PlayheadSyncService);
  private route = inject(ActivatedRoute);
  private storyboardService = inject(StoryboardService);
  private galleryService = inject(GalleryService);

  private workspaceStateService = inject(WorkspaceStateService);
  private sourceAssetService = inject(SourceAssetService);

  isDownloading = signal(false);

  // Trimming state (for clip in/out adjustments)
  trimState: {
    active: boolean;
    clipId: string;
    type: 'start' | 'end';
    startX: number;
    initialStart: number;
    initialDur: number;
    initialOffset: number;
    hasMoved?: boolean;
  } | null = null;

  // Drag state for moving clips along the timeline
  dragState: {
    active: boolean;
    clipId: string;
    startX: number;
    initialStartTime: number;
    hasMoved?: boolean;
  } | null = null;

  isBrowser: boolean;
  lastSavedText = signal<string>('');

  private saveSubject = new Subject<void>();
  private saveSubscription?: Subscription;
  private activeSaveSubscription?: Subscription;
  private hasPendingSave = false;
  private isSaving = false;

  constructor(
    public matIconRegistry: MatIconRegistry,
    private dialog: MatDialog,
    @Inject(PLATFORM_ID) platformId: Object,
  ) {
    this.isBrowser = isPlatformBrowser(platformId);

    effect(() => {
      this.applyVideoFilter();
    });

    // Setup an effect to handle storyboard loading from signal
    effect(
      () => {
        const storyboard = this.agentChatService.currentStoryboard();
        if (this.isSaving) {
          return;
        }
        if (storyboard && storyboard.timeline_id) {
          if (
            this.timelineState.loadedTimelineId() === storyboard.timeline_id
          ) {
            return;
          }
          this.timelineState.loadedTimelineId.set(storyboard.timeline_id);
          this.workbenchService.getTimeline(storyboard.timeline_id).subscribe({
            next: (timeline: TimelineDTO) => {
              this.processGeneratedData(timeline);
              this.lastSavedText.set('Saved');
            },
            error: err => {
              console.error('Failed to fetch timeline:', err);
              this.lastSavedText.set('Failed to load timeline');
            },
          });
        } else {
          this.timelineState.loadedTimelineId.set(undefined);
          this.timelineState.timelineClips.set([]);
          this.timelineState.selectedClipId.set(null);
          this.timelineState.assets.set([]);
          this.timelineState.currentTime.set(0);
          this.timelineState.isPlaying.set(false);
          this.timelineState.scrollOffset.set(0);
          this.lastSavedText.set('');
        }
      },
      {allowSignalWrites: true},
    );

    // Pause playback when switching away from video player to agent view
    effect(
      () => {
        if (
          this.activeToolButton() === 'agent' &&
          this.timelineState.isPlaying()
        ) {
          const lastScroll = this.timelineState.scrollOffset();
          this.timelineState.isPlaying.set(false);
          this.playbackService.stopLoop();
          if (this.dummyScrollContainer?.nativeElement) {
            this.dummyScrollContainer.nativeElement.scrollLeft = lastScroll;
          }
        }
      },
      {allowSignalWrites: true},
    );

    this.matIconRegistry
      .addSvgIcon(
        'white-gemini-spark-icon',
        this.setPath(`${this.path}/mobile-white-gemini-spark-icon.svg`),
      )
      .addSvgIcon(
        'creative-studio-icon',
        this.setPath(`${this.path}/creative-studio-icon.svg`),
      )
      .addSvgIcon(
        'mobile-white-gemini-spark-icon',
        this.setPath(`${this.path}/mobile-white-gemini-spark-icon.svg`),
      )
      .addSvgIcon(
        'creative-studio-icon',
        this.setPath(`${this.path}/creative-studio-icon.svg`),
      )
      .addSvgIcon(
        'fun-templates-icon',
        this.setPath(`${this.path}/fun-templates-icon.svg`),
      )
      .addSvgIcon(
        'video-clap-icon',
        this.setPath(`${this.path}/video-clap-icon.svg`),
      )
      .addSvgIcon(
        'movie-shallow-icon',
        this.setPath(`${this.path}/movie-clap-shallow-icon.svg`),
      )
      .addSvgIcon(
        'volume-off-icon',
        this.setPath(`${this.path}/volume-off-icon.svg`),
      )
      .addSvgIcon('upload-icon', this.setPath(`${this.path}/upload-icon.svg`))
      .addSvgIcon(
        'sound-sensing-icon',
        this.setPath(`${this.path}/sound-sensing-icon.svg`),
      )
      .addSvgIcon('lock-icon', this.setPath(`${this.path}/lock-icon.svg`))
      .addSvgIcon('img-icon', this.setPath(`${this.path}/img-icon.svg`))
      .addSvgIcon('eye-icon', this.setPath(`${this.path}/eye-icon.svg`))
      .addSvgIcon('drive-icon', this.setPath(`${this.path}/drive-icon.svg`))
      .addSvgIcon(
        'audio-magic-eraser-icon',
        this.setPath(`${this.path}/audio_magic_eraser-icon.svg`),
      )
      .addSvgIcon(
        'play-arrow-icon',
        this.setPath(`${this.path}/play-arrow-icon.svg`),
      )
      .addSvgIcon('square-icon', this.setPath(`${this.path}/square.svg`))
      .addSvgIcon('phone-icon', this.setPath(`${this.path}/pixel-9.svg`))
      .addSvgIcon(
        'lightbulb-icon',
        this.setPath(`${this.path}/lightbulb-tips.svg`),
      )
      .addSvgIcon('desktop-icon', this.setPath(`${this.path}/desktop.svg`))
      .addSvgIcon(
        'desktop-mac-icon',
        this.setPath(`${this.path}/desktop-mac.svg`),
      )
      .addSvgIcon('edit-icon', this.setPath(`${this.path}/edit.svg`))
      .addSvgIcon(
        'gemini-spark-icon',
        this.setPath(`${this.path}/gemini-spark.svg`),
      )
      .addSvgIcon(
        'photo-merge-auto-icon',
        this.setPath(`${this.path}/photo-merge-auto.svg`),
      )
      .addSvgIcon(
        'web-stories-icon',
        this.setPath(`${this.path}/web-stories.svg`),
      );
  }

  private path = '../../../assets/images';

  private setPath(url: string): SafeResourceUrl {
    return this.sanitizer.bypassSecurityTrustResourceUrl(url);
  }

  // Signal to track audio element changes
  audioElementsChanged = signal<number>(0);

  onCloseAgentView() {
    this.activeToolButton.set(null);
  }

  toggleVideoVisibility() {
    this.isVideoHidden.update(v => !v);
  }

  toggleTrackLock(trackIndex: number) {
    this.lockedTracks.update(prev => {
      const next = new Set(prev);
      if (next.has(trackIndex)) next.delete(trackIndex);
      else next.add(trackIndex);
      return next;
    });
  }

  toggleTrackMute(trackIndex: number) {
    this.mutedTracks.update(prev => {
      const next = new Set(prev);
      if (next.has(trackIndex)) next.delete(trackIndex);
      else next.add(trackIndex);
      return next;
    });
  }

  isTrackLocked(trackIndex: number): boolean {
    return this.lockedTracks().has(trackIndex);
  }

  isTrackMuted(trackIndex: number): boolean {
    return this.mutedTracks().has(trackIndex);
  }

  ngOnInit() {
    // save timeline after 10 seconds of inactivity
    this.saveSubscription = this.saveSubject
      .pipe(debounceTime(10000))
      .subscribe(() => {
        this.hasPendingSave = false;
        this.saveTimeline();
      });

    this.route.queryParams.subscribe(params => {
      const sessionId = params['sessionId'];
      const storyboardId = params['storyboardId'];

      if (sessionId) {
        this.agentChatService.selectedSessionId.set(sessionId);
      }

      if (sessionId || storyboardId) {
        this.activeToolButton.set('agent');
      }
    });
  }

  ngAfterViewInit() {
    this.bgAudios.changes.subscribe(() => {
      this.audioElementsChanged.update(v => v + 1);
      this.registerPlaybackElements();
    });

    this.timelineVideos.changes.subscribe(() => {
      this.registerPlaybackElements();
      this.applyVideoFilter();
    });

    // Set initial container width for timeline
    if (this.timelineContainer?.nativeElement) {
      this.containerWidthSignal.set(
        this.timelineContainer.nativeElement.clientWidth,
      );
    }

    this.registerPlaybackElements();
  }

  private registerPlaybackElements() {
    const videoElements =
      this.timelineVideos?.toArray().map(e => e.nativeElement) || [];
    this.playbackService.registerElements({
      videos: videoElements,
      audios: this.bgAudios?.toArray().map(e => e.nativeElement) || [],
      timeline: this.timelineContainer?.nativeElement,
      dummyScroll: this.dummyScrollContainer?.nativeElement,
      timeRuler: this.timeRuler,
    });
  }

  @HostListener('window:resize')
  onResize() {
    if (this.timelineContainer?.nativeElement) {
      this.containerWidthSignal.set(
        this.timelineContainer.nativeElement.clientWidth,
      );
    }
  }

  ngOnDestroy() {
    this.playbackService.stopLoop();
    if (this.hasPendingSave) {
      this.saveTimeline();
    } else if (this.activeSaveSubscription) {
      this.activeSaveSubscription.unsubscribe();
    }
    if (this.saveSubscription) {
      this.saveSubscription.unsubscribe();
    }
  }

  // --- Logic: File Handling ---
  onFileSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    if (!input.files) return;

    Array.from(input.files).forEach(file => {
      const isVideo = file.type.startsWith('video');
      const isAudio = file.type.startsWith('audio');
      if (!isVideo && !isAudio) return;

      const objectUrl = window.URL.createObjectURL(file);
      const id = Math.random().toString(36).substr(2, 9);

      const asset: MediaAsset = {
        id,
        name: file.name,
        type: isVideo ? 'video' : 'audio',
        url: objectUrl,
        // Use bypassSecurityTrustUrl for media src
        safeUrl: this.sanitizer.bypassSecurityTrustUrl(objectUrl),
        duration: 0,
      };

      this.timelineState.assets.update(prev => [...prev, asset]);

      if (isVideo) {
        this.extractVideoMetadata(asset, file);
      } else {
        this.extractAudioMetadata(asset);
      }
    });

    input.value = '';
  }

  // --- Cloud Media Selection ---
  openMediaSelector() {
    const mimeType = this.activeTab() === 'video' ? 'video/*' : 'audio/*';
    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: mimeType,
        showFooter: true,
        maxSelection: 10,
        multiSelect: true,
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef
      .afterClosed()
      .subscribe((result: MediaItemSelection | SourceAssetResponseDto) => {
        if (result) {
          // Normalize to an array: if it's already an array, use it;
          // if it's a single object, wrap it in an array.
          const results = Array.isArray(result) ? result : [result];

          // Process each result individually
          results.forEach(res => {
            this.processCloudMediaResult(res);
          });
        }
      });
  }

  private processCloudMediaResult(
    result: MediaItemSelection | SourceAssetResponseDto,
  ) {
    const isGalleryItem = 'mediaItem' in result;

    let url: string;
    let name: string;
    let type: 'video' | 'audio';
    let thumbnail: string | undefined;

    let mediaItemId: number | undefined;
    let sourceAssetId: number | undefined;

    if (isGalleryItem) {
      const selection = result as MediaItemSelection;
      const mediaItem = selection.mediaItem;
      const selectedIndex = selection.selectedIndex || 0;
      url = mediaItem.presignedUrls?.[selectedIndex] || '';
      name = mediaItem.prompt || 'Cloud Media';
      // Determine type from mimeType or default to current tab
      type = mediaItem.mimeType?.startsWith('audio') ? 'audio' : 'video';
      // Use presignedThumbnailUrls for videos
      thumbnail =
        type === 'video'
          ? mediaItem.presignedThumbnailUrls?.[selectedIndex] || url
          : undefined;
      mediaItemId = mediaItem.id;
    } else {
      const asset = result as SourceAssetResponseDto;
      url = asset.presignedUrl || '';
      name = asset.originalFilename || 'Source Asset';
      type = asset.mimeType?.startsWith('audio') ? 'audio' : 'video';
      // Use presignedThumbnailUrl for videos, fallback to presignedUrl
      thumbnail =
        type === 'video'
          ? asset.presignedThumbnailUrl || asset.presignedUrl
          : undefined;
      sourceAssetId = asset.id;
    }

    if (!url) return;

    const id = Math.random().toString(36).substr(2, 9);
    const newAsset: MediaAsset = {
      id,
      name,
      type,
      url,
      safeUrl: this.sanitizer.bypassSecurityTrustUrl(url),
      duration: 0,
      thumbnail,
      mediaItemId,
      sourceAssetId,
    };

    this.timelineState.assets.update(prev => [...prev, newAsset]);

    // Extract duration from the cloud media
    if (type === 'video') {
      this.extractVideoMetadataFromUrl(newAsset);
    } else {
      this.extractAudioMetadataFromUrl(newAsset);
    }
  }

  private extractVideoMetadataFromUrl(asset: MediaAsset) {
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.crossOrigin = 'anonymous';
    video.src = asset.url;
    video.onloadedmetadata = () => {
      this.updateAssetDuration(asset.id, video.duration);
      video.currentTime = Math.min(1, video.duration / 4);
    };
    video.onseeked = () => {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = 160;
        canvas.height = 90;
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          const thumbUrl = canvas.toDataURL('image/jpeg');
          this.timelineState.assets.update(items =>
            items.map(i =>
              i.id === asset.id ? {...i, thumbnail: thumbUrl} : i,
            ),
          );
        }
      } catch (e) {
        // CORS may prevent thumbnail generation for cloud assets
        console.warn('Could not generate thumbnail for cloud asset', e);
      }
    };
    video.onerror = () => {
      // If video fails to load metadata, set a default duration
      this.updateAssetDuration(asset.id, 10);
    };
  }

  private extractAudioMetadataFromUrl(asset: MediaAsset) {
    const audio = document.createElement('audio');
    audio.crossOrigin = 'anonymous';
    audio.muted = true;
    audio.volume = 0; // Double safety
    audio.autoplay = false;
    audio.src = asset.url;
    audio.onloadedmetadata = () => {
      this.updateAssetDuration(asset.id, audio.duration);
    };
    audio.onerror = e => {
      // If audio fails to load metadata, set a default duration
      this.updateAssetDuration(asset.id, 10);
    };
  }

  extractVideoMetadata(asset: MediaAsset, file: File) {
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.muted = true;
    video.volume = 0;
    video.autoplay = false;
    video.src = asset.url;
    video.onloadedmetadata = () => {
      this.updateAssetDuration(asset.id, video.duration);
      video.currentTime = Math.min(1, video.duration / 4);
    };

    video.onseeked = () => {
      const canvas = document.createElement('canvas');
      canvas.width = 160;
      canvas.height = 90;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const thumbUrl = canvas.toDataURL('image/jpeg');
        this.timelineState.assets.update(items =>
          items.map(i => (i.id === asset.id ? {...i, thumbnail: thumbUrl} : i)),
        );
      }
    };
  }

  extractAudioMetadata(asset: MediaAsset) {
    const audio = document.createElement('audio');
    audio.muted = true;
    audio.volume = 0;
    audio.autoplay = false;
    audio.src = asset.url;
    audio.onloadedmetadata = () => {
      this.updateAssetDuration(asset.id, audio.duration);
    };
  }

  updateAssetDuration(id: string, duration: number) {
    this.timelineState.assets.update(items =>
      items.map(i => (i.id === id ? {...i, duration} : i)),
    );
    this.timelineState.timelineClips.update(clips => {
      const updated = clips.map(clip => {
        if (clip.assetId === id) {
          if (clip.duration === 0 || clip.isDurationPlaceholder) {
            const clipSpeed = clip.speed !== undefined ? clip.speed : 1.0;
            const targetDuration = duration / clipSpeed;
            const updatedClip = {...clip, duration: targetDuration};
            delete updatedClip.isDurationPlaceholder;
            return updatedClip;
          }
        }
        return clip;
      });
      return this.recalculateAudioTracks(updated);
    });
    this.refreshTimelineLayout();
  }

  private recalculateAudioTracks(clips: TimelineClip[]): TimelineClip[] {
    const videoClips = clips.filter(c => c.trackIndex === 0);
    const audioClips = clips.filter(c => c.trackIndex > 0);

    // Sort audio clips by startTime to ensure deterministic and clean layout
    audioClips.sort((a, b) => a.startTime - b.startTime);

    const updatedAudioClips: TimelineClip[] = [];

    audioClips.forEach(clip => {
      const targetTrack = this.findNextAvailableTrackForClip(
        clip.startTime,
        clip.duration,
        updatedAudioClips,
      );
      updatedAudioClips.push({
        ...clip,
        trackIndex: targetTrack,
      });
    });

    return [...videoClips, ...updatedAudioClips];
  }

  private findNextAvailableTrackForClip(
    startTime: number,
    duration: number,
    existingAudioClips: TimelineClip[],
  ): number {
    let targetTrack = 1;
    let placed = false;

    while (!placed) {
      const trackClips = existingAudioClips.filter(
        c => c.trackIndex === targetTrack,
      );
      const hasOverlap = trackClips.some(c => {
        const cEnd = c.startTime + c.duration;
        const newEnd = startTime + duration;
        return startTime < cEnd && newEnd > c.startTime;
      });

      if (!hasOverlap) {
        placed = true;
      } else {
        targetTrack++;
      }
    }
    return targetTrack;
  }

  onThumbnailError(asset: MediaAsset) {
    // Clear the thumbnail if it fails to load, so the placeholder icon shows
    this.timelineState.assets.update(items =>
      items.map(i => (i.id === asset.id ? {...i, thumbnail: undefined} : i)),
    );
  }

  refreshTimelineLayout() {
    this.timelineState.timelineClips.update(clips => {
      const vClips = clips.filter(c => c.trackIndex === 0);
      const otherClips = clips.filter(c => c.trackIndex !== 0);

      const layoutTrack = (trackClips: TimelineClip[]) => {
        let currentTime = 0;
        return trackClips.map(clip => {
          const newClip = {...clip, startTime: currentTime};
          currentTime += clip.duration;
          return newClip;
        });
      };

      return [...layoutTrack(vClips), ...otherClips];
    });
  }

  processGeneratedData(data: TimelineDTO) {
    const newClips: TimelineClip[] = [];
    const videoStartTimes: number[] = [];
    const assetsToExtract: MediaAsset[] = [];

    // Save transitions metadata

    this.timelineState.transitions.set(data.transitions || []);
    this.timelineState.transitionIn.set(data.transition_in || null);
    this.timelineState.transitionOut.set(data.transition_out || null);

    // Handle Video Clips
    let currentVideoTime = 0;
    if (data.video_clips) {
      data.video_clips.forEach((clip: VideoClipDTO, idx: number) => {
        const mediaItemId =
          clip.asset_ref?.type === 'media_item'
            ? Number(clip.asset_ref.id)
            : undefined;
        const sourceAssetId =
          clip.asset_ref?.type === 'source_asset'
            ? Number(clip.asset_ref.id)
            : undefined;
        const speed =
          clip.speed !== undefined && clip.speed !== null ? clip.speed : 1.0;
        const trimDuration = (clip.trim?.duration_seconds || 5) / speed;
        const trimOffset = clip.trim?.offset_seconds || 0;

        const assetId = String(mediaItemId || sourceAssetId || '');
        const isPlaceholder = !clip.trim?.duration_seconds;

        // Populate assets signal so lookup works
        let existingAsset = this.timelineState
          .assets()
          .find(a => a.id === assetId);
        if (!existingAsset && clip.presigned_url) {
          existingAsset = {
            id: assetId,
            name: 'Clip ' + assetId,
            type: 'video',
            url: clip.presigned_url!,
            safeUrl: this.sanitizer.bypassSecurityTrustUrl(clip.presigned_url!),
            duration: trimDuration,
            thumbnail: clip.presigned_thumbnail_url || undefined,
            mediaItemId: mediaItemId,
            sourceAssetId: sourceAssetId,
          };
          this.timelineState.assets.update(prev => [...prev, existingAsset!]);
        }

        if (isPlaceholder && existingAsset) {
          if (!assetsToExtract.some(a => a.id === existingAsset!.id)) {
            assetsToExtract.push(existingAsset);
          }
        }

        const transitionInfo = data.transitions && data.transitions[idx];
        const transitionType = transitionInfo
          ? transitionInfo.type
          : TransitionType.NONE;
        const transitionDuration = transitionInfo
          ? transitionInfo.duration_seconds
          : 0;

        newClips.push({
          id: Math.random().toString(36).substr(2, 9),
          assetId: assetId,
          startTime: currentVideoTime,
          duration: trimDuration,
          offset: trimOffset,
          trackIndex: 0,
          color: '#3b82f6',
          mediaItemId: mediaItemId,
          sourceAssetId: sourceAssetId,
          first_frame_asset_ref: clip.first_frame_asset_ref || null,
          last_frame_asset_ref: clip.last_frame_asset_ref || null,
          placeholder: clip.placeholder || null,
          isDurationPlaceholder: isPlaceholder || undefined,
          volume:
            clip.volume !== undefined && clip.volume !== null
              ? clip.volume
              : 1.0,
          speed:
            clip.speed !== undefined && clip.speed !== null ? clip.speed : 1.0,
          transition_to_next_type: transitionType,
          transition_to_next_duration: transitionDuration,
        });
        videoStartTimes.push(currentVideoTime);
        currentVideoTime += trimDuration - transitionDuration / 2;
      });
    }

    // Handle Audio Clips
    if (data.audio_clips) {
      data.audio_clips.forEach((clip: AudioClipDTO) => {
        const mediaItemId =
          clip.asset_ref?.type === 'media_item'
            ? Number(clip.asset_ref.id)
            : undefined;
        const sourceAssetId =
          clip.asset_ref?.type === 'source_asset'
            ? Number(clip.asset_ref.id)
            : undefined;
        const speed =
          clip.speed !== undefined && clip.speed !== null ? clip.speed : 1.0;
        const trimDuration = (clip.trim?.duration_seconds || 5) / speed;
        const trimOffset = clip.trim?.offset_seconds || 0;

        let startTime = clip.start_at?.offset_seconds || 0;
        const vClipIndex = clip.start_at?.video_clip_index;
        if (
          vClipIndex !== undefined &&
          vClipIndex !== null &&
          vClipIndex >= 0 &&
          vClipIndex < videoStartTimes.length
        ) {
          startTime =
            videoStartTimes[vClipIndex] + (clip.start_at?.offset_seconds || 0);
        }

        const assetId = clip.presigned_url || '';
        const isPlaceholder = !clip.trim?.duration_seconds;

        // Populate assets signal
        let existingAsset = this.timelineState
          .assets()
          .find(a => a.id === assetId);
        if (!existingAsset && clip.presigned_url) {
          existingAsset = {
            id: assetId,
            name: 'Audio ' + assetId,
            type: 'audio',
            url: clip.presigned_url!,
            safeUrl: this.sanitizer.bypassSecurityTrustUrl(clip.presigned_url!),
            duration: trimDuration,
            mediaItemId: mediaItemId,
            sourceAssetId: sourceAssetId,
          };
          this.timelineState.assets.update(prev => [...prev, existingAsset!]);
        }

        if (isPlaceholder && existingAsset) {
          if (!assetsToExtract.some(a => a.id === existingAsset!.id)) {
            assetsToExtract.push(existingAsset);
          }
        }

        // Find available track among newClips
        const duration = trimDuration;
        const allAudioClips = newClips.filter(c => c.trackIndex > 0);
        let targetTrack = 1;
        let found = false;
        while (!found) {
          const trackClips = allAudioClips.filter(
            c => c.trackIndex === targetTrack,
          );
          const hasOverlap = trackClips.some(c => {
            return (
              (startTime >= c.startTime &&
                startTime < c.startTime + c.duration) ||
              (startTime + duration > c.startTime &&
                startTime + duration <= c.startTime + c.duration) ||
              (startTime <= c.startTime &&
                startTime + duration >= c.startTime + c.duration)
            );
          });
          if (!hasOverlap) {
            found = true;
          } else {
            targetTrack++;
          }
        }

        newClips.push({
          id: Math.random().toString(36).substr(2, 9),
          assetId: assetId,
          startTime: startTime,
          duration: duration,
          offset: trimOffset,
          trackIndex: targetTrack,
          color: '#10b981',
          mediaItemId: mediaItemId,
          sourceAssetId: sourceAssetId,
          isDurationPlaceholder: isPlaceholder || undefined,
          volume:
            clip.volume !== undefined && clip.volume !== null
              ? clip.volume
              : 1.0,
          speed:
            clip.speed !== undefined && clip.speed !== null ? clip.speed : 1.0,
        });
      });
    }

    console.log('Setting timelineClips to:', newClips);
    this.timelineState.timelineClips.set(newClips);
    this.refreshTimelineLayout();

    assetsToExtract.forEach(asset => {
      if (asset.type === 'video') {
        this.extractVideoMetadataFromUrl(asset);
      } else {
        this.extractAudioMetadataFromUrl(asset);
      }
    });
  }

  getAssetThumbnail(id: string): string | undefined {
    return this.timelineState.assets().find(a => a.id === id)?.thumbnail;
  }

  getAssetName(id: string): string {
    return this.timelineState.assets().find(a => a.id === id)?.name || 'Clip';
  }

  isAssetVideo(id: string): boolean {
    return this.timelineState.assets().find(a => a.id === id)?.type === 'video';
  }

  // --- Logic: Timeline ---

  addToTimeline(asset: MediaAsset) {
    const clipsToAdd: TimelineClip[] = [];
    const assetColor = this.getRandomColor();

    if (asset.type === 'video') {
      // Magnetic Video: Always add to the end of the video track
      const vClips = this.timelineState
        .timelineClips()
        .filter(c => c.trackIndex === 0);
      const vStartTime =
        vClips.length > 0
          ? Math.max(...vClips.map(c => c.startTime + c.duration))
          : 0;

      clipsToAdd.push({
        id: Math.random().toString(36).substr(2, 9),
        assetId: asset.id,
        startTime: vStartTime,
        duration: asset.duration,
        offset: 0,
        trackIndex: 0,
        color: assetColor,
        mediaItemId: asset.mediaItemId,
        sourceAssetId: asset.sourceAssetId,
      });

      // Add Audio for Video (Synced at same start time)
      const targetTrack = this.findAvailableAudioTrack(
        vStartTime,
        asset.duration,
      );
      clipsToAdd.push({
        id: Math.random().toString(36).substr(2, 9),
        assetId: asset.id,
        startTime: vStartTime,
        duration: asset.duration,
        offset: 0,
        trackIndex: targetTrack,
        color: '#10b981',
        mediaItemId: asset.mediaItemId,
        sourceAssetId: asset.sourceAssetId,
      });
    } else {
      // Smart Audio: Add at playhead, find first available track
      const playhead = this.timelineState.currentTime();
      const targetTrack = this.findAvailableAudioTrack(
        playhead,
        asset.duration,
      );

      clipsToAdd.push({
        id: Math.random().toString(36).substr(2, 9),
        assetId: asset.id,
        startTime: playhead,
        duration: asset.duration,
        offset: 0,
        trackIndex: targetTrack,
        color: '#10b981',
        mediaItemId: asset.mediaItemId,
        sourceAssetId: asset.sourceAssetId,
      });
    }

    this.timelineState.timelineClips.update(prev => [...prev, ...clipsToAdd]);
    this.refreshTimelineLayout();
    this.triggerAutoSave();
  }

  deleteAsset(asset: MediaAsset, event: Event) {
    event.stopPropagation();

    // Remove from assets list
    this.timelineState.assets.update(prev =>
      prev.filter(a => a.id !== asset.id),
    );

    // Remove any clips associated with this asset from the timeline
    this.timelineState.timelineClips.update(prev =>
      prev.filter(c => c.assetId !== asset.id),
    );

    // Clear selection if it was a clip of this asset
    const selectedId = this.timelineState.selectedClipId();
    if (selectedId) {
      const stillExists = this.timelineState
        .timelineClips()
        .some(c => c.id === selectedId);
      if (!stillExists) {
        this.timelineState.selectedClipId.set(null);
      }
    }

    this.refreshTimelineLayout();
    this.triggerAutoSave();
  }

  private findAvailableAudioTrack(startTime: number, duration: number): number {
    const allAudioClips = this.timelineState
      .timelineClips()
      .filter(c => c.trackIndex > 0);
    return this.findNextAvailableTrackForClip(
      startTime,
      duration,
      allAudioClips,
    );
  }

  // Start dragging a clip horizontally on the timeline
  startDrag(event: MouseEvent, clip: TimelineClip) {
    if (this.isTrackLocked(clip.trackIndex)) return;
    event.stopPropagation();
    event.preventDefault();
    this.selectClip(clip.id, event);
    this.dragState = {
      active: true,
      clipId: clip.id,
      startX: event.clientX,
      initialStartTime: clip.startTime,
    };
    this.timelineState.isPlaying.set(false);
  }

  selectClip(id: string, event: MouseEvent) {
    event.stopPropagation();
    const clip = this.timelineState.timelineClips().find(c => c.id === id);
    if (clip && this.isTrackLocked(clip.trackIndex)) return;
    this.timelineState.selectedClipId.set(id);
  }

  deleteSelectedClip() {
    const id = this.timelineState.selectedClipId();
    if (!id) return;
    this.timelineState.timelineClips.update(prev =>
      prev.filter(c => c.id !== id),
    );
    this.timelineState.selectedClipId.set(null);
    this.refreshTimelineLayout();
    this.triggerAutoSave();
  }

  // --- Split Logic ---
  canSplit(): boolean {
    const id = this.timelineState.selectedClipId();
    if (!id) return false;
    const clip = this.timelineState.timelineClips().find(c => c.id === id);
    if (!clip) return false;
    const time = this.timelineState.currentTime();
    return (
      time > clip.startTime + 0.1 && time < clip.startTime + clip.duration - 0.1
    );
  }

  splitSelectedClip(): void {
    if (!this.canSplit()) return;
    const id = this.timelineState.selectedClipId();
    const clip = this.timelineState.timelineClips().find(c => c.id === id)!;
    const splitPoint = this.timelineState.currentTime() - clip.startTime;

    const clip1Duration = splitPoint;
    const clip2Duration = clip.duration - splitPoint;
    const clip2Offset = clip.offset + splitPoint;

    const clip2: TimelineClip = {
      ...clip,
      id: Math.random().toString(36).substr(2, 9),
      duration: clip2Duration,
      offset: clip2Offset,
      startTime: clip.startTime + splitPoint,
    };

    this.timelineState.timelineClips.update(prev => {
      const updated = prev.map(c =>
        c.id === id ? {...c, duration: clip1Duration} : c,
      );
      return [...updated, clip2];
    });

    this.timelineState.selectedClipId.set(clip2.id);
    this.refreshTimelineLayout();
    this.triggerAutoSave();
  }

  togglePlay() {
    if (!this.isBrowser) return;

    if (this.timelineState.isPlaying()) {
      // Pausing
      const lastScroll = this.timelineState.scrollOffset();
      this.timelineState.isPlaying.set(false);
      this.playbackService.stopLoop();

      if (this.dummyScrollContainer?.nativeElement) {
        this.dummyScrollContainer.nativeElement.scrollLeft = lastScroll;
      }
    } else {
      // Playing
      if (
        this.activeToolButton() === 'agent' &&
        this.timelineState.timelineClips().length > 0
      ) {
        this.activeToolButton.set(null);
      }
      this.timelineState.isPlaying.set(true);
      this.playbackService.runGameLoop();
    }
  }

  onVideoEnded() {}
  onMetadataLoaded() {}

  // --- Download / Render ---
  downloadVideo() {
    const storyboard = this.agentChatService.currentStoryboard();
    if (!storyboard || !storyboard.timeline_id || this.isDownloading()) {
      console.warn('Cannot download: missing storyboard or timeline ID');
      return;
    }

    const runRender = () => {
      this.isDownloading.set(true);

      const request: RenderTimelineRequest = {
        timeline_id: storyboard.timeline_id,
      };

      this.workbenchService.renderVideo(request).subscribe({
        next: (res: MediaItem) => {
          // Poll for completion
          const pollInterval = 2000;
          this.lastSavedText.set('Rendering video...');

          interval(pollInterval)
            .pipe(
              switchMap(() => this.galleryService.getMedia(res.id as number)),
              catchError(err => {
                console.error('Error polling rendered media', err);
                return throwError(() => err);
              }),
              takeWhile(item => {
                const status = item.status?.toUpperCase();
                if (status === 'FAILED') {
                  this.isDownloading.set(false);
                  this.lastSavedText.set('Render failed');
                  return false;
                }
                if (status === 'COMPLETED') {
                  return false;
                }
                return true;
              }, true), // inclusive to emit the last item
            )
            .subscribe({
              next: item => {
                if (item.status?.toUpperCase() === 'COMPLETED') {
                  this.isDownloading.set(false);
                  this.lastSavedText.set('Render complete');

                  if (item.presignedUrls && item.presignedUrls.length > 0) {
                    const url = item.presignedUrls[0];
                    this.http.get(url, {responseType: 'blob'}).subscribe({
                      next: blob => {
                        const localUrl = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = localUrl;
                        a.download = `creative-studio-export-${new Date().getTime()}.mp4`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        window.URL.revokeObjectURL(localUrl);
                      },
                      error: err => {
                        console.error(
                          'Failed to download video file blob',
                          err,
                        );
                        // Fallback: Open the presigned URL directly in a new tab if blob download fails (e.g., due to CORS)
                        window.open(url, '_blank');
                      },
                    });
                  }
                }
              },
              error: err => {
                console.error('Polling failed', err);
                this.isDownloading.set(false);
                this.lastSavedText.set('Render failed');
              },
            });
        },
        error: err => {
          console.error('Render request failed', err);
          this.isDownloading.set(false);
          this.lastSavedText.set('Render failed');
        },
      });
    };

    if (this.hasPendingSave) {
      this.saveTimeline().subscribe({
        next: () => {
          runRender();
        },
        error: err => {
          console.error('Save failed before download, aborting render', err);
        },
      });
    } else {
      runRender();
    }
  }

  // Scrubbing State
  scrubState: {active: boolean; startX: number; initialTime: number} | null =
    null;

  onScrubStart(event: MouseEvent) {
    event.preventDefault();
    event.stopPropagation(); // Stop bubbling to container

    this.scrubState = {
      active: true,
      startX: event.clientX,
      initialTime: this.timelineState.currentTime(),
    };
    this.timelineState.isPlaying.set(false);

    // Center the view on the playhead
    if (this.timelineContainer?.nativeElement) {
      const containerWidth = this.timelineContainer.nativeElement.clientWidth;
      const playheadPos =
        this.timelineState.currentTime() * this.timelineState.pixelsPerSecond();
      const newScrollLeft = Math.max(0, playheadPos - containerWidth * 0.5);
      this.timelineState.scrollOffset.set(newScrollLeft);
      if (this.dummyScrollContainer?.nativeElement) {
        this.dummyScrollContainer.nativeElement.scrollLeft = newScrollLeft;
      }
    }
  }

  onScrubMove(event: MouseEvent) {
    if (!this.scrubState?.active) return;

    const deltaX = event.clientX - this.scrubState.startX;
    const deltaTime = deltaX / this.timelineState.pixelsPerSecond();
    const newTime = Math.max(
      0,
      Math.min(
        this.scrubState.initialTime + deltaTime,
        this.timelineState.totalDuration(),
      ),
    );

    this.timelineState.currentTime.set(newTime);

    // Auto-scroll logic for scrubbing
    if (this.timelineContainer?.nativeElement) {
      const container = this.timelineContainer.nativeElement;
      const playheadPos = newTime * this.timelineState.pixelsPerSecond();
      const containerWidth = container.clientWidth;
      const scrollLeft = this.timelineState.scrollOffset();

      // Scroll forward if playhead goes off screen right
      if (playheadPos > scrollLeft + containerWidth) {
        this.timelineState.scrollOffset.set(playheadPos - containerWidth);
      }
      // Scroll backward if playhead goes off screen left
      else if (playheadPos < scrollLeft) {
        this.timelineState.scrollOffset.set(playheadPos);
      }
    }
  }

  onScrubEnd() {
    this.scrubState = null;
  }

  onTimelineMouseDown(event: MouseEvent) {
    if (this.dragState?.active) return;

    // If clicking on ruler/timeline bg, start scrubbing
    // Use offsetX if the target is the container itself for better accuracy
    // Otherwise fallback to clientX calculation
    let clickX = 0;
    const target = event.target as HTMLElement;
    const currentTarget = event.currentTarget as HTMLElement;

    if (target === currentTarget) {
      clickX = event.offsetX + currentTarget.scrollLeft;
    } else {
      const rect = currentTarget.getBoundingClientRect();
      clickX = event.clientX - rect.left + currentTarget.scrollLeft;
    }

    const time = Math.max(0, clickX / this.timelineState.pixelsPerSecond());
    this.timelineState.currentTime.set(time);

    // Center the view on the clicked time
    if (this.timelineContainer?.nativeElement) {
      const containerWidth = this.timelineContainer.nativeElement.clientWidth;
      const playheadPos = time * this.timelineState.pixelsPerSecond();
      const newScrollLeft = Math.max(0, playheadPos - containerWidth * 0.5);
      this.timelineState.scrollOffset.set(newScrollLeft);
      if (this.dummyScrollContainer?.nativeElement) {
        this.dummyScrollContainer.nativeElement.scrollLeft = newScrollLeft;
      }
    }

    this.onScrubStart(event);
    this.timelineState.selectedClipId.set(null);
  }

  // --- Trimming Logic ---
  startTrim(event: MouseEvent, clip: TimelineClip, type: 'start' | 'end') {
    if (this.isTrackLocked(clip.trackIndex)) return;
    event.stopPropagation();
    event.preventDefault();
    this.trimState = {
      active: true,
      clipId: clip.id,
      type,
      startX: event.clientX,
      initialStart: clip.startTime,
      initialDur: clip.duration,
      initialOffset: clip.offset,
    };
    this.timelineState.isPlaying.set(false);
  }

  onTrimMove(event: MouseEvent) {
    if (!this.trimState || !this.trimState.active) return;

    const deltaX = event.clientX - this.trimState.startX;
    if (Math.abs(deltaX) < 1) return; // Ignore micro-jitters
    this.trimState.hasMoved = true;

    const deltaTime = deltaX / this.timelineState.pixelsPerSecond();
    const {clipId, type, initialDur, initialOffset} = this.trimState;

    const clip = this.timelineState.timelineClips().find(c => c.id === clipId);
    if (!clip) return;
    const asset = this.timelineState.assets().find(a => a.id === clip.assetId);
    const maxDuration = asset ? asset.duration : 9999;

    this.timelineState.timelineClips.update(clips =>
      clips.map(c => {
        if (c.id !== clipId) return c;

        let newDur = c.duration;
        let newOffset = c.offset;

        if (type === 'end') {
          newDur = Math.max(0.5, initialDur + deltaTime);
          if (newOffset + newDur > maxDuration)
            newDur = maxDuration - newOffset;
        } else {
          const change = deltaTime;
          if (change > initialDur - 0.5) {
            newOffset = initialOffset + (initialDur - 0.5);
            newDur = 0.5;
          } else if (initialOffset + change < 0) {
            newOffset = 0;
            newDur = initialDur + initialOffset;
          } else {
            newOffset = initialOffset + change;
            newDur = initialDur - change;
          }
        }

        return {...c, duration: newDur, offset: newOffset};
      }),
    );
  }

  onTrimEnd() {
    if (this.trimState && this.trimState.active) {
      const hasMoved = this.trimState.hasMoved;
      this.refreshTimelineLayout();
      this.trimState = null;
      if (hasMoved) {
        this.triggerAutoSave();
      }
    }
  }

  // --- Drag Move / End Logic ---

  onDragMove(event: MouseEvent) {
    if (!this.dragState || !this.dragState.active) return;

    const deltaX = event.clientX - this.dragState.startX;
    if (Math.abs(deltaX) < 1) return; // Ignore micro-jitters
    this.dragState.hasMoved = true;

    const deltaTime = deltaX / this.timelineState.pixelsPerSecond();
    let newStartTime = this.dragState.initialStartTime + deltaTime;
    if (newStartTime < 0) newStartTime = 0;

    // Snap to start or current playhead for nicer UX
    const snapThreshold = 10 / this.timelineState.pixelsPerSecond();
    if (Math.abs(newStartTime) < snapThreshold) {
      newStartTime = 0;
    } else if (
      Math.abs(newStartTime - this.timelineState.currentTime()) < snapThreshold
    ) {
      newStartTime = this.timelineState.currentTime();
    }

    const clipId = this.dragState.clipId;
    this.timelineState.timelineClips.update(clips =>
      clips.map(c => (c.id === clipId ? {...c, startTime: newStartTime} : c)),
    );
  }

  onDragEnd() {
    if (this.dragState && this.dragState.active) {
      const clipId = this.dragState.clipId;
      const hasMoved = this.dragState.hasMoved;
      this.dragState = null;
      if (hasMoved) {
        this.resolveOverlaps(clipId);
      }
    }
  }

  // Move-aside overlap resolution on the same track
  private resolveOverlaps(movedClipId: string) {
    const allClips = this.timelineState.timelineClips();
    const movedClip = allClips.find(c => c.id === movedClipId);
    if (!movedClip) return;

    if (movedClip.trackIndex === 0) {
      // Video Track: Magnetic / Ripple Edit
      // 1. Sort all video clips by startTime to determine order
      // 2. Remove gaps
      const videoClips = allClips
        .filter(c => c.trackIndex === 0)
        .sort((a, b) => a.startTime - b.startTime);

      let currentTime = 0;
      const newVideoClips = videoClips.map(clip => {
        const newClip = {...clip, startTime: currentTime};
        const transitionType =
          clip.transition_to_next_type || TransitionType.NONE;
        const transitionDuration =
          transitionType !== TransitionType.NONE &&
          clip.transition_to_next_duration !== undefined &&
          clip.transition_to_next_duration !== null
            ? clip.transition_to_next_duration
            : 0;
        currentTime += clip.duration - transitionDuration / 2;
        return newClip;
      });

      // Update state
      this.timelineState.timelineClips.update(prev => {
        const others = prev.filter(c => c.trackIndex !== 0);
        return [...others, ...newVideoClips];
      });
    } else {
      // Audio Track: Gravity
      // Try to place on Track 1, then 2, etc.
      const audioClips = allClips.filter(
        c => c.trackIndex > 0 && c.id !== movedClipId,
      );

      const targetTrack = this.findNextAvailableTrackForClip(
        movedClip.startTime,
        movedClip.duration,
        audioClips,
      );

      // Update the clip with the new track index
      this.timelineState.timelineClips.update(prev =>
        prev.map(c =>
          c.id === movedClipId ? {...c, trackIndex: targetTrack} : c,
        ),
      );
    }
    this.triggerAutoSave();
  }

  // --- Utilities ---
  formatTime(seconds: number): string {
    const fps = 30; // Assuming 30 frames per second
    const totalFrames = Math.floor(seconds * fps);

    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const f = totalFrames % fps;

    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}:${f.toString().padStart(2, '0')}`;
  }

  toggleToolButton(
    buttonName: 'gallery' | 'audio' | 'stories' | 'edit' | 'agent',
  ): void {
    if (this.activeToolButton() === buttonName) {
      this.activeToolButton.set(null);
    } else {
      this.activeToolButton.set(buttonName);
    }
  }

  getRandomColor() {
    return '#3b82f6';
  }

  getRandomHeight(seed: number) {
    // deterministic pseudo random for waveform vis
    return 30 + (Math.sin(seed) * 40 + 30);
  }

  getSequence(length: number): number[] {
    return [...Array(Math.floor(length)).keys()].map(i => i + 1);
  }

  getThumbnailsSequence(duration: number): number[] {
    // add thumbnails dinamically
    const count = Math.ceil(
      (duration * this.timelineState.pixelsPerSecond()) / 80,
    );
    return this.getSequence(count);
  }

  onDummyScroll(event: Event) {
    const target = event.target as HTMLElement;
    this.timelineState.scrollOffset.set(target.scrollLeft);
    this.timeRuler.setScrollLeft(target.scrollLeft);
  }

  triggerAutoSave() {
    this.hasPendingSave = true;
    this.lastSavedText.set('Saving...');
    this.saveSubject.next();
  }

  saveTimeline(): Observable<TimelineDTO | null> {
    this.hasPendingSave = false;
    const sb = this.agentChatService.currentStoryboard();
    if (!sb || !sb.id || !sb.timeline_id) {
      console.warn(
        'Cannot auto-save timeline: missing storyboard, ID, or timeline ID',
      );
      return of(null);
    }

    if (this.activeSaveSubscription) {
      this.activeSaveSubscription.unsubscribe();
    }

    this.lastSavedText.set('Saving...');

    const clips = this.timelineState.timelineClips();
    const videoClips = clips
      .filter(c => c.trackIndex === 0)
      .map(c => {
        const asset = this.timelineState.assets().find(a => a.id === c.assetId);
        let assetRef = null;
        const mediaItemId = c.mediaItemId || asset?.mediaItemId;
        const sourceAssetId = c.sourceAssetId || asset?.sourceAssetId;
        if (mediaItemId) {
          assetRef = {
            id: mediaItemId,
            type: 'media_item' as const,
          };
        } else if (sourceAssetId) {
          assetRef = {
            id: sourceAssetId,
            type: 'source_asset' as const,
          };
        }

        return {
          asset_ref: assetRef,
          trim: {
            offset_seconds: c.offset,
            duration_seconds: c.duration,
          },
          first_frame_asset_ref: c.first_frame_asset_ref || null,
          last_frame_asset_ref: c.last_frame_asset_ref || null,
          placeholder: c.placeholder || null,
          volume: 1.0,
          speed: 1.0,
        };
      });

    const audioClips = clips
      .filter(c => c.trackIndex > 0)
      .map(c => {
        const asset = this.timelineState.assets().find(a => a.id === c.assetId);
        let assetRef = null;
        const mediaItemId = c.mediaItemId || asset?.mediaItemId;
        const sourceAssetId = c.sourceAssetId || asset?.sourceAssetId;
        if (mediaItemId) {
          assetRef = {
            id: mediaItemId,
            type: 'media_item' as const,
          };
        } else if (sourceAssetId) {
          assetRef = {
            id: sourceAssetId,
            type: 'source_asset' as const,
          };
        }

        return {
          start_at: {
            video_clip_index: -1,
            offset_seconds: c.startTime,
          },
          asset_ref: assetRef,
          trim: {
            offset_seconds: c.offset,
            duration_seconds: c.duration,
          },
          volume: 1.0,
        };
      });

    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();

    const timelineUpdate = {
      timeline_id: sb.timeline_id,
      storyboard_id: sb.id,
      workspace_id: workspaceId || 1,
      title: 'Timeline',
      video_clips: videoClips,
      audio_clips: audioClips,
      transitions: this.timelineState.transitions(),
      transition_in: this.timelineState.transitionIn() || undefined,
      transition_out: this.timelineState.transitionOut() || undefined,
    };

    this.isSaving = true;
    const subject = new Subject<TimelineDTO>();
    this.activeSaveSubscription = this.workbenchService
      .updateTimeline(sb.timeline_id, timelineUpdate)
      .subscribe({
        next: (res: TimelineDTO) => {
          console.log('Timeline updated successfully', res);
          this.lastSavedText.set('Saved');
          this.isSaving = false;
          subject.next(res);
          subject.complete();
        },
        error: err => {
          console.error('Error updating timeline', err);
          this.lastSavedText.set('Failed to save changes');
          this.isSaving = false;
          subject.error(err);
        },
      });
    return subject.asObservable();
  }
}
