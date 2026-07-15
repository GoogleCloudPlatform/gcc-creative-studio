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

import {Injectable, signal, computed} from '@angular/core';
import {SafeResourceUrl} from '@angular/platform-browser';
import {AssetRef, Transition} from '../../common/models/workbench.model';

export interface TimelineClip {
  id: string;
  assetId: string;
  startTime: number; // absolute time on timeline
  duration: number; // duration of this specific clip (could be trimmed later)
  offset: number; // offset into the original source file
  trackIndex: number; // 0 for video, 1 for audio
  color: string;
  mediaItemId?: number;
  sourceAssetId?: number;
  first_frame_asset_ref?: AssetRef | null;
  last_frame_asset_ref?: AssetRef | null;
  placeholder?: string | null;
}

export interface MediaAsset {
  id: string;
  name: string;
  type: 'video' | 'audio';
  url: string;
  safeUrl: SafeResourceUrl;
  duration: number;
  thumbnail?: string;
  mediaItemId?: number;
  sourceAssetId?: number;
}

@Injectable({
  providedIn: 'root',
})
export class TimelineStateService {
  // Signals for State
  assets = signal<MediaAsset[]>([]);
  currentTime = signal<number>(0);
  isPlaying = signal<boolean>(false);
  pixelsPerSecond = signal<number>(15);
  scrollOffset = signal<number>(0);
  timelineClips = signal<TimelineClip[]>([]);
  selectedClipId = signal<string | null>(null);
  transitions = signal<Transition[]>([]);
  transitionIn = signal<Transition | null>(null);
  transitionOut = signal<Transition | null>(null);
  loadedTimelineId = signal<number | string | undefined>(undefined);

  // Computed Values
  totalDuration = computed(() => {
    if (this.timelineClips().length === 0) return 0;
    return Math.max(...this.timelineClips().map(c => c.startTime + c.duration));
  });

  videoClips = computed(() =>
    this.timelineClips()
      .filter(c => c.trackIndex === 0)
      .sort((a, b) => a.startTime - b.startTime),
  );

  activeVideoClip = computed(() => {
    const time = this.currentTime();
    return this.videoClips().find(
      c => time >= c.startTime && time < c.startTime + c.duration,
    );
  });

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

  activeAudioClips = computed(() => {
    const time = this.currentTime();
    return this.audioTracks().map(track =>
      track.find(c => time >= c.startTime && time < c.startTime + c.duration),
    );
  });
}
