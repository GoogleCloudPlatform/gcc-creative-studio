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
  effect,
  inject,
  OnInit,
  Inject,
  PLATFORM_ID
} from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import {MatIconRegistry } from '@angular/material/icon';
import { MatSliderModule } from '@angular/material/slider';
import { DomSanitizer, SafeResourceUrl, SafeUrl } from '@angular/platform-browser';
import { MatDialog } from '@angular/material/dialog';
import { ImageSelectorComponent, MediaItemSelection } from '../common/components/image-selector/image-selector.component';
import { SourceAssetResponseDto } from '../common/services/source-asset.service';
import { MediaItem } from '../common/models/media-item.model';
// --- Interfaces ---
interface MediaAsset {
  id: string;
  name: string;
  type: 'video' | 'audio';
  url: string;
  safeUrl: SafeUrl;
  duration: number; // in seconds
  thumbnail?: string;
}

interface TimelineClip {
  id: string;
  assetId: string;
  startTime: number; // absolute time on timeline
  duration: number; // duration of this specific clip (could be trimmed later)
  offset: number; // offset into the original source file
  trackIndex: number; // 0 for video, 1 for audio
  color: string;
}

@Component({
  selector: 'app-workbench',
  templateUrl: './workbench.component.html',
  styleUrls: ['./workbench.component.scss'],
})
export class WorkbenchComponent implements OnInit, OnDestroy {
  // Signals for State
  assets = signal<MediaAsset[]>([]);
  timelineClips = signal<TimelineClip[]>([]);
  currentTime = signal<number>(0);
  isPlaying = signal<boolean>(false);
  selectedClipId = signal<string | null>(null);
  activeToolButton = signal<'gallery' | 'audio' | 'stories' | 'edit' | 'agent' | null>(null);

  // Simple tab between video/audio assets (UX only)
  activeTab = signal<'video' | 'audio'>('video');

  // Visual Settings (Lighting & Zoom)
  exposureVal = 100;
  contrastVal = 100;
  saturateVal = 100;
  pixelsPerSecond = 15; // Default reduced from 30 to 15

  // Computed Values
  videoClips = computed(() => this.timelineClips().filter(c => c.trackIndex === 0).sort((a, b) => a.startTime - b.startTime));
  
  // Group audio clips by track index
  audioTracks = computed(() => {
    const clips = this.timelineClips().filter(c => c.trackIndex > 0);
    if (clips.length === 0) return [[]]; // Always return at least one empty track
    const maxTrack = Math.max(...clips.map(c => c.trackIndex), 1);
    const tracks: TimelineClip[][] = [];
    for (let i = 1; i <= maxTrack; i++) {
        tracks.push(clips.filter(c => c.trackIndex === i));
    }
    return tracks;
  });

  // Filtered assets list based on active tab
  filteredAssets = computed(() => {
    const tab = this.activeTab();
    return this.assets().filter(a => a.type === tab);
  });
  
  videoTrackEnd = computed(() => {
      const clips = this.videoClips();
      return clips.length > 0 ? Math.max(...clips.map(c => c.startTime + c.duration)) : 0;
  });

  totalDuration = computed(() => {
    if (this.timelineClips().length === 0) return 0;
    return Math.max(...this.timelineClips().map(c => c.startTime + c.duration));
  });

  timelineWidth = computed(() => {
    // Ensure timeline is at least screen width or longer based on content
    return Math.max(this.totalDuration() * this.pixelsPerSecond + 800,800); 
  });

  // derived signals for active source logic
  activeVideoClip = computed(() => {
    const time = this.currentTime();
    return this.videoClips().find(c => time >= c.startTime && time < c.startTime + c.duration);
  });

  activeAudioClips = computed(() => {
    const time = this.currentTime();
    return this.audioTracks().map(track => track.find(c => time >= c.startTime && time < c.startTime + c.duration));
  });

  activeVideoSrc = computed(() => {
    const clip = this.activeVideoClip();
    if (!clip) return '';
    const asset = this.assets().find(a => a.id === clip.assetId);
    return asset ? asset.safeUrl : '';
  });

  activeAudioSrcs = computed(() => {
    return this.activeAudioClips().map(clip => {
        if (!clip) return '';
        const asset = this.assets().find(a => a.id === clip.assetId);
        return asset ? asset.safeUrl : '';
    });
  });

  videoFilter = computed(() => {
      return `brightness(${this.exposureVal}%) contrast(${this.contrastVal}%) saturate(${this.saturateVal}%)`;
  });

  animationFrameId: any;
  
  // View Children
  @ViewChild('mainVideo') mainVideo!: ElementRef<HTMLVideoElement>;
  @ViewChildren('bgAudio') bgAudios!: QueryList<ElementRef<HTMLAudioElement>>;
  @ViewChild('timelineContainer') timelineContainer!: ElementRef<HTMLDivElement>;

  // Services
  private sanitizer = inject(DomSanitizer);

  // Trimming state (for clip in/out adjustments)
  trimState: {
    active: boolean;
    clipId: string;
    type: 'start' | 'end';
    startX: number;
    initialStart: number;
    initialDur: number;
    initialOffset: number;
  } | null = null;

  // Drag state for moving clips along the timeline
  dragState: { active: boolean; clipId: string; startX: number; initialStartTime: number } | null = null;

  isBrowser: boolean;

  constructor(
    public matIconRegistry: MatIconRegistry,
    private dialog: MatDialog,
    @Inject(PLATFORM_ID) platformId: Object
  ) {
    this.isBrowser = isPlatformBrowser(platformId);
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
      .addSvgIcon(
        'upload-icon',
        this.setPath(`${this.path}/upload-icon.svg`),
      )
      .addSvgIcon(
        'sound-sensing-icon',
        this.setPath(`${this.path}/sound-sensing-icon.svg`),
      )
      .addSvgIcon(
        'lock-icon',
        this.setPath(`${this.path}/lock-icon.svg`),
      )
      .addSvgIcon(
        'img-icon',
        this.setPath(`${this.path}/img-icon.svg`),
      )
      .addSvgIcon(
        'eye-icon',
        this.setPath(`${this.path}/eye-icon.svg`),
      )
      .addSvgIcon(
        'drive-icon',
        this.setPath(`${this.path}/drive-icon.svg`),
      )
      .addSvgIcon(
        'audio-magic-eraser-icon',
        this.setPath(`${this.path}/audio_magic_eraser-icon.svg`),
      )
      .addSvgIcon(
        'play-arrow-icon',
        this.setPath(`${this.path}/play-arrow-icon.svg`),
      )
      .addSvgIcon(
        'square-icon',
        this.setPath(`${this.path}/square.svg`),     
      )
      .addSvgIcon(
        'phone-icon',
        this.setPath(`${this.path}/pixel-9.svg`),     
      )
      .addSvgIcon(
        'lightbulb-icon',
        this.setPath(`${this.path}/lightbulb-tips.svg`),     
      )
      .addSvgIcon(
        'desktop-icon',
        this.setPath(`${this.path}/desktop.svg`),     
      )
      .addSvgIcon(
        'desktop-mac-icon',
        this.setPath(`${this.path}/desktop-mac.svg`),     
      )
      .addSvgIcon(
        'edit-icon',
        this.setPath(`${this.path}/edit.svg`),     
      )
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

    // Setup an effect to handle video seeking/sync when active clip changes or time jumps
    effect(() => {
      const vid = this.mainVideo?.nativeElement;
      const vClip = this.activeVideoClip();
      const curTime = this.currentTime();

      // Video Sync
      if (vid && vClip) {
        const fileTime = (curTime - vClip.startTime) + vClip.offset;
        if (Math.abs(vid.currentTime - fileTime) > 0.5) vid.currentTime = fileTime;
        if (this.isPlaying() && vid.paused) vid.play().catch(e => console.error('[VideoSync] Play failed', e));
        if (!this.isPlaying() && !vid.paused) vid.pause();
      } else if (vid) {
        vid.pause();
      }

      // Audio Sync (Multi-track)
      const _ = this.audioElementsChanged(); // Dependency
      const audioElements = this.bgAudios?.toArray();
      const activeAClips = this.activeAudioClips();
      
      if (audioElements) {
        audioElements.forEach((audioRef, index) => {
            const aud = audioRef.nativeElement;
            const aClip = activeAClips[index];
            
            if (aud && aClip) {
                const fileTime = (curTime - aClip.startTime) + aClip.offset;
                if (Math.abs(aud.currentTime - fileTime) > 0.5) {
                    aud.currentTime = fileTime;
                }
                
                if (this.isPlaying() && aud.paused) {
                    aud.play().catch(e => console.error('Audio play failed', e));
                }
                if (!this.isPlaying() && !aud.paused) {
                    aud.pause();
                }
            } else if (aud) {
                if (!aud.paused) {
                    aud.pause();
                }
            }
        });
      }
    });
  }

  private path = '../../../assets/images';

  private setPath(url: string): SafeResourceUrl {
      return this.sanitizer.bypassSecurityTrustResourceUrl(url);
    }

  // Signal to track audio element changes
  audioElementsChanged = signal<number>(0);

  ngOnInit() {}
  
  ngAfterViewInit() {
    this.bgAudios.changes.subscribe(() => {
        this.audioElementsChanged.update(v => v + 1);
    });
  }
  
  ngOnDestroy() {
    if (this.animationFrameId) cancelAnimationFrame(this.animationFrameId);
  }

  // --- Logic: File Handling ---

  onFileSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    if (!input.files) return;

    Array.from(input.files).forEach(file => {
      const isVideo = file.type.startsWith('video');
      const isAudio = file.type.startsWith('audio');
      if (!isVideo && !isAudio) return;

      const objectUrl = URL.createObjectURL(file);
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

      this.assets.update(prev => [...prev, asset]);

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
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef.afterClosed().subscribe((result: MediaItemSelection | SourceAssetResponseDto) => {
      if (result) {
        this.processCloudMediaResult(result);
      }
    });
  }

  private processCloudMediaResult(result: MediaItemSelection | SourceAssetResponseDto) {
    const isGalleryItem = 'mediaItem' in result;
    
    let url: string;
    let name: string;
    let type: 'video' | 'audio';
    let thumbnail: string | undefined;

    if (isGalleryItem) {
      const selection = result as MediaItemSelection;
      const mediaItem = selection.mediaItem;
      const selectedIndex = selection.selectedIndex || 0;
      url = mediaItem.presignedUrls?.[selectedIndex] || '';
      name = mediaItem.prompt || 'Cloud Media';
      // Determine type from mimeType or default to current tab
      type = mediaItem.mimeType?.startsWith('audio') ? 'audio' : 'video';
      // Use presignedThumbnailUrls for videos
      thumbnail = type === 'video' 
        ? (mediaItem.presignedThumbnailUrls?.[selectedIndex] || url) 
        : undefined;
    } else {
      const asset = result as SourceAssetResponseDto;
      url = asset.presignedUrl || '';
      name = asset.originalFilename || 'Source Asset';
      type = asset.mimeType?.startsWith('audio') ? 'audio' : 'video';
      // Use presignedThumbnailUrl for videos, fallback to presignedUrl
      thumbnail = type === 'video' 
        ? (asset.presignedThumbnailUrl || asset.presignedUrl) 
        : undefined;
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
    };

    this.assets.update(prev => [...prev, newAsset]);

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
          this.assets.update(items => items.map(i => i.id === asset.id ? {...i, thumbnail: thumbUrl} : i));
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
    audio.onerror = (e) => {
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
           this.assets.update(items => items.map(i => i.id === asset.id ? {...i, thumbnail: thumbUrl} : i));
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
    this.assets.update(items => items.map(i => i.id === id ? {...i, duration} : i));
    this.timelineClips.update(clips => clips.map(clip => clip.assetId === id ? { ...clip, duration } : clip));
    this.refreshTimelineLayout();
  }

  onThumbnailError(asset: MediaAsset) {
    // Clear the thumbnail if it fails to load, so the placeholder icon shows
    this.assets.update(items => items.map(i => i.id === asset.id ? {...i, thumbnail: undefined} : i));
  }

  refreshTimelineLayout() {
      this.timelineClips.update(clips => {
          const vClips = clips.filter(c => c.trackIndex === 0);
          const otherClips = clips.filter(c => c.trackIndex !== 0);

          const layoutTrack = (trackClips: TimelineClip[]) => {
            let currentTime = 0;
            return trackClips.map(clip => {
                const newClip = { ...clip, startTime: currentTime };
                currentTime += clip.duration;
                return newClip;
            });
          };

          return [...layoutTrack(vClips), ...otherClips];
      });
  }

  getAssetThumbnail(id: string): string | undefined {
      return this.assets().find(a => a.id === id)?.thumbnail;
  }

  getAssetName(id: string): string {
      return this.assets().find(a => a.id === id)?.name || 'Clip';
  }

  isAssetVideo(id: string): boolean {
     return this.assets().find(a => a.id === id)?.type === 'video';
  }

  // --- Logic: Timeline ---

  addToTimeline(asset: MediaAsset) {
    const clipsToAdd: TimelineClip[] = [];
    const assetColor = this.getRandomColor();

    if (asset.type === 'video') {
      // Magnetic Video: Always add to the end of the video track
      const vClips = this.timelineClips().filter(c => c.trackIndex === 0);
      const vStartTime = vClips.length > 0 ? Math.max(...vClips.map(c => c.startTime + c.duration)) : 0;
      
      clipsToAdd.push({
        id: Math.random().toString(36).substr(2, 9),
        assetId: asset.id,
        startTime: vStartTime,
        duration: asset.duration,
        offset: 0,
        trackIndex: 0,
        color: assetColor
      });

      // Add Audio for Video (Synced at same start time)
      const targetTrack = this.findAvailableAudioTrack(vStartTime, asset.duration);
      clipsToAdd.push({
          id: Math.random().toString(36).substr(2, 9),
          assetId: asset.id,
          startTime: vStartTime,
          duration: asset.duration,
          offset: 0,
          trackIndex: targetTrack,
          color: '#10b981' 
      });

    } else {
      // Smart Audio: Add at playhead, find first available track
      const playhead = this.currentTime();
      const targetTrack = this.findAvailableAudioTrack(playhead, asset.duration);

      clipsToAdd.push({
          id: Math.random().toString(36).substr(2, 9),
          assetId: asset.id,
          startTime: playhead,
          duration: asset.duration,
          offset: 0,
          trackIndex: targetTrack,
          color: '#10b981' 
      });
    }

    this.timelineClips.update(prev => [...prev, ...clipsToAdd]);
    this.refreshTimelineLayout();
  }

  deleteAsset(asset: MediaAsset, event: Event) {
    event.stopPropagation();
    
    // Remove from assets list
    this.assets.update(prev => prev.filter(a => a.id !== asset.id));
    
    // Remove any clips associated with this asset from the timeline
    this.timelineClips.update(prev => prev.filter(c => c.assetId !== asset.id));
    
    // Clear selection if it was a clip of this asset
    const selectedId = this.selectedClipId();
    if (selectedId) {
        const stillExists = this.timelineClips().some(c => c.id === selectedId);
        if (!stillExists) {
            this.selectedClipId.set(null);
        }
    }
    
    this.refreshTimelineLayout();
  }

  private findAvailableAudioTrack(startTime: number, duration: number): number {
      const allAudioClips = this.timelineClips().filter(c => c.trackIndex > 0);
      let targetTrack = 1;
      let placed = false;
      
      while (!placed) {
        const trackClips = allAudioClips.filter(c => c.trackIndex === targetTrack);
        const hasOverlap = trackClips.some(c => {
           const cEnd = c.startTime + c.duration;
           const newEnd = startTime + duration;
           return (startTime < cEnd && newEnd > c.startTime);
        });
        
        if (!hasOverlap) {
            placed = true;
        } else {
            targetTrack++;
        }
      }
      return targetTrack;
  }



  // Start dragging a clip horizontally on the timeline
  startDrag(event: MouseEvent, clip: TimelineClip) {
    event.stopPropagation();
    event.preventDefault();
    this.selectClip(clip.id, event);
    this.dragState = {
      active: true,
      clipId: clip.id,
      startX: event.clientX,
      initialStartTime: clip.startTime
    };
    this.isPlaying.set(false);
  }

  selectClip(id: string, event: MouseEvent) {
    event.stopPropagation();
    this.selectedClipId.set(id);
  }

  deleteSelectedClip() {
    const id = this.selectedClipId();
    if (!id) return;
    this.timelineClips.update(prev => prev.filter(c => c.id !== id));
    this.selectedClipId.set(null);
    this.refreshTimelineLayout();
  }

  // --- Split Logic ---
  canSplit(): boolean {
    const id = this.selectedClipId();
    if (!id) return false;
    const clip = this.timelineClips().find(c => c.id === id);
    if (!clip) return false;
    const time = this.currentTime();
    return time > clip.startTime + 0.1 && time < clip.startTime + clip.duration - 0.1;
  }

  splitSelectedClip(): void {
    if (!this.canSplit()) return;
    const id = this.selectedClipId();
    const clip = this.timelineClips().find(c => c.id === id)!;
    const splitPoint = this.currentTime() - clip.startTime;

    const clip1Duration = splitPoint;
    const clip2Duration = clip.duration - splitPoint;
    const clip2Offset = clip.offset + splitPoint;

    const clip2: TimelineClip = {
      ...clip,
      id: Math.random().toString(36).substr(2, 9),
      duration: clip2Duration,
      offset: clip2Offset,
      startTime: clip.startTime + splitPoint
    };

    this.timelineClips.update(prev => {
      const updated = prev.map(c => c.id === id ? { ...c, duration: clip1Duration } : c);
      return [...updated, clip2];
    });

    this.selectedClipId.set(clip2.id);
    this.refreshTimelineLayout();
  }

  // --- Logic: Playback Loop ---

  togglePlay() {
    if (!this.isBrowser) return;
    this.isPlaying.set(!this.isPlaying());
    if (this.isPlaying()) {
        this.runGameLoop();
    } else {
        cancelAnimationFrame(this.animationFrameId);
    }
  }

  runGameLoop() {
      if (!this.isBrowser) return;
      let lastTime = performance.now();
      const loop = (now: number) => {
          if (!this.isPlaying()) return;
          const dt = (now - lastTime) / 1000; 
          lastTime = now;
          const nextTime = this.currentTime() + dt;
          
          // 1. Auto Scroll Logic
          if (this.timelineContainer?.nativeElement) {
              const container = this.timelineContainer.nativeElement;
              const playheadPos = nextTime * this.pixelsPerSecond;
              const containerWidth = container.clientWidth;
              const scrollLeft = container.scrollLeft;
              
              // If playhead goes past 80% of visible area, scroll forward
              if (playheadPos > scrollLeft + containerWidth * 0.8) {
                   // Smoothly jump scroll to keep playhead at 20%
                   container.scrollLeft = playheadPos - containerWidth * 0.2;
              }
          }

          if (nextTime >= this.totalDuration()) {
              this.currentTime.set(this.totalDuration());
              this.isPlaying.set(false);
          } else {
              this.currentTime.set(nextTime);
              this.animationFrameId = requestAnimationFrame(loop);
          }
      };
      this.animationFrameId = requestAnimationFrame(loop);
  }
  
  onVideoEnded() {}
  onMetadataLoaded() {}

  // --- Interaction ---
  
  // Scrubbing State
  scrubState: { active: boolean; startX: number; initialTime: number } | null = null;

  onScrubStart(event: MouseEvent) {
      event.preventDefault();
      event.stopPropagation(); // Stop bubbling to container
      
      this.scrubState = {
          active: true,
          startX: event.clientX,
          initialTime: this.currentTime()
      };
      this.isPlaying.set(false);
  }

  onScrubMove(event: MouseEvent) {
      if (!this.scrubState?.active) return;
      
      const deltaX = event.clientX - this.scrubState.startX;
      const deltaTime = deltaX / this.pixelsPerSecond;
      const newTime = Math.max(0, Math.min(this.scrubState.initialTime + deltaTime, this.totalDuration()));
      
      this.currentTime.set(newTime);
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
          clickX = (event.clientX - rect.left) + currentTarget.scrollLeft;
      }

      const time = Math.max(0, clickX / this.pixelsPerSecond);
      this.currentTime.set(time);
      
      this.onScrubStart(event);
      this.selectedClipId.set(null);
  }

    // --- Trimming Logic ---
    startTrim(event: MouseEvent, clip: TimelineClip, type: 'start' | 'end') {
      event.stopPropagation();
      event.preventDefault();
      this.trimState = {
        active: true,
        clipId: clip.id,
        type,
        startX: event.clientX,
        initialStart: clip.startTime,
        initialDur: clip.duration,
        initialOffset: clip.offset
      };
      this.isPlaying.set(false);
    }

    onTrimMove(event: MouseEvent) {
      if (!this.trimState || !this.trimState.active) return;

      const deltaX = event.clientX - this.trimState.startX;
      const deltaTime = deltaX / this.pixelsPerSecond;
      const { clipId, type, initialDur, initialOffset } = this.trimState;

      const clip = this.timelineClips().find(c => c.id === clipId);
      if (!clip) return;
      const asset = this.assets().find(a => a.id === clip.assetId);
      const maxDuration = asset ? asset.duration : 9999;

      this.timelineClips.update(clips => clips.map(c => {
        if (c.id !== clipId) return c;

        let newDur = c.duration;
        let newOffset = c.offset;

        if (type === 'end') {
          newDur = Math.max(0.5, initialDur + deltaTime);
          if (newOffset + newDur > maxDuration) newDur = maxDuration - newOffset;
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

        return { ...c, duration: newDur, offset: newOffset };
      }));
    }

    onTrimEnd() {
      if (this.trimState && this.trimState.active) {
        this.refreshTimelineLayout();
        this.trimState = null;
      }
    }

  // --- Drag Move / End Logic ---

  onDragMove(event: MouseEvent) {
    if (!this.dragState || !this.dragState.active) return;

    const deltaX = event.clientX - this.dragState.startX;
    const deltaTime = deltaX / this.pixelsPerSecond;
    let newStartTime = this.dragState.initialStartTime + deltaTime;
    if (newStartTime < 0) newStartTime = 0;

    // Snap to start or current playhead for nicer UX
    const snapThreshold = 10 / this.pixelsPerSecond;
    if (Math.abs(newStartTime) < snapThreshold) {
      newStartTime = 0;
    } else if (Math.abs(newStartTime - this.currentTime()) < snapThreshold) {
      newStartTime = this.currentTime();
    }

    const clipId = this.dragState.clipId;
    this.timelineClips.update(clips =>
      clips.map(c => (c.id === clipId ? { ...c, startTime: newStartTime } : c))
    );
  }

  onDragEnd() {
    if (this.dragState && this.dragState.active) {
      const clipId = this.dragState.clipId;
      this.dragState = null;
      this.resolveOverlaps(clipId);
    }
  }

  // Move-aside overlap resolution on the same track
  private resolveOverlaps(movedClipId: string) {
    const allClips = this.timelineClips();
    const movedClip = allClips.find(c => c.id === movedClipId);
    if (!movedClip) return;

    if (movedClip.trackIndex === 0) {
        // Video Track: Magnetic / Ripple Edit
        // 1. Sort all video clips by startTime to determine order
        // 2. Remove gaps
        const videoClips = allClips.filter(c => c.trackIndex === 0).sort((a, b) => a.startTime - b.startTime);
        
        let currentTime = 0;
        const newVideoClips = videoClips.map(clip => {
            const newClip = { ...clip, startTime: currentTime };
            currentTime += clip.duration;
            return newClip;
        });
        
        // Update state
        this.timelineClips.update(prev => {
            const others = prev.filter(c => c.trackIndex !== 0);
            return [...others, ...newVideoClips];
        });

    } else {
        // Audio Track: Gravity
        // Try to place on Track 1, then 2, etc.
        const audioClips = allClips.filter(c => c.trackIndex > 0 && c.id !== movedClipId);
        
        let targetTrack = 1;
        let placed = false;
        const duration = movedClip.duration;
        const startTime = movedClip.startTime; // Keep the user's dragged time
        
        while (!placed) {
            const trackClips = audioClips.filter(c => c.trackIndex === targetTrack);
            const hasOverlap = trackClips.some(c => {
               const cEnd = c.startTime + c.duration;
               const newEnd = startTime + duration;
               return (startTime < cEnd && newEnd > c.startTime);
            });
            
            if (!hasOverlap) {
                placed = true;
            } else {
                targetTrack++;
            }
        }
        
        // Update the clip with the new track index
        this.timelineClips.update(prev => prev.map(c => c.id === movedClipId ? { ...c, trackIndex: targetTrack } : c));
    }
  }

  // --- Utilities ---
   formatTimeRuler(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  formatTime(seconds: number): string {
    const fps = 30; // Assuming 30 frames per second
    const totalFrames = Math.floor(seconds * fps);

    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const f = totalFrames % fps;

    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}:${f.toString().padStart(2, '0')}`;
  }

  timeRulerTicks(): number[] {
    const duration = Math.max(this.totalDuration(), 60);
    const ticks = [];
    for(let i=0; i <= duration; i+=2) ticks.push(i);
    return ticks;
  }

  isMajorTick(tick: number): boolean {
    return tick % 10 === 0;
  }

  toggleToolButton(buttonName: 'gallery' | 'audio' | 'stories' | 'edit' | 'agent'): void {
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
      return 40 + (Math.sin(seed) * 30 + 30);
  }

  getSequence(length: number): number[] {
    return [...Array(Math.floor(length)).keys()].map(i => i + 1);
  }
}