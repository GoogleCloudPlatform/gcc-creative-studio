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
import {
  TransitionType,
  TimelineClip,
} from '../../common/models/workbench.model';

export interface TimeRulerInterface {
  setScrollLeft(left: number): void;
}

@Injectable({
  providedIn: 'root',
})
export class PlayheadSyncService {
  private timelineState = inject(TimelineStateService);
  isVideoLoading = signal<boolean>(false);
  private readonly targetStates = new Map<
    HTMLVideoElement,
    'playing' | 'paused'
  >();
  private readonly activeOperations = new Map<
    HTMLVideoElement,
    Promise<void>
  >();
  private readonly lastExecutedState = new Map<
    HTMLVideoElement,
    'playing' | 'paused'
  >();
  private readonly pendingSeeks = new Map<HTMLVideoElement, number>();
  private readonly lastSeekTime = new Map<HTMLVideoElement, number>();
  private readonly seekTimeout = new Map<HTMLVideoElement, any>();
  private readonly recoveringElements = new Set<HTMLVideoElement>();
  private readonly recoveryAttempts = new Map<HTMLVideoElement, number>();

  private elements = signal<{
    videos: HTMLVideoElement[];
    audios: HTMLAudioElement[];
    timeline: HTMLDivElement;
    dummyScroll: HTMLDivElement;
    timeRuler: TimeRulerInterface;
  } | null>(null);

  private animationFrameId: number | undefined;

  constructor() {
    effect(() => {
      if (this.timelineState.isPlaying()) {
        return;
      }
      const els = this.elements();
      if (!els) return;
      this.syncPlayhead(this.timelineState.currentTime());
    });
  }

  syncPlayhead(curTime: number) {
    const els = this.elements();
    if (!els) return;

    const isPlaying = this.timelineState.isPlaying();
    const activeTransition = this.getActiveTransition(curTime);
    const clips = this.timelineState.videoClips();

    if (activeTransition) {
      // --- Transition Flow ---
      const outgoingClip = activeTransition.outgoingClip;
      const incomingClip = activeTransition.incomingClip;

      const outgoingIdx = outgoingClip
        ? clips.findIndex(c => c.id === outgoingClip.id)
        : -1;
      const incomingIdx = incomingClip
        ? clips.findIndex(c => c.id === incomingClip.id)
        : -1;

      const outgoingEl = outgoingIdx !== -1 ? els.videos[outgoingIdx] : null;
      const incomingEl = incomingIdx !== -1 ? els.videos[incomingIdx] : null;

      // 1. Sync and Play Outgoing Video (plays until endTime and then freezes)
      if (outgoingEl && outgoingClip) {
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

        const driftThreshold = isPlaying ? 1.0 : 0.2;
        if (
          shouldPlay &&
          Math.abs(outgoingEl.currentTime - fileTime) > driftThreshold
        ) {
          this.safeSeek(outgoingEl, fileTime);
        }
        const targetVolume =
          outgoingClip.volume !== undefined ? outgoingClip.volume : 1.0;
        if (outgoingEl.volume !== targetVolume) {
          outgoingEl.volume = targetVolume;
        }
        if (outgoingEl.playbackRate !== speed) {
          outgoingEl.playbackRate = speed;
        }

        if (shouldPlay && outgoingEl.paused && outgoingEl.readyState >= 2) {
          this.safePlay(outgoingEl);
        } else if (!shouldPlay && !outgoingEl.paused) {
          this.safePause(outgoingEl);
        }
      }

      // 2. Sync and Play Incoming Video
      if (incomingEl && incomingClip) {
        const speed = incomingClip.speed || 1.0;
        const targetTime =
          (curTime - incomingClip.startTime) * speed + incomingClip.offset;
        const fileTime = Math.max(0, targetTime);
        const shouldPlay = isPlaying && targetTime >= 0;

        const driftThreshold = isPlaying ? 1.0 : 0.2;
        if (Math.abs(incomingEl.currentTime - fileTime) > driftThreshold) {
          this.safeSeek(incomingEl, fileTime);
        }
        const targetVolume =
          incomingClip.volume !== undefined ? incomingClip.volume : 1.0;
        if (incomingEl.volume !== targetVolume) {
          incomingEl.volume = targetVolume;
        }
        if (incomingEl.playbackRate !== speed) {
          incomingEl.playbackRate = speed;
        }

        if (shouldPlay && incomingEl.paused && incomingEl.readyState >= 2) {
          this.safePlay(incomingEl);
        } else if (!shouldPlay && !incomingEl.paused) {
          this.safePause(incomingEl);
        }
      }

      // 3. Apply Transition CSS Classes & Styles, and hide all other videos
      const progress =
        (curTime - activeTransition.startTime) / activeTransition.duration;

      els.videos.forEach((videoEl, idx) => {
        if (outgoingIdx !== -1 && idx === outgoingIdx) {
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
          let translateX = '0%';
          if (incomingIdx === -1) {
            if (activeTransition.type === TransitionType.WIPE_LEFT) {
              translateX = `${-progress * 100}%`;
            } else if (activeTransition.type === TransitionType.WIPE_RIGHT) {
              translateX = `${progress * 100}%`;
            }
          }
          videoEl.style.setProperty('--transition-translateX', translateX);
        } else if (incomingIdx !== -1 && idx === incomingIdx) {
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
          let translateX = '0%';
          if (activeTransition.type === TransitionType.WIPE_LEFT) {
            translateX = `${(1 - progress) * 100}%`;
          } else if (activeTransition.type === TransitionType.WIPE_RIGHT) {
            translateX = `${(progress - 1) * 100}%`;
          }
          videoEl.style.setProperty('--transition-translateX', translateX);
        } else {
          // Hide and pause all other video elements
          if (
            videoEl.classList.contains('transition-outgoing') ||
            videoEl.classList.contains('transition-incoming') ||
            videoEl.style.opacity !== '0.001'
          ) {
            this.clearTransitionStyles(videoEl);
            videoEl.style.opacity = '0.001';
            videoEl.style.transform = 'none';
          }
          if (!videoEl.paused) {
            this.safePause(videoEl);
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

              this.recoveringElements.add(videoEl);
              const onCanPlay = () => {
                videoEl.removeEventListener('canplay', onCanPlay);
                const targetSpeed =
                  currentClip.speed !== undefined ? currentClip.speed : 1.0;
                const fileTime =
                  (curTime - currentClip.startTime) * targetSpeed +
                  currentClip.offset;

                const onSeeked = () => {
                  videoEl.removeEventListener('seeked', onSeeked);
                  this.recoveringElements.delete(videoEl);
                  if (isPlaying && videoEl.paused) {
                    this.safePlay(videoEl);
                  }
                };
                videoEl.addEventListener('seeked', onSeeked);

                this.safeSeek(videoEl, fileTime);
              };
              videoEl.addEventListener('canplay', onCanPlay);
              videoEl.load();
              return;
            }

            const targetVolume =
              currentClip.volume !== undefined ? currentClip.volume : 1.0;
            const targetSpeed =
              currentClip.speed !== undefined ? currentClip.speed : 1.0;

            const fileTime =
              (curTime - currentClip.startTime) * targetSpeed +
              currentClip.offset;
            const driftThreshold = isPlaying ? 1.0 : 0.2;
            if (Math.abs(videoEl.currentTime - fileTime) > driftThreshold) {
              this.safeSeek(videoEl, fileTime);
            }

            if (videoEl.volume !== targetVolume) {
              videoEl.volume = targetVolume;
            }
            if (videoEl.playbackRate !== targetSpeed) {
              videoEl.playbackRate = targetSpeed;
            }

            if (isPlaying && videoEl.paused && videoEl.readyState >= 2) {
              this.safePlay(videoEl);
            }
            if (!isPlaying && !videoEl.paused) {
              this.safePause(videoEl);
            }
          } else {
            // Inactive elements: hidden and paused
            if (
              videoEl.classList.contains('transition-outgoing') ||
              videoEl.classList.contains('transition-incoming') ||
              videoEl.style.opacity !== '0.001'
            ) {
              this.clearTransitionStyles(videoEl);
              videoEl.style.opacity = '0.001';
              videoEl.style.transform = 'none';
            }
            if (!videoEl.paused) {
              this.safePause(videoEl);
            }
          }
        });
      } else {
        // No active clip: hide all videos
        els.videos.forEach(videoEl => {
          this.clearTransitionStyles(videoEl);
          videoEl.style.opacity = '0.001';
          videoEl.style.transform = 'none';
          if (!videoEl.paused) {
            this.safePause(videoEl);
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
          if (!aud.src || aud.src === window.location.href || aud.error) {
            return;
          }
          const targetVolume = aClip.volume !== undefined ? aClip.volume : 1.0;
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
  }

  private getActiveTransition(curTime: number) {
    const clips = this.timelineState.videoClips();
    if (clips.length === 0) return null;

    // 1. Check transition_in
    const transitionIn = this.timelineState.transitionIn();
    if (
      transitionIn &&
      transitionIn.type !== TransitionType.NONE &&
      transitionIn.duration_seconds > 0
    ) {
      const duration = transitionIn.duration_seconds;
      if (curTime >= 0 && curTime <= duration) {
        return {
          incomingClip: clips[0],
          type: transitionIn.type,
          duration: duration,
          startTime: 0,
          endTime: duration,
        };
      }
    }

    // 2. Check in-between transitions
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

    // 3. Check transition_out
    const transitionOut = this.timelineState.transitionOut();
    if (
      transitionOut &&
      transitionOut.type !== TransitionType.NONE &&
      transitionOut.duration_seconds > 0
    ) {
      const lastClip = clips[clips.length - 1];
      const lastVideoEndTime = lastClip.startTime + lastClip.duration;
      if (lastVideoEndTime > 0) {
        const duration = transitionOut.duration_seconds;
        const startTrans = lastVideoEndTime - duration;
        if (curTime >= startTrans && curTime <= lastVideoEndTime) {
          return {
            outgoingClip: lastClip,
            type: transitionOut.type,
            duration: duration,
            startTime: startTrans,
            endTime: lastVideoEndTime,
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
    el.style.removeProperty('--transition-translateX');
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
        if (asset) {
          const loadedAssetId = videoEl.getAttribute('data-loaded-asset-id');
          if (loadedAssetId !== asset.id) {
            videoEl.src = asset.url;
            videoEl.setAttribute('data-loaded-asset-id', asset.id);
            videoEl.load();
            videoEl.currentTime = clip.offset;
          }
        }
      }
    });
  }

  registerElements(elements: {
    videos: HTMLVideoElement[];
    audios: HTMLAudioElement[];
    timeline: HTMLDivElement;
    dummyScroll: HTMLDivElement;
    timeRuler: TimeRulerInterface;
  }) {
    this.targetStates.clear();
    this.activeOperations.clear();
    this.lastExecutedState.clear();
    this.pendingSeeks.clear();
    this.seekTimeout.forEach(timeout => clearTimeout(timeout));
    this.seekTimeout.clear();
    this.lastSeekTime.clear();
    this.recoveringElements.clear();
    this.recoveryAttempts.clear();
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
          if (
            activeVideoEl.error &&
            !this.recoveringElements.has(activeVideoEl)
          ) {
            const attempts = this.recoveryAttempts.get(activeVideoEl) || 0;
            if (attempts >= 3) {
              console.error(
                '[VideoSync] Active video element exceeded recovery attempts. Stopping loop.',
                activeVideoEl.error,
              );
              this.timelineState.isPlaying.set(false);
              this.stopLoop();
              this.isVideoLoading.set(false);
              return;
            }
            this.recoveryAttempts.set(activeVideoEl, attempts + 1);
            this.recoveringElements.add(activeVideoEl);

            console.warn(
              `[VideoSync] Active video element encountered an error, recovering (attempt ${attempts + 1})...`,
              activeVideoEl.error,
            );

            this.targetStates.delete(activeVideoEl);
            this.activeOperations.delete(activeVideoEl);
            this.lastExecutedState.delete(activeVideoEl);

            const onCanPlay = () => {
              activeVideoEl.removeEventListener('canplay', onCanPlay);
              const targetSpeed =
                currentClip.speed !== undefined ? currentClip.speed : 1.0;
              const fileTime =
                (this.timelineState.currentTime() - currentClip.startTime) *
                  targetSpeed +
                currentClip.offset;

              const onSeeked = () => {
                activeVideoEl.removeEventListener('seeked', onSeeked);
                this.recoveringElements.delete(activeVideoEl);

                // Reset recovery attempts after 500ms of successful playback/seeking
                setTimeout(() => {
                  if (!activeVideoEl.error) {
                    this.recoveryAttempts.set(activeVideoEl, 0);
                  }
                }, 500);

                if (this.timelineState.isPlaying()) {
                  this.safePlay(activeVideoEl);
                }
              };
              activeVideoEl.addEventListener('seeked', onSeeked);

              this.safeSeek(activeVideoEl, fileTime);
            };
            activeVideoEl.addEventListener('canplay', onCanPlay);

            activeVideoEl.load();

            lastTime = now;
            this.animationFrameId = requestAnimationFrame(loop);
            return;
          }

          if (activeVideoEl.readyState < 2) {
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
            this.safePause(vid);
          }
        });

        this.animationFrameId = requestAnimationFrame(loop);
        return;
      }

      // Resume playing
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
        this.syncPlayhead(0);
        this.timelineState.isPlaying.set(false);
      } else {
        this.timelineState.currentTime.set(nextTime);
        this.syncPlayhead(nextTime);
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

  private safePlay(videoEl: HTMLVideoElement) {
    this.targetStates.set(videoEl, 'playing');
    if (!this.activeOperations.has(videoEl)) {
      this.runOperationChain(videoEl);
    }
  }

  private safePause(videoEl: HTMLVideoElement) {
    this.targetStates.set(videoEl, 'paused');
    if (!this.activeOperations.has(videoEl)) {
      this.runOperationChain(videoEl);
    }
  }

  private runOperationChain(videoEl: HTMLVideoElement) {
    const target = this.targetStates.get(videoEl);
    if (!target) return;

    const isCurrentlyPlaying = !videoEl.paused;
    if (target === 'playing' && isCurrentlyPlaying) {
      this.lastExecutedState.delete(videoEl);
      return;
    }
    if (target === 'paused' && !isCurrentlyPlaying) {
      this.lastExecutedState.delete(videoEl);
      return;
    }

    if (this.lastExecutedState.get(videoEl) === target) {
      return;
    }

    this.lastExecutedState.set(videoEl, target);

    if (target === 'playing') {
      const promise = videoEl.play();
      if (promise !== undefined) {
        this.activeOperations.set(videoEl, promise);
        promise
          .then(() => {
            this.activeOperations.delete(videoEl);
            this.lastExecutedState.delete(videoEl);
            this.runOperationChain(videoEl);
          })
          .catch(err => {
            this.activeOperations.delete(videoEl);
            if (err.name !== 'AbortError') {
              console.error('[VideoSync] Play failed:', err);
            }
            this.runOperationChain(videoEl);
          });
      } else {
        this.lastExecutedState.delete(videoEl);
        this.runOperationChain(videoEl);
      }
    } else {
      videoEl.pause();
      this.lastExecutedState.delete(videoEl);
      this.runOperationChain(videoEl);
    }
  }

  private safeSeek(videoEl: HTMLVideoElement, fileTime: number) {
    const activeTimeout = this.seekTimeout.get(videoEl);
    if (activeTimeout) {
      clearTimeout(activeTimeout);
      this.seekTimeout.delete(videoEl);
    }

    const now = Date.now();
    const lastSeek = this.lastSeekTime.get(videoEl) || 0;
    const timeSinceLastSeek = now - lastSeek;

    if (timeSinceLastSeek < 150) {
      const delay = 150 - timeSinceLastSeek;
      const timeout = setTimeout(() => {
        this.safeSeek(videoEl, fileTime);
      }, delay);
      this.seekTimeout.set(videoEl, timeout);
      return;
    }

    if (videoEl.seeking) {
      this.pendingSeeks.set(videoEl, fileTime);
      return;
    }

    this.lastSeekTime.set(videoEl, now);
    videoEl.currentTime = fileTime;

    const onSeeked = () => {
      videoEl.removeEventListener('seeked', onSeeked);
      const pendingTime = this.pendingSeeks.get(videoEl);
      if (pendingTime !== undefined) {
        this.pendingSeeks.delete(videoEl);
        this.safeSeek(videoEl, pendingTime);
      }
    };
    videoEl.addEventListener('seeked', onSeeked);
  }
}
