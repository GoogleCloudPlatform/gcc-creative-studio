/**
 * Copyright 2026 Google LLC
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
import {AudioStateService, AudioState} from './audio-state.service';

describe('AudioStateService', () => {
  let service: AudioStateService;

  beforeEach(() => {
    try {
      localStorage.removeItem('audio_generation_state');
    } catch (e) {
      /* ignore */
    }
    TestBed.configureTestingModule({});
    service = TestBed.inject(AudioStateService);
  });

  afterEach(() => {
    try {
      localStorage.removeItem('audio_generation_state');
    } catch (e) {
      /* ignore */
    }
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should use default initial state if localStorage is empty with sampleCount = 1', () => {
    const state = service.getState();
    expect(state.model).toBe('lyria');
    expect(state.prompt).toBe('');
    expect(state.negativePrompt).toBe('');
    expect(state.sampleCount).toBe(1);
    expect(state.selectedLanguage).toBe('en-US');
    expect(state.selectedVoice).toBe('Puck');
  });

  it('should load initial state from localStorage if present', () => {
    const savedState: Partial<AudioState> = {
      model: 'lyria',
      prompt: 'ambient techno',
      sampleCount: 2,
    };
    localStorage.setItem('audio_generation_state', JSON.stringify(savedState));

    const state = service.getState();
    expect(state.prompt).toBe('ambient techno');
    expect(state.sampleCount).toBe(2);
  });

  it('should update state and save to localStorage when updateState is called', () => {
    service.updateState({prompt: 'synthwave', sampleCount: 3});

    const state = service.getState();
    expect(state.prompt).toBe('synthwave');
    expect(state.sampleCount).toBe(3);

    const saved = localStorage.getItem('audio_generation_state');
    expect(saved).toBeTruthy();
    if (saved) {
      const parsed = JSON.parse(saved);
      expect(parsed.prompt).toBe('synthwave');
      expect(parsed.sampleCount).toBe(3);
    }
  });

  it('should clear state and remove from localStorage when clearState is called', () => {
    service.updateState({prompt: 'temporary'});
    expect(localStorage.getItem('audio_generation_state')).toBeTruthy();

    service.clearState();
    expect(localStorage.getItem('audio_generation_state')).toBeNull();
  });
});
