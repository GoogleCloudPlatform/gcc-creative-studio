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

import {Injectable} from '@angular/core';
import {BehaviorSubject, Observable} from 'rxjs';

import {
  ReferenceImage,
  ReferenceVideo,
  ReferenceAudio,
} from '../common/models/search.model';
import {MODEL_CONFIGS} from '../common/config/model-config';

const STORAGE_KEY = 'video_state';

interface VideoState {
  prompt: string;
  aspectRatio: string;
  resolution: '1K' | '2K' | '4K';
  model: string;
  style: string | null;
  colorAndTone: string | null;
  lighting: string | null;
  numberOfMedia: number;
  durationSeconds: number;
  composition: string | null;
  generateAudio: boolean;
  negativePrompt: string;
  useBrandGuidelines: boolean;
  enhancePrompt: boolean;
  mode: string;
  referenceImages: ReferenceImage[];
  referenceImagesType: 'ASSET' | 'STYLE';
  referenceVideo: ReferenceVideo | null;
  referenceAudio: ReferenceAudio | null;
}

@Injectable({
  providedIn: 'root',
})
export class VideoStateService {
  private initialState: VideoState;
  private state: BehaviorSubject<VideoState>;
  state$: Observable<VideoState>;

  constructor() {
    this.initialState = {
      prompt: '',
      aspectRatio: '16:9',
      resolution: '1K',
      model: 'gemini-omni-flash-preview',
      style: null,
      colorAndTone: null,
      lighting: null,
      numberOfMedia: 1,
      durationSeconds: 8,
      composition: null,
      generateAudio: true,
      negativePrompt: '',
      useBrandGuidelines: false,
      enhancePrompt: false,
      mode: 'Text to Video',
      referenceImages: [],
      referenceImagesType: 'ASSET',
      referenceVideo: null,
      referenceAudio: null,
    };

    let savedState: VideoState | null = null;
    if (typeof localStorage !== 'undefined') {
      try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
          const parsed = JSON.parse(saved);
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            let loadedModel = parsed.model ?? this.initialState.model;
            let loadedNumMedia =
              parsed.numberOfMedia ?? this.initialState.numberOfMedia;

            const isValidVideoModel = MODEL_CONFIGS.some(
              m => m.type === 'VIDEO' && m.value === loadedModel,
            );

            if (!isValidVideoModel) {
              loadedModel = this.initialState.model;
              loadedNumMedia = this.initialState.numberOfMedia;
            }

            savedState = {
              ...this.initialState,
              ...parsed,
              model: loadedModel,
              numberOfMedia: loadedNumMedia,
              referenceVideo: null,
              referenceAudio: null,
              referenceImages: [],
            };
          }
        }
      } catch (e) {
        console.error('Failed to parse saved video state from localStorage', e);
      }
    }
    if (savedState) {
      this.state = new BehaviorSubject<VideoState>(savedState);
    } else {
      this.state = new BehaviorSubject<VideoState>({...this.initialState});
    }
    this.state$ = this.state.asObservable();
  }

  updateState(newState: Partial<VideoState>) {
    const updated = {...this.state.value, ...newState};
    this.state.next(updated);
    if (typeof localStorage !== 'undefined') {
      try {
        // Don't save reference files to localStorage
        const partialState: Partial<VideoState> = {...updated};
        delete partialState.referenceVideo;
        delete partialState.referenceAudio;
        delete partialState.referenceImages;
        localStorage.setItem(STORAGE_KEY, JSON.stringify(partialState));
      } catch (e) {
        console.error('Failed to save video state to localStorage', e);
      }
    }
  }

  getState(): VideoState {
    return this.state.value;
  }

  resetState() {
    this.state.next({
      ...this.initialState,
      referenceImages: [],
    });
    if (typeof localStorage !== 'undefined') {
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch (e) {
        console.error('Failed to remove video state from localStorage', e);
      }
    }
  }
}
