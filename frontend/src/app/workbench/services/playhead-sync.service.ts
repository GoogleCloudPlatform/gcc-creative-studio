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
import {TimelineStateService, TimelineClip} from './timeline-state.service';
import {TimeRulerComponent} from '../components/time-ruler/time-ruler.component';

@Injectable({
  providedIn: 'root',
})
export class PlayheadSyncService {
  private timelineState = inject(TimelineStateService);

  private elements = signal<{
    videoA: HTMLVideoElement;
    videoB: HTMLVideoElement;
    audios: HTMLAudioElement[];
    timeline: HTMLDivElement;
    dummyScroll: HTMLDivElement;
    timeRuler: TimeRulerComponent;
  } | null>(null);

  private animationFrameId: number | undefined;
  private activeVideoElement: 'A' | 'B' = 'A';
  private loadedClips = new Map<'A' | 'B', string>(); // map element to clipId

  constructor() {
    // Eagerly preload the first two clips when timeline is loaded
    effect(() => {
      const els = this.elements();
      if (!els) return;

      const clips = this.timelineState.videoClips();
      if (clips.length > 0) {
        const firstClip = clips[0];
        if (this.loadedClips.get('A') !== firstClip.id) {
          this.loadClipInElement('A', firstClip);
        }
        if (clips.length > 1) {
          const secondClip = clips[1];
          if (this.loadedClips.get('B') !== secondClip.id) {
            this.loadClipInElement('B', secondClip);
          }
        }
      }
    });

    effect(() => {
      const els = this.elements();
      if (!els) return;

      const curTime = this.timelineState.currentTime();
      const isPlaying = this.timelineState.isPlaying();

      const currentClip = this.timelineState.activeVideoClip();
      const nextClip = this.getNextVideoClip();

      if (currentClip) {
        // 1. Manage Active Element
        if (this.loadedClips.get('A') === currentClip.id) {
          this.activeVideoElement = 'A';
        } else if (this.loadedClips.get('B') === currentClip.id) {
          this.activeVideoElement = 'B';
        } else {
          // Not loaded in either! Load it in the INACTIVE one!
          const inactiveEl = this.activeVideoElement === 'A' ? 'B' : 'A';
          this.loadClipInElement(inactiveEl, currentClip);
          this.activeVideoElement = inactiveEl;
        }

        const activeEl =
          this.activeVideoElement === 'A' ? els.videoA : els.videoB;
        const inactiveEl =
          this.activeVideoElement === 'A' ? els.videoB : els.videoA;

        // 2. Show/Hide Videos (using opacity for smoother transitions)
        if (activeEl) activeEl.style.opacity = '1';
        if (inactiveEl) inactiveEl.style.opacity = '0';

        // 3. Sync and Play Active Video
        if (activeEl) {
          const targetVolume =
            currentClip.volume !== undefined ? currentClip.volume : 1.0;
          const targetSpeed =
            currentClip.speed !== undefined ? currentClip.speed : 1.0;

          const fileTime =
            (curTime - currentClip.startTime) * targetSpeed +
            currentClip.offset;
          if (Math.abs(activeEl.currentTime - fileTime) > 0.5) {
            activeEl.currentTime = fileTime;
          }

          if (activeEl.volume !== targetVolume) {
            activeEl.volume = targetVolume;
          }
          if (activeEl.playbackRate !== targetSpeed) {
            activeEl.playbackRate = targetSpeed;
          }

          if (isPlaying && activeEl.paused) {
            activeEl
              .play()
              .catch(e => console.error('[VideoSync] Play failed', e));
          }
          if (!isPlaying && !activeEl.paused) {
            activeEl.pause();
          }
        }

        // 4. Preload Next Clip in Inactive Element
        if (nextClip) {
          const inactiveKey = this.activeVideoElement === 'A' ? 'B' : 'A';
          if (this.loadedClips.get(inactiveKey) !== nextClip.id) {
            this.loadClipInElement(inactiveKey, nextClip);
          }
        }
      } else {
        // No active clip, hide both
        if (els.videoA) els.videoA.style.opacity = '0';
        if (els.videoB) els.videoB.style.opacity = '0';
      }

      // Audio Sync (Multi-track)
      const audioElements = els.audios;
      const activeAClips = this.timelineState.activeAudioClips();

      if (audioElements) {
        audioElements.forEach((aud, index) => {
          const aClip = activeAClips[index];

          if (aud && aClip) {
            const targetVolume =
              aClip.volume !== undefined ? aClip.volume : 1.0;
            const targetSpeed = aClip.speed !== undefined ? aClip.speed : 1.0;

            const fileTime =
              (curTime - aClip.startTime) * targetSpeed + aClip.offset;
            if (Math.abs(aud.currentTime - fileTime) > 0.5) {
              aud.currentTime = fileTime;
            }

            if (aud.volume !== targetVolume) {
              aud.volume = targetVolume;
            }
            if (aud.playbackRate !== targetSpeed) {
              aud.playbackRate = targetSpeed;
            }

            if (isPlaying && aud.paused) {
              aud.play().catch(e => console.error('Audio play failed', e));
            }
            if (!isPlaying && !aud.paused) {
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

  private getNextVideoClip(): TimelineClip | undefined {
    const currentClip = this.timelineState.activeVideoClip();
    const clips = this.timelineState.videoClips();

    if (!currentClip) {
      return clips[0]; // Preload first clip if none active
    }

    const index = clips.findIndex(c => c.id === currentClip.id);
    return clips[index + 1];
  }

  private loadClipInElement(el: 'A' | 'B', clip: TimelineClip) {
    const els = this.elements();
    if (!els) return;

    const videoEl = el === 'A' ? els.videoA : els.videoB;
    if (!videoEl) return;

    const asset = this.timelineState.assets().find(a => a.id === clip.assetId);
    if (asset) {
      videoEl.src = asset.url;
      videoEl.load(); // Force browser to start loading!
    }
    this.loadedClips.set(el, clip.id);
  }

  registerElements(elements: {
    videoA: HTMLVideoElement;
    videoB: HTMLVideoElement;
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
