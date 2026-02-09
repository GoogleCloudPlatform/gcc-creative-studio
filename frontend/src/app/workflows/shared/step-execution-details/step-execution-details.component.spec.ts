/**
 * Copyright 2024 Google LLC
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

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { of } from 'rxjs';

import { StepExecutionDetailsComponent } from './step-execution-details.component';

describe('StepExecutionDetailsComponent', () => {
  let component: StepExecutionDetailsComponent;
  let fixture: ComponentFixture<StepExecutionDetailsComponent>;
  let router: Router;

  const mockStepConfigs = {
    'text-step': {
      inputs: [{ name: 'prompt', type: 'text' }],
      outputs: [{ name: 'text', type: 'text' }],
    },
    'image-step': {
      inputs: [{ name: 'image', type: 'image' }],
      outputs: [{ name: 'image', type: 'image' }],
    },
    'video-step': {
      inputs: [{ name: 'video', type: 'video' }],
      outputs: [{ name: 'video', type: 'video' }],
    },
    'audio-step': {
      inputs: [{ name: 'audio', type: 'audio' }],
      outputs: [{ name: 'audio', type: 'audio' }],
    },
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [StepExecutionDetailsComponent],
      providers: [
        {
          provide: Router,
          useValue: {
            createUrlTree: () => {},
            serializeUrl: () => 'mock-url',
          },
        },
      ],
    }).compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(StepExecutionDetailsComponent);
    component = fixture.componentInstance;
    router = TestBed.inject(Router);
    spyOn(component, 'getStepConfig').and.callFake(() => {
      return (mockStepConfigs as any)[component.stepType];
    });
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('getMediaUrl', () => {
    it('should return the URL from mediaUrlMap if key exists', () => {
      component.mediaUrlMap.set('media:123', 'http://example.com/media.jpg');
      expect(component.getMediaUrl(123)).toBe('http://example.com/media.jpg');
    });

    it('should return previewUrl if value is an object with previewUrl', () => {
      const value = { previewUrl: 'http://example.com/preview.jpg' };
      expect(component.getMediaUrl(value)).toBe('http://example.com/preview.jpg');
    });

    it('should return the value if it is a string starting with http', () => {
      const value = 'http://example.com/image.jpg';
      expect(component.getMediaUrl(value)).toBe(value);
    });

    it('should return the value if it is a string starting with data:', () => {
      const value = 'data:image/png;base64,';
      expect(component.getMediaUrl(value)).toBe(value);
    });

    it('should return an empty string for other cases', () => {
      expect(component.getMediaUrl('not-a-url')).toBe('');
      expect(component.getMediaUrl({})).toBe('');
      expect(component.getMediaUrl(null)).toBe('');
    });
  });

  describe('onMediaLoaded', () => {
    it('should add the key to loadedMedia', () => {
      component.onMediaLoaded(123);
      expect(component.loadedMedia.has('media:123')).toBe(true);
    });
  });

  describe('navigateToGallery', () => {
    it('should not navigate if id is not found', () => {
      spyOn(window, 'open');
      component.navigateToGallery({});
      expect(window.open).not.toHaveBeenCalled();
    });

    it('should navigate to gallery if id is found and it is a media item', () => {
      spyOn(window, 'open');
      spyOn(router, 'createUrlTree').and.callThrough();
      component.mediaUrlMap.set('media:123', 'http://example.com/media.jpg');
      component.navigateToGallery(123);
      expect(router.createUrlTree).toHaveBeenCalledWith(['/gallery', 123]);
      expect(window.open).toHaveBeenCalledWith('mock-url', '_blank');
    });
  });

  describe('isLoaded', () => {
    it('should return true if media is loaded', () => {
      component.loadedMedia.add('media:123');
      expect(component.isLoaded(123)).toBe(true);
    });

    it('should return false if media is not loaded', () => {
      expect(component.isLoaded(123)).toBe(false);
    });
  });

  describe('isArray', () => {
    it('should return true for arrays', () => {
      expect(component.isArray([])).toBe(true);
    });

    it('should return false for non-arrays', () => {
      expect(component.isArray({})).toBe(false);
      expect(component.isArray('string')).toBe(false);
      expect(component.isArray(123)).toBe(false);
    });
  });

  describe('getResolvedValues', () => {
    it('should return an array with the value for simple values', () => {
      expect(component.getResolvedValues('hello')).toEqual(['hello']);
      expect(component.getResolvedValues(123)).toEqual([123]);
    });

    it('should flatten nested arrays', () => {
      expect(component.getResolvedValues([1, [2, 3]])).toEqual([1, 2, 3]);
    });

    it('should resolve values with _resolvedValue property', () => {
      const value = { _resolvedValue: [{ _resolvedValue: 'a' }, 'b'] };
      expect(component.getResolvedValues(value)).toEqual(['a', 'b']);
    });
  });

  describe('isImageInput', () => {
    it('should return true if input is an image', () => {
      component.stepType = 'image-step';
      expect(component.isImageInput('image')).toBe(true);
    });

    it('should return false if input is not an image', () => {
      component.stepType = 'text-step';
      expect(component.isImageInput('prompt')).toBe(false);
    });
  });

  describe('isImageOutput', () => {
    it('should return true if output is an image', () => {
      component.stepType = 'image-step';
      expect(component.isImageOutput('image')).toBe(true);
    });

    it('should return false if output is not an image', () => {
      component.stepType = 'text-step';
      expect(component.isImageOutput('text')).toBe(false);
    });
  });

  describe('isTextOutput', () => {
    it('should return true if output is a text', () => {
      component.stepType = 'text-step';
      expect(component.isTextOutput('text')).toBe(true);
    });

    it('should return false if output is not a text', () => {
      component.stepType = 'image-step';
      expect(component.isTextOutput('image')).toBe(false);
    });
  });

  describe('isVideoOutput', () => {
    it('should return true if output is a video', () => {
      component.stepType = 'video-step';
      expect(component.isVideoOutput('video')).toBe(true);
    });

    it('should return false if output is not a video', () => {
      component.stepType = 'text-step';
      expect(component.isVideoOutput('text')).toBe(false);
    });
  });

  describe('isAudioOutput', () => {
    it('should return true if output is an audio', () => {
      component.stepType = 'audio-step';
      expect(component.isAudioOutput('audio')).toBe(true);
    });

    it('should return false if output is not an audio', () => {
      component.stepType = 'text-step';
      expect(component.isAudioOutput('text')).toBe(false);
    });
  });

  describe('isVideoInput', () => {
    it('should return true if input is a video', () => {
      component.stepType = 'video-step';
      expect(component.isVideoInput('video')).toBe(true);
    });

    it('should return false if input is not a video', () => {
      component.stepType = 'text-step';
      expect(component.isVideoInput('prompt')).toBe(false);
    });
  });

  describe('isAudioInput', () => {
    it('should return true if input is an audio', () => {
      component.stepType = 'audio-step';
      expect(component.isAudioInput('audio')).toBe(true);
    });

    it('should return false if input is not an audio', () => {
      component.stepType = 'text-step';
      expect(component.isAudioInput('prompt')).toBe(false);
    });
  });

  describe('inputCount', () => {
    it('should return the correct number of inputs', () => {
      component.inputs = { a: 1, b: 2 };
      expect(component.inputCount).toBe(2);
    });
  });

  describe('outputCount', () => {
    it('should return the correct number of outputs', () => {
      component.outputs = { x: 1, y: 2, z: 3 };
      expect(component.outputCount).toBe(3);
    });
  });
});
