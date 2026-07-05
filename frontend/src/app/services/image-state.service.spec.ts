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
import {ImageStateService, ImageState} from './image-state.service';

describe('ImageStateService', () => {
  let service: ImageStateService;

  beforeEach(() => {
    try {
      localStorage.removeItem('image_state');
    } catch (e) {
      /* ignore */
    }
    TestBed.configureTestingModule({});
  });

  afterEach(() => {
    try {
      localStorage.removeItem('image_state');
    } catch (e) {
      /* ignore */
    }
  });

  it('should be created', () => {
    service = TestBed.inject(ImageStateService);
    expect(service).toBeTruthy();
  });

  it('should use default initial state if localStorage is empty', () => {
    service = TestBed.inject(ImageStateService);
    const state = service.getState();
    expect(state.prompt).toBe('');
    expect(state.aspectRatio).toBe('1:1');
    expect(state.model).toBe('gemini-3.1-flash-lite-image');
  });

  it('should load initial state from localStorage if present', () => {
    const savedState: Partial<ImageState> = {
      prompt: 'a futuristic city',
      aspectRatio: '16:9',
      model: 'gemini-3.1-flash-image',
    };
    localStorage.setItem('image_state', JSON.stringify(savedState));

    service = TestBed.inject(ImageStateService);
    const state = service.getState();
    expect(state.prompt).toBe('a futuristic city');
    expect(state.aspectRatio).toBe('16:9');
    expect(state.model).toBe('gemini-3.1-flash-image');
  });

  it('should update state and save to localStorage when updateState is called', () => {
    service = TestBed.inject(ImageStateService);

    service.updateState({prompt: 'new prompt', aspectRatio: '4:3'});

    const state = service.getState();
    expect(state.prompt).toBe('new prompt');
    expect(state.aspectRatio).toBe('4:3');

    const saved = localStorage.getItem('image_state');
    expect(saved).toBeTruthy();
    if (saved) {
      const parsed = JSON.parse(saved);
      expect(parsed.prompt).toBe('new prompt');
      expect(parsed.aspectRatio).toBe('4:3');
    }
  });

  it('should reset state and remove from localStorage when resetState is called', () => {
    service = TestBed.inject(ImageStateService);

    service.updateState({prompt: 'temporary prompt'});
    expect(localStorage.getItem('image_state')).toBeTruthy();

    service.resetState();
    expect(service.getState().prompt).toBe('');
    expect(localStorage.getItem('image_state')).toBeNull();
  });

  it('should fallback to default state and not crash if localStorage contains invalid JSON', () => {
    localStorage.setItem('image_state', 'invalid { json');
    const consoleSpy = spyOn(console, 'error');
    service = TestBed.inject(ImageStateService);
    const state = service.getState();
    expect(state.prompt).toBe('');
    expect(state.aspectRatio).toBe('1:1');
    expect(consoleSpy).toHaveBeenCalled();
  });

  it('should not crash if localStorage.getItem throws an error during initialization', () => {
    spyOn(localStorage, 'getItem').and.throwError('SecurityError');
    const consoleSpy = spyOn(console, 'error');
    service = TestBed.inject(ImageStateService);
    expect(service.getState().prompt).toBe('');
    expect(consoleSpy).toHaveBeenCalledWith(
      'Failed to load saved image state from localStorage',
      jasmine.any(Error),
    );
  });

  it('should not crash if localStorage.setItem throws an error during updateState', () => {
    service = TestBed.inject(ImageStateService);
    spyOn(localStorage, 'setItem').and.throwError('QuotaExceededError');
    const consoleSpy = spyOn(console, 'error');
    expect(() => {
      service.updateState({prompt: 'prompt exceeding quota'});
    }).not.toThrow();
    expect(service.getState().prompt).toBe('prompt exceeding quota');
    expect(consoleSpy).toHaveBeenCalledWith(
      'Failed to save image state to localStorage',
      jasmine.any(Error),
    );
  });

  it('should not crash if localStorage.removeItem throws an error during resetState', () => {
    service = TestBed.inject(ImageStateService);
    const removeSpy = spyOn(localStorage, 'removeItem').and.throwError(
      'SecurityError',
    );
    const consoleSpy = spyOn(console, 'error');
    expect(() => {
      service.resetState();
    }).not.toThrow();
    expect(service.getState().prompt).toBe('');
    expect(consoleSpy).toHaveBeenCalledWith(
      'Failed to remove image state from localStorage',
      jasmine.any(Error),
    );
    removeSpy.and.stub();
  });
});
