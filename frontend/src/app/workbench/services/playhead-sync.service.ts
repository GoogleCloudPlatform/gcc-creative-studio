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
import {
  TransitionType,
  TimelineClip,
} from '../../common/models/workbench.model';

@Injectable({
  providedIn: 'root',
})
export class PlayheadSyncService {
  private timelineState = inject(TimelineStateService);
  isVideoLoading = signal<boolean>(false);

  private elements = signal<{
    videos: HTMLVideoElement[];
    audios: HTMLAudioElement[];
    timeline: HTMLDivElement;
    dummyScroll: HTMLDivElement;
    timeRuler: TimeRulerComponent;
  } | null>(null);

  private animationFrameId: number | undefined;

  constructor() {
    effect(() => {
      const els = this.elements();
      if (!els) return;

      const curTime = this.timelineState.currentTime();
      const isPlaying = this.timelineState.isPlaying();

      const activeTransition = this.getActiveTransition(curTime);
      const clips = this.timelineState.videoClips();

      if (activeTransition) {
        // --- Transition Flow ---
        const outgoingClip = activeTransition.outgoingClip;
        const incomingClip = activeTransition.incomingClip;

        const outgoingIdx = clips.findIndex(c => c.id === outgoingClip.id);
        const incomingIdx = clips.findIndex(c => c.id === incomingClip.id);

        const outgoingEl = outgoingIdx !== -1 ? els.videos[outgoingIdx] : null;
        const incomingEl = incomingIdx !== -1 ? els.videos[incomingIdx] : null;

        // 1. Sync and Play Outgoing Video (plays until endTime and then freezes)
        if (outgoingEl) {
          const speed = outgoingClip.speed || 1.0;
          let fileTime: number;
          let shouldPlay = isPlaying;

          if (curTime <= outgoingClip.startTime + outgoingClip.duration) {
            fileTime =
              (curTime - outgoingClip.startTime) * speed + outgoingClip.offset;
          } else {
            fileTime = outgoingClip.duration * speed + outgoingClip.offset;
            shouldPlay = false;
          }

          if (shouldPlay && Math.abs(outgoingEl.currentTime - fileTime) > 0.5) {
            outgoingEl.currentTime = fileTime;
          }
          const targetVolume =
            outgoingClip.volume !== undefined ? outgoingClip.volume : 1.0;
          if (outgoingEl.volume !== targetVolume) {
            outgoingEl.volume = targetVolume;
          }
          if (outgoingEl.playbackRate !== speed) {
            outgoingEl.playbackRate = speed;
          }

          if (shouldPlay && outgoingEl.paused) {
            outgoingEl
              .play()
              .catch(e => console.error('[VideoSync] Outgoing play failed', e));
          } else if (!shouldPlay && !outgoingEl.paused) {
            outgoingEl.pause();
          }
        }

        // 2. Sync and Play Incoming Video
        if (incomingEl) {
          const speed = incomingClip.speed || 1.0;
          const targetTime =
            (curTime - incomingClip.startTime) * speed + incomingClip.offset;
          const fileTime = Math.max(0, targetTime);
          const shouldPlay = isPlaying && targetTime >= 0;

          if (Math.abs(incomingEl.currentTime - fileTime) > 0.5) {
            incomingEl.currentTime = fileTime;
          }
          const targetVolume =
            incomingClip.volume !== undefined ? incomingClip.volume : 1.0;
          if (incomingEl.volume !== targetVolume) {
            incomingEl.volume = targetVolume;
          }
          if (incomingEl.playbackRate !== speed) {
            incomingEl.playbackRate = speed;
          }

          if (shouldPlay && incomingEl.paused) {
            incomingEl
              .play()
              .catch(e => console.error('[VideoSync] Incoming play failed', e));
          } else if (!shouldPlay && !incomingEl.paused) {
            incomingEl.pause();
          }
        }

        // 3. Apply Transition CSS Classes & Styles, and hide all other videos
        const progress =
          (curTime - activeTransition.startTime) / activeTransition.duration;

        els.videos.forEach((videoEl, idx) => {
          if (idx === outgoingIdx) {
            const outgoingClass = `transition-${activeTransition.type}`;
            if (
              !videoEl.classList.contains('transition-outgoing') ||
              !videoEl.classList.contains(outgoingClass)
            ) {
              this.clearTransitionStyles(videoEl);
              videoEl.classList.add(outgoingClass);
              videoEl.classList.add('transition-outgoing');
            }
            videoEl.style.setProperty(
              '--transition-progress',
              progress.toString(),
            );
          } else if (idx === incomingIdx) {
            const incomingClass = `transition-${activeTransition.type}`;
            if (
              !videoEl.classList.contains('transition-incoming') ||
              !videoEl.classList.contains(incomingClass)
            ) {
              this.clearTransitionStyles(videoEl);
              videoEl.classList.add(incomingClass);
              videoEl.classList.add('transition-incoming');
            }
            videoEl.style.setProperty(
              '--transition-progress',
              progress.toString(),
            );
          } else {
            // Hide and pause all other video elements
            if (
              videoEl.classList.contains('transition-outgoing') ||
              videoEl.classList.contains('transition-incoming') ||
              videoEl.style.opacity !== '0'
            ) {
              this.clearTransitionStyles(videoEl);
              videoEl.style.opacity = '0';
              videoEl.style.transform = 'none';
            }
            if (!videoEl.paused) {
              videoEl.pause();
            }
          }
        });
      } else {
        // --- Normal (No Transition) Flow ---
        const currentClip = this.timelineState.activeVideoClip();

        if (currentClip) {
          const activeIdx = clips.findIndex(c => c.id === currentClip.id);

          els.videos.forEach((videoEl, idx) => {
            if (idx === activeIdx) {
              // Active element: visible
              if (
                videoEl.classList.contains('transition-outgoing') ||
                videoEl.classList.contains('transition-incoming') ||
                videoEl.style.opacity !== '1'
              ) {
                this.clearTransitionStyles(videoEl);
                videoEl.style.opacity = '1';
                videoEl.style.transform = 'none';
              }

              const targetVolume =
                currentClip.volume !== undefined ? currentClip.volume : 1.0;
              const targetSpeed =
                currentClip.speed !== undefined ? currentClip.speed : 1.0;

              const fileTime =
                (curTime - currentClip.startTime) * targetSpeed +
                currentClip.offset;
              if (Math.abs(videoEl.currentTime - fileTime) > 0.5) {
                videoEl.currentTime = fileTime;
              }

              if (videoEl.volume !== targetVolume) {
                videoEl.volume = targetVolume;
              }
              if (videoEl.playbackRate !== targetSpeed) {
                videoEl.playbackRate = targetSpeed;
              }

              if (isPlaying && videoEl.paused) {
                videoEl
                  .play()
                  .catch(e => console.error('[VideoSync] Play failed', e));
              }
              if (!isPlaying && !videoEl.paused) {
                videoEl.pause();
              }
            } else {
              // Inactive elements: hidden and paused
              if (
                videoEl.classList.contains('transition-outgoing') ||
                videoEl.classList.contains('transition-incoming') ||
                videoEl.style.opacity !== '0'
              ) {
                this.clearTransitionStyles(videoEl);
                videoEl.style.opacity = '0';
                videoEl.style.transform = 'none';
              }
              if (!videoEl.paused) {
                videoEl.pause();
              }
            }
          });
        } else {
          // No active clip: hide all videos
          els.videos.forEach(videoEl => {
            this.clearTransitionStyles(videoEl);
            videoEl.style.opacity = '0';
            videoEl.style.transform = 'none';
            if (!videoEl.paused) {
              videoEl.pause();
            }
          });
        }
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

  private getActiveTransition(curTime: number) {
    const clips = this.timelineState.videoClips();
    for (let i = 0; i < clips.length - 1; i++) {
      const clipI = clips[i];
      const clipJ = clips[i + 1];
      const tType = clipI.transition_to_next_type;
      const tDuration = clipI.transition_to_next_duration;

      if (
        tType &&
        tType !== TransitionType.NONE &&
        tDuration &&
        tDuration > 0
      ) {
        const endTime = clipI.startTime + clipI.duration;
        const startTrans = endTime - tDuration / 2;
        const endTrans = endTime + tDuration / 2;

        if (curTime >= startTrans && curTime <= endTrans) {
          return {
            outgoingClip: clipI,
            incomingClip: clipJ,
            type: tType,
            duration: tDuration,
            startTime: startTrans,
            endTime: endTrans,
          };
        }
      }
    }
    return null;
  }

  private clearTransitionStyles(el: HTMLVideoElement) {
    el.classList.remove(
      'transition-fade',
      'transition-wipe_left',
      'transition-wipe_right',
      'transition-outgoing',
      'transition-incoming',
    );
    el.style.removeProperty('--transition-progress');
    el.style.removeProperty('opacity');
    el.style.removeProperty('transform');
  }

  private getNextVideoClip(): TimelineClip | undefined {
    const currentClip = this.timelineState.activeVideoClip();
    const clips = this.timelineState.videoClips();

    if (!currentClip) {
      return clips[0];
    }

    const index = clips.findIndex(c => c.id === currentClip.id);
    return clips[index + 1];
  }

  private initializeVideoSources(videos: HTMLVideoElement[]) {
    const clips = this.timelineState.videoClips();
    clips.forEach((clip, idx) => {
      const videoEl = videos[idx];
      if (videoEl) {
        const asset = this.timelineState
          .assets()
          .find(a => a.id === clip.assetId);
        if (asset && videoEl.src !== asset.url) {
          videoEl.src = asset.url;
          videoEl.load();
          videoEl.currentTime = clip.offset;
        }
      }
    });
  }

  registerElements(elements: {
    videos: HTMLVideoElement[];
    audios: HTMLAudioElement[];
    timeline: HTMLDivElement;
    dummyScroll: HTMLDivElement;
    timeRuler: TimeRulerComponent;
  }) {
    this.elements.set(elements);
    if (elements.videos.length > 0) {
      this.initializeVideoSources(elements.videos);
    }
  }

  runGameLoop() {
    let lastTime: number | null = null;
    const loop = (now: number) => {
      if (!this.timelineState.isPlaying()) return;

      const els = this.elements();
      if (!els) {
        this.animationFrameId = requestAnimationFrame(loop);
        return;
      }

      if (lastTime === null) {
        lastTime = now;
        this.animationFrameId = requestAnimationFrame(loop);
        return;
      }

      // Check if all preloaded videos are ready (or first clip ready)
      const currentClip = this.timelineState.activeVideoClip();
      const firstClip = this.timelineState.videoClips()[0];
      let isReady = true;

      if (currentClip) {
        const clips = this.timelineState.videoClips();
        const activeIdx = clips.findIndex(c => c.id === currentClip.id);
        const activeVideoEl = els.videos[activeIdx];
        if (activeVideoEl) {
          if (activeVideoEl.error) {
            console.error(
              '[VideoSync] Active video element encountered an error:',
              activeVideoEl.error,
            );
            this.timelineState.isPlaying.set(false);
            this.stopLoop();
            this.isVideoLoading.set(false);
            return;
          }

          if (
            currentClip.id === firstClip?.id &&
            activeVideoEl.readyState < 3
          ) {
            isReady = false;
          }
        }
      }

      this.isVideoLoading.set(!isReady);

      if (!isReady) {
        lastTime = now;
        els.audios.forEach(aud => {
          if (aud && !aud.paused) {
            aud.pause();
          }
        });
        els.videos.forEach(vid => {
          if (vid && !vid.paused) {
            vid.pause();
          }
        });

        this.animationFrameId = requestAnimationFrame(loop);
        return;
      }

      // Resume playing if isPlaying is true and elements were paused
      const curTime = this.timelineState.currentTime();
      const activeTransition = this.getActiveTransition(curTime);
      const clips = this.timelineState.videoClips();

      if (activeTransition) {
        const outgoingClip = activeTransition.outgoingClip;
        const incomingClip = activeTransition.incomingClip;

        const outgoingIdx = clips.findIndex(c => c.id === outgoingClip.id);
        const incomingIdx = clips.findIndex(c => c.id === incomingClip.id);

        const outgoingVideoEl =
          outgoingIdx !== -1 ? els.videos[outgoingIdx] : null;
        const incomingVideoEl =
          incomingIdx !== -1 ? els.videos[incomingIdx] : null;

        if (this.timelineState.isPlaying()) {
          if (
            outgoingVideoEl &&
            outgoingVideoEl.paused &&
            curTime <= outgoingClip.startTime + outgoingClip.duration
          ) {
            outgoingVideoEl
              .play()
              .catch(e => console.error('[VideoSync] Play failed', e));
          }
          if (incomingVideoEl) {
            const speed = incomingClip.speed || 1.0;
            const targetTime =
              (curTime - incomingClip.startTime) * speed + incomingClip.offset;
            const shouldPlayIncoming = targetTime >= 0;

            if (shouldPlayIncoming && incomingVideoEl.paused) {
              incomingVideoEl
                .play()
                .catch(e => console.error('[VideoSync] Play failed', e));
            } else if (!shouldPlayIncoming && !incomingVideoEl.paused) {
              incomingVideoEl.pause();
            }
          }
        }
      } else {
        const currentClip = this.timelineState.activeVideoClip();
        if (currentClip) {
          const activeIdx = clips.findIndex(c => c.id === currentClip.id);
          const activeVideoEl = els.videos[activeIdx];
          if (
            activeVideoEl &&
            activeVideoEl.paused &&
            this.timelineState.isPlaying()
          ) {
            activeVideoEl
              .play()
              .catch(e => console.error('[VideoSync] Play failed', e));
          }
        }
      }
      els.audios.forEach((aud, index) => {
        const activeAClips = this.timelineState.activeAudioClips();
        const aClip = activeAClips[index];
        if (aud && aClip && aud.paused && this.timelineState.isPlaying()) {
          aud.play().catch(e => console.error('Audio play failed', e));
        }
      });

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
          timeRuler?.setScrollLeft(newScrollLeft);
        }
      }

      if (nextTime >= this.timelineState.totalDuration()) {
        this.timelineState.currentTime.set(0);
        this.timelineState.scrollOffset.set(0);
        if (timeline) {
          timeline.scrollLeft = 0;
        }
        timeRuler?.setScrollLeft(0);
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
    this.isVideoLoading.set(false);
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
    }
  }
}
