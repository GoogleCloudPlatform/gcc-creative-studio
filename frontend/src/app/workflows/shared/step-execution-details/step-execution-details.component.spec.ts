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

import {NO_ERRORS_SCHEMA} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {Router} from '@angular/router';
import {NodeTypes} from '../../workflow.models';
import {StepExecutionDetailsComponent} from './step-execution-details.component';

describe('StepExecutionDetailsComponent', () => {
  let component: StepExecutionDetailsComponent;
  let fixture: ComponentFixture<StepExecutionDetailsComponent>;
  let routerSpy: jasmine.SpyObj<Router>;

  beforeEach(async () => {
    routerSpy = jasmine.createSpyObj('Router', [
      'createUrlTree',
      'serializeUrl',
    ]);

    await TestBed.configureTestingModule({
      declarations: [StepExecutionDetailsComponent],
      providers: [{provide: Router, useValue: routerSpy}],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(StepExecutionDetailsComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('Image Step - Generate Image Mode', () => {
    beforeEach(() => {
      component.stepType = NodeTypes.IMAGE;
      component.mode = 'generate_image';
      component.inputs = {
        prompt: 'A futuristic city',
        input_images: null,
        input_image: null,
        model_image: null,
        top_image: null,
        bottom_image: null,
        dress_image: null,
        shoes_image: null,
      };
      component.outputs = {
        generated_image: 101,
        image_output: 101,
      };
      fixture.detectChanges();
    });

    it('should only include prompt in filteredInputs', () => {
      expect(component.filteredInputs).toEqual({
        prompt: 'A futuristic city',
      });
      expect(component.inputCount).toBe(1);
    });

    it('should only include generated_image in filteredOutputs and ignore redundant aliases', () => {
      expect(component.filteredOutputs).toEqual({
        generated_image: 101,
      });
      expect(component.outputCount).toBe(1);
    });

    it('should identify prompt as non-image input and other ports as image input', () => {
      expect(component.isImageInput('prompt')).toBeFalse();
      expect(component.isImageInput('input_images')).toBeTrue();
      expect(component.isImageOutput('generated_image')).toBeTrue();
      expect(component.isImageOutput('image_output')).toBeTrue();
    });
  });

  describe('Image Step - Edit Image Mode', () => {
    beforeEach(() => {
      component.stepType = NodeTypes.IMAGE;
      component.mode = 'edit_image';
      component.inputs = {
        prompt: 'Add fireworks',
        input_images: [101],
        input_image: null,
        model_image: null,
      };
      component.outputs = {
        generated_image: 202,
        edited_image: 202,
        image_output: 202,
      };
      fixture.detectChanges();
    });

    it('should only include prompt and input_images in filteredInputs', () => {
      expect(component.filteredInputs).toEqual({
        prompt: 'Add fireworks',
        input_images: [101],
      });
      expect(component.inputCount).toBe(2);
    });

    it('should only include single generated_image output', () => {
      expect(component.filteredOutputs).toEqual({
        generated_image: 202,
      });
      expect(component.outputCount).toBe(1);
    });
  });

  describe('Image Step - Upscale Image Mode', () => {
    beforeEach(() => {
      component.stepType = NodeTypes.IMAGE;
      component.mode = 'upscale_image';
      component.inputs = {
        prompt: null,
        input_images: null,
        input_image: 303,
        model_image: null,
      };
      component.outputs = {
        generated_image: 304,
        upscaled_image: 304,
        image_output: 304,
      };
      fixture.detectChanges();
    });

    it('should only include input_image in filteredInputs and omit null prompt', () => {
      expect(component.filteredInputs).toEqual({
        input_image: 303,
      });
      expect(component.inputCount).toBe(1);
    });

    it('should only include single generated_image output', () => {
      expect(component.filteredOutputs).toEqual({
        generated_image: 304,
      });
      expect(component.outputCount).toBe(1);
    });
  });

  describe('Image Step - Virtual Try-On Mode', () => {
    beforeEach(() => {
      component.stepType = NodeTypes.IMAGE;
      component.mode = 'virtual_try_on';
      component.inputs = {
        prompt: null,
        model_image: 401,
        top_image: 402,
        bottom_image: null,
        dress_image: null,
        shoes_image: null,
      };
      component.outputs = {
        generated_image: 405,
        image_output: 405,
      };
      fixture.detectChanges();
    });

    it('should only include provided VTO image inputs in filteredInputs', () => {
      expect(component.filteredInputs).toEqual({
        model_image: 401,
        top_image: 402,
      });
      expect(component.inputCount).toBe(2);
    });

    it('should only include single generated_image output', () => {
      expect(component.filteredOutputs).toEqual({
        generated_image: 405,
      });
      expect(component.outputCount).toBe(1);
    });
  });

  describe('Image Step Modes', () => {
    it('should filter inputs and outputs for edit_image mode', () => {
      component.stepType = NodeTypes.IMAGE;
      component.mode = 'edit_image';
      component.inputs = {
        prompt: 'Edit prompt',
        input_images: [501],
        input_image: null,
      };
      component.outputs = {
        edited_image: 502,
      };
      fixture.detectChanges();

      expect(component.filteredInputs).toEqual({
        prompt: 'Edit prompt',
        input_images: [501],
      });
      expect(component.filteredOutputs).toEqual({
        generated_image: 502,
      });
    });

    it('should filter inputs and outputs for upscale_image mode', () => {
      component.stepType = NodeTypes.IMAGE;
      component.mode = 'upscale_image';
      component.inputs = {
        prompt: null,
        input_image: 601,
      };
      component.outputs = {
        upscaled_image: 602,
      };
      fixture.detectChanges();

      expect(component.filteredInputs).toEqual({
        input_image: 601,
      });
      expect(component.filteredOutputs).toEqual({
        generated_image: 602,
      });
    });
  });

  describe('Non-Image Step Types', () => {
    it('should filter inputs and outputs for generate_text based on step config', () => {
      component.stepType = NodeTypes.GENERATE_TEXT;
      component.inputs = {
        prompt: 'Generate an article',
        input_images: null,
        extra_unknown_field: 'ignored',
      };
      component.outputs = {
        generated_text: 'Generated text article',
        extra_output: 'ignored',
      };
      fixture.detectChanges();

      expect(component.filteredInputs).toEqual({
        prompt: 'Generate an article',
      });
      expect(component.filteredOutputs).toEqual({
        generated_text: 'Generated text article',
      });
    });

    it('should filter inputs and outputs for generate_video and identify video/audio inputs', () => {
      component.stepType = NodeTypes.GENERATE_VIDEO;
      component.inputs = {
        prompt: 'add an elephant here',
        input_video: [{sourceAssetId: 10}],
        input_audio: [{step: 'step_1', output: 'generated_audio'}],
        extra_unknown_field: 'ignored',
      };
      component.outputs = {
        generated_video: 102,
      };
      fixture.detectChanges();

      expect(component.filteredInputs).toEqual({
        prompt: 'add an elephant here',
        input_video: [{sourceAssetId: 10}],
        input_audio: [{step: 'step_1', output: 'generated_audio'}],
      });
      expect(component.filteredOutputs).toEqual({
        generated_video: 102,
      });

      expect(component.isVideoInput('input_video')).toBeTrue();
      expect(component.isAudioInput('input_audio')).toBeTrue();
      expect(component.isImageInput('input_images')).toBeTrue();
      expect(component.isVideoOutput('generated_video')).toBeTrue();
    });

    it('should filter inputs and outputs for generate_audio', () => {
      component.stepType = NodeTypes.GENERATE_AUDIO;
      component.inputs = {
        prompt: 'ambient forest sounds',
      };
      component.outputs = {
        generated_audio: 103,
      };
      fixture.detectChanges();

      expect(component.filteredInputs).toEqual({
        prompt: 'ambient forest sounds',
      });
      expect(component.filteredOutputs).toEqual({
        generated_audio: 103,
      });

      expect(component.isAudioOutput('generated_audio')).toBeTrue();
    });
  });

  describe('Media URL resolution and helpers', () => {
    it('should resolve media URL from mediaUrlMap for numbers, string numbers, and references', () => {
      component.mediaUrlMap.set('media:101', 'https://example.com/image.png');
      component.mediaUrlMap.set('asset:202', 'https://example.com/asset.mp4');
      expect(component.getMediaUrl(101)).toBe('https://example.com/image.png');
      expect(component.getMediaUrl('101')).toBe(
        'https://example.com/image.png',
      );
      expect(component.getMediaUrl({sourceAssetId: 202})).toBe(
        'https://example.com/asset.mp4',
      );
      expect(
        component.getMediaUrl({previewUrl: 'https://example.com/preview.png'}),
      ).toBe('https://example.com/preview.png');
      expect(component.getMediaUrl('https://example.com/direct.png')).toBe(
        'https://example.com/direct.png',
      );
    });

    it('should track loaded media state for numbers and string numbers', () => {
      component.onMediaLoaded(101);
      expect(component.isLoaded(101)).toBeTrue();
      expect(component.isLoaded('101')).toBeTrue();
      expect(component.isLoaded(999)).toBeFalse();
    });

    it('should flatten nested resolved values', () => {
      expect(component.getResolvedValues([1, [2, 3]])).toEqual([1, 2, 3]);
      expect(component.getResolvedValues({_resolvedValue: [4, 5]})).toEqual([
        4, 5,
      ]);
      expect(
        component.getResolvedValues([{step: 'step_1', _resolvedValue: 42}]),
      ).toEqual([42]);
    });

    it('should provide stable tracking keys in trackByKey and trackByMedia', () => {
      expect(component.trackByKey(0, {key: 'prompt', value: 'hello'})).toBe(
        'prompt',
      );
      expect(component.trackByMedia(0, 101)).toBe('media:101');
      expect(component.trackByMedia(0, '101')).toBe('media:101');
      expect(component.trackByMedia(0, {sourceAssetId: 202})).toBe('asset:202');
      expect(
        component.trackByMedia(0, {previewUrl: 'https://example.com/test.mp4'}),
      ).toBe('https://example.com/test.mp4');
      expect(component.trackByMedia(3, null)).toBe(3);
    });

    it('should format display values correctly', () => {
      expect(component.formatDisplayValue('A prompt text')).toBe(
        'A prompt text',
      );
      expect(component.formatDisplayValue(123)).toBe('123');
      expect(component.formatDisplayValue(true)).toBe('true');
      expect(component.formatDisplayValue(null)).toBe('');
      expect(component.formatDisplayValue(undefined)).toBe('');
      expect(component.formatDisplayValue({key: 'val'})).toBe(
        '{\n  "key": "val"\n}',
      );
    });
  });
});
