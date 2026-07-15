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
import {MODEL_CONFIGS} from '../common/config/model-config';

const STORAGE_KEY = 'image_state';

export interface ImageState {
  prompt: string;
  negativePrompt: string;
  aspectRatio: string;
  model: string;
  lighting: string | null;
  watermark: boolean;
  googleSearch: boolean;
  resolution: string;
  style: string | null;
  colorAndTone: string | null;
  numberOfMedia: number;
  composition: string | null;
  useBrandGuidelines: boolean;
  enhancePrompt: boolean;
  mode: string;
}

@Injectable({
  providedIn: 'root',
})
export class ImageStateService {
  private initialState: ImageState;
  private state: BehaviorSubject<ImageState>;
  state$: Observable<ImageState>;

  constructor() {
    this.initialState = {
      prompt: '',
      negativePrompt: '',
      aspectRatio: '1:1',
      model: 'gemini-3.1-flash-lite-image',
      lighting: '',
      watermark: false,
      googleSearch: false,
      resolution: '1K',
      style: null,
      colorAndTone: null,
      numberOfMedia: 4,
      composition: null,
      useBrandGuidelines: false,
      enhancePrompt: false,
      mode: 'Text to Image',
    };

    let savedState: ImageState | null = null;
    if (typeof localStorage !== 'undefined') {
      try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
          const parsed = JSON.parse(saved);
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            let loadedModel = parsed.model ?? this.initialState.model;

            const isValidImageModel = MODEL_CONFIGS.some(
              m => m.type === 'IMAGE' && m.value === loadedModel,
            );

            if (!isValidImageModel) {
              loadedModel = this.initialState.model;
            }

            savedState = {...this.initialState, ...parsed, model: loadedModel};
          }
        }
      } catch (e) {
        console.error('Failed to load saved image state from localStorage', e);
      }
    }
    if (savedState) {
      this.state = new BehaviorSubject<ImageState>(savedState);
    } else {
      this.state = new BehaviorSubject<ImageState>({...this.initialState});
    }
    this.state$ = this.state.asObservable();
  }

  updateState(newState: Partial<ImageState>) {
    const updated = {...this.state.value, ...newState};
    this.state.next(updated);
    if (typeof localStorage !== 'undefined') {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      } catch (e) {
        console.error('Failed to save image state to localStorage', e);
      }
    }
  }

  getState(): ImageState {
    return this.state.value;
  }

  resetState() {
    this.state.next({...this.initialState});
    if (typeof localStorage !== 'undefined') {
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch (e) {
        console.error('Failed to remove image state from localStorage', e);
      }
    }
  }
}
