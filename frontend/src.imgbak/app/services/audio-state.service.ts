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

export interface AudioState {
  model: string;
  prompt: string;
  negativePrompt: string;
  seed?: number;
  sampleCount: number;
  selectedLanguage: string;
  selectedVoice: string;
}

@Injectable({
  providedIn: 'root',
})
export class AudioStateService {
  private readonly STORAGE_KEY = 'audio_generation_state';

  private defaultState: AudioState = {
    model: 'lyria',
    prompt: '',
    negativePrompt: '',
    seed: undefined,
    sampleCount: 4,
    selectedLanguage: 'en-US',
    selectedVoice: 'Puck',
  };

  getState(): AudioState {
    const saved = localStorage.getItem(this.STORAGE_KEY);
    if (saved) {
      try {
        const parsedState = JSON.parse(saved);
        return {...this.defaultState, ...parsedState};
      } catch (e) {
        console.error('Failed to parse audio state', e);
        return this.defaultState;
      }
    }
    return this.defaultState;
  }

  updateState(partialState: Partial<AudioState>) {
    const currentState = this.getState();
    const newState = {...currentState, ...partialState};
    localStorage.setItem(this.STORAGE_KEY, JSON.stringify(newState));
  }

  clearState() {
    localStorage.removeItem(this.STORAGE_KEY);
  }
}
