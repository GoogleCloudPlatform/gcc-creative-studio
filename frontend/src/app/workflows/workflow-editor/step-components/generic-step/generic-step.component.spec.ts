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
import {FormBuilder, ReactiveFormsModule} from '@angular/forms';
import {WorkflowStatusPipe} from '../../../workflow-status.pipe';
import {IMAGE_STEP_CONFIG} from '../step-configs/image-step.config';
import {GenericStepComponent} from './generic-step.component';

describe('GenericStepComponent - Image Node Dynamic Mode Selection', () => {
  let component: GenericStepComponent;
  let fixture: ComponentFixture<GenericStepComponent>;
  let fb: FormBuilder;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [GenericStepComponent],
      imports: [ReactiveFormsModule, WorkflowStatusPipe],
      providers: [FormBuilder],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fb = TestBed.inject(FormBuilder);
    fixture = TestBed.createComponent(GenericStepComponent);
    component = fixture.componentInstance;

    // Create a step form corresponding to an Image node
    component.stepForm = fb.group({
      stepId: ['image_step_1'],
      type: ['image'],
      status: ['idle'],
      inputs: fb.group({
        prompt: [''],
        input_images: [null],
        input_image: [null],
        model_image: [null],
        top_image: [null],
        bottom_image: [null],
        dress_image: [null],
        shoes_image: [null],
      }),
      settings: fb.group({
        mode: ['generate_image'],
        model: ['gemini-3.1-flash-image'],
        aspect_ratio: ['1:1'],
        brand_guidelines: [false],
        upscale_factor: ['x2'],
        enhance_input_image: [false],
        image_preservation_factor: [null],
      }),
      outputs: fb.group({
        generated_image: [{type: 'image'}],
      }),
    });

    component.config = IMAGE_STEP_CONFIG;
    component.stepIndex = 0;
    fixture.detectChanges();
  });

  it('should initialize with default generate_image mode', () => {
    expect(component).toBeTruthy();
    expect(component.localConfig.type).toBe('image');

    const promptInput = component.localConfig.inputs.find(
      i => i.name === 'prompt',
    );
    const inputImages = component.localConfig.inputs.find(
      i => i.name === 'input_images',
    );
    const inputImage = component.localConfig.inputs.find(
      i => i.name === 'input_image',
    );

    expect(promptInput?.hidden).toBeFalse();
    expect(promptInput?.required).toBeTrue();
    expect(inputImages?.hidden).toBeTrue();
    expect(inputImage?.hidden).toBeTrue();

    const modelSetting = component.localConfig.settings.find(
      s => s.name === 'model',
    );
    const upscaleFactorSetting = component.localConfig.settings.find(
      s => s.name === 'upscale_factor',
    );
    expect(modelSetting?.hidden).toBeFalse();
    expect(upscaleFactorSetting?.hidden).toBeTrue();
  });

  it('should dynamically switch to edit_image mode', () => {
    component.stepForm.get('settings.mode')?.setValue('edit_image');

    const promptInput = component.localConfig.inputs.find(
      i => i.name === 'prompt',
    );
    const inputImages = component.localConfig.inputs.find(
      i => i.name === 'input_images',
    );
    const inputImage = component.localConfig.inputs.find(
      i => i.name === 'input_image',
    );

    expect(promptInput?.hidden).toBeFalse();
    expect(inputImages?.hidden).toBeFalse();
    expect(inputImages?.required).toBeTrue();
    expect(inputImage?.hidden).toBeTrue();
  });

  it('should dynamically switch to upscale_image mode and hide prompt', () => {
    component.stepForm.get('settings.mode')?.setValue('upscale_image');

    const promptInput = component.localConfig.inputs.find(
      i => i.name === 'prompt',
    );
    const inputImage = component.localConfig.inputs.find(
      i => i.name === 'input_image',
    );
    const upscaleFactorSetting = component.localConfig.settings.find(
      s => s.name === 'upscale_factor',
    );
    const modelSetting = component.localConfig.settings.find(
      s => s.name === 'model',
    );

    expect(promptInput?.hidden).toBeTrue();
    expect(inputImage?.hidden).toBeFalse();
    expect(inputImage?.required).toBeTrue();
    expect(upscaleFactorSetting?.hidden).toBeFalse();
    expect(modelSetting?.hidden).toBeTrue();
  });

  it('should dynamically switch to virtual_try_on mode', () => {
    component.stepForm.get('settings.mode')?.setValue('virtual_try_on');

    const modelImage = component.localConfig.inputs.find(
      i => i.name === 'model_image',
    );
    const topImage = component.localConfig.inputs.find(
      i => i.name === 'top_image',
    );
    const promptInput = component.localConfig.inputs.find(
      i => i.name === 'prompt',
    );

    expect(modelImage?.hidden).toBeFalse();
    expect(modelImage?.required).toBeTrue();
    expect(topImage?.hidden).toBeFalse();
    expect(topImage?.required).toBeFalse();
    expect(promptInput?.hidden).toBeTrue();
  });

  it('should return mode setting from getModeSetting', () => {
    const modeSetting = component.getModeSetting();
    expect(modeSetting).toBeDefined();
    expect(modeSetting?.name).toBe('mode');
    expect(modeSetting?.options?.length).toBe(4);
  });
});
