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

import {TestBed} from '@angular/core/testing';
import {TimelineStateService} from './timeline-state.service';
import {TimelineClip} from '../../common/models/workbench.model';

describe('TimelineStateService', () => {
  let service: TimelineStateService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(TimelineStateService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should have default state', () => {
    expect(service.currentTime()).toBe(0);
    expect(service.isPlaying()).toBe(false);
    expect(service.pixelsPerSecond()).toBe(15);
    expect(service.scrollOffset()).toBe(0);
    expect(service.timelineClips()).toEqual([]);
    expect(service.selectedClipId()).toBeNull();
  });

  it('should calculate totalDuration correctly', () => {
    const clips: TimelineClip[] = [
      {
        id: '1',
        assetId: 'a1',
        startTime: 0,
        duration: 10,
        offset: 0,
        trackIndex: 0,
        color: 'red',
      },
      {
        id: '2',
        assetId: 'a2',
        startTime: 5,
        duration: 15,
        offset: 0,
        trackIndex: 1,
        color: 'blue',
      },
    ];
    service.timelineClips.set(clips);
    expect(service.totalDuration()).toBe(20); //  5+15
  });

  it('should filter and sort videoClips correctly', () => {
    const clips: TimelineClip[] = [
      {
        id: '1',
        assetId: 'a1',
        startTime: 10,
        duration: 10,
        offset: 0,
        trackIndex: 0,
        color: 'red',
      },
      {
        id: '2',
        assetId: 'a2',
        startTime: 0,
        duration: 5,
        offset: 0,
        trackIndex: 0,
        color: 'blue',
      },
      {
        id: '3',
        assetId: 'a3',
        startTime: 5,
        duration: 5,
        offset: 0,
        trackIndex: 1,
        color: 'green',
      }, // Audio
    ];
    service.timelineClips.set(clips);
    const vClips = service.videoClips();
    expect(vClips.length).toBe(2);
    expect(vClips[0].id).toBe('2'); // Sorted by startTime
    expect(vClips[1].id).toBe('1');
  });

  it('should find activeVideoClip correctly', () => {
    const clips: TimelineClip[] = [
      {
        id: '1',
        assetId: 'a1',
        startTime: 0,
        duration: 10,
        offset: 0,
        trackIndex: 0,
        color: 'red',
      },
      {
        id: '2',
        assetId: 'a2',
        startTime: 10,
        duration: 10,
        offset: 0,
        trackIndex: 0,
        color: 'blue',
      },
    ];
    service.timelineClips.set(clips);

    service.currentTime.set(5);
    expect(service.activeVideoClip()?.id).toBe('1');

    service.currentTime.set(15);
    expect(service.activeVideoClip()?.id).toBe('2');

    service.currentTime.set(25);
    expect(service.activeVideoClip()).toBeUndefined();
  });

  it('should group audioTracks correctly', () => {
    const clips: TimelineClip[] = [
      {
        id: '1',
        assetId: 'a1',
        startTime: 0,
        duration: 10,
        offset: 0,
        trackIndex: 1,
        color: 'red',
      },
      {
        id: '2',
        assetId: 'a2',
        startTime: 5,
        duration: 10,
        offset: 0,
        trackIndex: 2,
        color: 'blue',
      },
      {
        id: '3',
        assetId: 'a3',
        startTime: 10,
        duration: 10,
        offset: 0,
        trackIndex: 1,
        color: 'green',
      },
    ];
    service.timelineClips.set(clips);
    const tracks = service.audioTracks();
    expect(tracks.length).toBe(2); // Track 1 and Track 2
    expect(tracks[0].length).toBe(2); // 2 clips in track 1
    expect(tracks[1].length).toBe(1); // 1 clip in track 2
  });

  it('should find activeAudioClips correctly', () => {
    const clips: TimelineClip[] = [
      {
        id: '1',
        assetId: 'a1',
        startTime: 0,
        duration: 10,
        offset: 0,
        trackIndex: 1,
        color: 'red',
      },
      {
        id: '2',
        assetId: 'a2',
        startTime: 5,
        duration: 10,
        offset: 0,
        trackIndex: 2,
        color: 'blue',
      },
      {
        id: '3',
        assetId: 'a3',
        startTime: 10,
        duration: 10,
        offset: 0,
        trackIndex: 1,
        color: 'green',
      },
    ];
    service.timelineClips.set(clips);

    service.currentTime.set(2);
    let activeClips = service.activeAudioClips();
    expect(activeClips.length).toBe(2);
    expect(activeClips[0]?.id).toBe('1'); // Active only track 1
    expect(activeClips[1]).toBeUndefined();

    service.currentTime.set(7);
    activeClips = service.activeAudioClips();
    expect(activeClips[0]?.id).toBe('1'); // Active on track 1
    expect(activeClips[1]?.id).toBe('2'); // Active on track 2

    service.currentTime.set(12);
    activeClips = service.activeAudioClips();
    expect(activeClips[0]?.id).toBe('3'); // Active on track 1
    expect(activeClips[1]?.id).toBe('2'); // Active on track 2
  });
});
