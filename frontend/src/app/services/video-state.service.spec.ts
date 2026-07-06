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
import {VideoStateService} from './video-state.service';

describe('VideoStateService', () => {
  let service: VideoStateService;

  beforeEach(() => {
    try {
      localStorage.removeItem('video_state');
    } catch (e) {
      /* ignore */
    }
  });

  afterEach(() => {
    try {
      localStorage.removeItem('video_state');
    } catch (e) {
      /* ignore */
    }
  });

  function initService() {
    TestBed.configureTestingModule({
      providers: [VideoStateService],
    });
    service = TestBed.inject(VideoStateService);
  }

  it('should be created', () => {
    initService();
    expect(service).toBeTruthy();
  });

  it('should use default initial state if localStorage is empty', () => {
    initService();
    const state = service.getState();
    expect(state.prompt).toBe('');
    expect(state.aspectRatio).toBe('16:9');
    expect(state.model).toBe('gemini-omni-flash-preview');
    expect(state.numberOfMedia).toBe(1);
  });

  it('should load initial state from localStorage if present', () => {
    const savedState = {
      prompt: 'a cinematic shot of a forest',
      aspectRatio: '9:16',
      model: 'veo-3.1-generate-001',
    };
    localStorage.setItem('video_state', JSON.stringify(savedState));

    initService();
    const state = service.getState();
    expect(state.prompt).toBe('a cinematic shot of a forest');
    expect(state.aspectRatio).toBe('9:16');
    expect(state.model).toBe('veo-3.1-generate-001');
  });

  it('should update state and save to localStorage when updateState is called', () => {
    initService();

    service.updateState({prompt: 'updated video prompt', durationSeconds: 12});

    const state = service.getState();
    expect(state.prompt).toBe('updated video prompt');
    expect(state.durationSeconds).toBe(12);

    const saved = localStorage.getItem('video_state');
    expect(saved).toBeTruthy();
    if (saved) {
      const parsed = JSON.parse(saved);
      expect(parsed.prompt).toBe('updated video prompt');
      expect(parsed.durationSeconds).toBe(12);
    }
  });

  it('should reset state and remove from localStorage when resetState is called', () => {
    initService();

    service.updateState({prompt: 'temporary video prompt'});
    expect(localStorage.getItem('video_state')).toBeTruthy();

    service.resetState();
    expect(service.getState().prompt).toBe('');
    expect(localStorage.getItem('video_state')).toBeNull();
  });

  it('should fallback to default state and not crash if localStorage contains invalid JSON', () => {
    localStorage.setItem('video_state', 'invalid { json');
    const consoleSpy = spyOn(console, 'error');
    initService();
    const state = service.getState();
    expect(state.prompt).toBe('');
    expect(state.aspectRatio).toBe('16:9');
    expect(consoleSpy).toHaveBeenCalled();
  });

  it('should omit referenceVideo, referenceAudio, and referenceImages when saving state to localStorage', () => {
    initService();

    service.updateState({
      prompt: 'video with references',
      referenceImages: [{previewUrl: 'http://example.com/img.png'}],
      referenceVideo: {
        id: 1,
        type: 'source_asset',
        previewUrl: 'http://example.com/vid.mp4',
      },
      referenceAudio: {id: 1, type: 'source_asset', name: 'audio.mp3'},
    });

    const state = service.getState();
    expect(state.referenceImages.length).toBe(1);
    expect(state.referenceVideo).toBeTruthy();
    expect(state.referenceAudio).toBeTruthy();

    const saved = localStorage.getItem('video_state');
    expect(saved).toBeTruthy();
    if (saved) {
      const parsed = JSON.parse(saved);
      expect(parsed.prompt).toBe('video with references');
      expect(parsed.referenceImages).toBeUndefined();
      expect(parsed.referenceVideo).toBeUndefined();
      expect(parsed.referenceAudio).toBeUndefined();
    }
  });

  it('should not crash if localStorage.getItem throws an error during initialization', () => {
    spyOn(localStorage, 'getItem').and.throwError('SecurityError');
    const consoleSpy = spyOn(console, 'error');
    initService();
    expect(service.getState().prompt).toBe('');
    expect(consoleSpy).toHaveBeenCalledWith(
      'Failed to parse saved video state from localStorage',
      jasmine.any(Error),
    );
  });

  it('should not crash if localStorage.setItem throws an error during updateState', () => {
    initService();
    spyOn(localStorage, 'setItem').and.throwError('QuotaExceededError');
    const consoleSpy = spyOn(console, 'error');
    expect(() => {
      service.updateState({prompt: 'quota error prompt'});
    }).not.toThrow();
    expect(service.getState().prompt).toBe('quota error prompt');
    expect(consoleSpy).toHaveBeenCalledWith(
      'Failed to save video state to localStorage',
      jasmine.any(Error),
    );
  });

  it('should not crash if localStorage.removeItem throws an error during resetState', () => {
    initService();
    const removeSpy = spyOn(localStorage, 'removeItem').and.throwError(
      'SecurityError',
    );
    const consoleSpy = spyOn(console, 'error');
    expect(() => {
      service.resetState();
    }).not.toThrow();
    expect(service.getState().prompt).toBe('');
    expect(consoleSpy).toHaveBeenCalledWith(
      'Failed to remove video state from localStorage',
      jasmine.any(Error),
    );
    removeSpy.and.stub();
  });
});
