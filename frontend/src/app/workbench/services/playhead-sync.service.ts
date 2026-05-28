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

import {Injectable, inject, signal, effect} from '@angular/core';
import {TimelineStateService} from './timeline-state.service';
import {TimeRulerComponent} from '../components/time-ruler/time-ruler.component';

@Injectable({
  providedIn: 'root',
})
export class PlayheadSyncService {
  private timelineState = inject(TimelineStateService);

  private elements = signal<{
    video: HTMLVideoElement;
    audios: HTMLAudioElement[];
    timeline: HTMLDivElement;
    dummyScroll: HTMLDivElement;
    timeRuler: TimeRulerComponent;
  } | null>(null);

  private animationFrameId: any;

  constructor() {
    effect(() => {
      const els = this.elements();
      if (!els) return;

      const vid = els.video;
      const vClip = this.timelineState.activeVideoClip();
      const curTime = this.timelineState.currentTime();

      // Video Sync
      if (vid && vClip) {
        const fileTime = curTime - vClip.startTime + vClip.offset;
        if (Math.abs(vid.currentTime - fileTime) > 0.5)
          vid.currentTime = fileTime;
        if (this.timelineState.isPlaying() && vid.paused)
          vid.play().catch(e => console.error('[VideoSync] Play failed', e));
        if (!this.timelineState.isPlaying() && !vid.paused) vid.pause();
      } else if (vid) {
        vid.pause();
      }

      // Audio Sync (Multi-track)
      const audioElements = els.audios;
      const activeAClips = this.timelineState.activeAudioClips();

      if (audioElements) {
        audioElements.forEach((aud, index) => {
          const aClip = activeAClips[index];

          if (aud && aClip) {
            const fileTime = curTime - aClip.startTime + aClip.offset;
            if (Math.abs(aud.currentTime - fileTime) > 0.5) {
              aud.currentTime = fileTime;
            }

            if (this.timelineState.isPlaying() && aud.paused) {
              aud.play().catch(e => console.error('Audio play failed', e));
            }
            if (!this.timelineState.isPlaying() && !aud.paused) {
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

  registerElements(elements: {
    video: HTMLVideoElement;
    audios: HTMLAudioElement[];
    timeline: HTMLDivElement;
    dummyScroll: HTMLDivElement;
    timeRuler: TimeRulerComponent;
  }) {
    this.elements.set(elements);
  }

  runGameLoop() {
    const els = this.elements();
    if (!els) return;

    let lastTime: number | null = null;
    const loop = (now: number) => {
      if (!this.timelineState.isPlaying()) return;

      if (lastTime === null) {
        lastTime = now;
        this.animationFrameId = requestAnimationFrame(loop);
        return;
      }

      const dt = (now - lastTime) / 1000;
      lastTime = now;
      const nextTime = this.timelineState.currentTime() + dt;

      const {timeline, dummyScroll, timeRuler} = els;

      // Auto Scroll Logic
      if (timeline) {
        const playheadPos = nextTime * this.timelineState.pixelsPerSecond();
        const containerWidth = timeline.clientWidth;
        const centerPoint = containerWidth * 0.5;

        if (playheadPos > centerPoint) {
          const newScrollLeft = playheadPos - centerPoint;
          this.timelineState.scrollOffset.set(newScrollLeft);
          if (dummyScroll) {
            dummyScroll.scrollLeft = newScrollLeft;
          }
          timeRuler.setScrollLeft(newScrollLeft);
        }
      }

      if (nextTime >= this.timelineState.totalDuration()) {
        this.timelineState.currentTime.set(0);
        this.timelineState.scrollOffset.set(0);
        if (timeline) {
          timeline.scrollLeft = 0;
        }
        timeRuler.setScrollLeft(0);
        if (dummyScroll) {
          dummyScroll.scrollLeft = 0;
        }
        this.timelineState.isPlaying.set(false);
      } else {
        this.timelineState.currentTime.set(nextTime);
        this.animationFrameId = requestAnimationFrame(loop);
      }
    };
    this.animationFrameId = requestAnimationFrame(loop);
  }

  stopLoop() {
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
    }
  }
}
