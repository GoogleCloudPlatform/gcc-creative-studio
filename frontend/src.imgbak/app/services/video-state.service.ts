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

import {SettingsService} from './settings.service';
import {
  ReferenceImage,
  ReferenceVideo,
  ReferenceAudio,
} from '../common/models/search.model';

interface VideoState {
  prompt: string;
  aspectRatio: string;
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

  constructor(private settingsService: SettingsService) {
    const showOmni = this.settingsService.getShowGeminiOmni();

    this.initialState = {
      prompt: '',
      aspectRatio: '16:9',
      model: showOmni ? 'gemini-omni-generate-preview' : 'veo-3.1-generate-001',
      style: null,
      colorAndTone: null,
      lighting: null,
      numberOfMedia: showOmni ? 1 : 4,
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

    this.state = new BehaviorSubject<VideoState>(this.initialState);
    this.state$ = this.state.asObservable();
  }

  updateState(newState: Partial<VideoState>) {
    this.state.next({...this.state.value, ...newState});
  }

  getState(): VideoState {
    return this.state.value;
  }

  resetState() {
    this.state.next(this.initialState);
  }
}
