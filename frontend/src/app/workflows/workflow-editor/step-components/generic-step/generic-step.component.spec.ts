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
import {
  FormBuilder,
  FormGroup,
  FormsModule,
  ReactiveFormsModule,
} from '@angular/forms';
import {MatCheckboxModule} from '@angular/material/checkbox';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';
import {MatInputModule} from '@angular/material/input';
import {MatRadioModule} from '@angular/material/radio';
import {MatSelectModule} from '@angular/material/select';
import {MatSliderModule} from '@angular/material/slider';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {GENERATE_TEXT_STEP_CONFIG} from '../step-configs/generate-text-step.config';
import {GENERATE_VIDEO_STEP_CONFIG} from '../step-configs/generate-video-step.config';
import {IMAGE_STEP_CONFIG} from '../step-configs/image-step.config';
import {StepInput} from './step.model';
import {StudioSliderComponent} from '../../../../common/components/studio-slider/studio-slider.component';
import {WorkflowStatusPipe} from '../../../workflow-status.pipe';
import {GenericStepComponent} from './generic-step.component';

describe('GenericStepComponent - Image Node Dynamic Mode Selection', () => {
  let component: GenericStepComponent;
  let fixture: ComponentFixture<GenericStepComponent>;
  let fb: FormBuilder;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [GenericStepComponent, StudioSliderComponent],
      imports: [
        FormsModule,
        ReactiveFormsModule,
        MatFormFieldModule,
        MatInputModule,
        MatSelectModule,
        MatCheckboxModule,
        MatRadioModule,
        MatSliderModule,
        MatIconModule,
        NoopAnimationsModule,
        WorkflowStatusPipe,
      ],
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
        resolution: ['1K'],
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
    fixture.detectChanges();

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

    const baseInputImages = component
      .getBaseInputs()
      .find(i => i.name === 'input_images');
    expect(baseInputImages?.hidden).toBeFalse();
    const portEl = fixture.nativeElement.querySelector(
      '[data-port-name="input_images"]',
    );
    expect(portEl).not.toBeNull();
  });

  it('should dynamically switch to upscale_image mode and hide prompt', () => {
    component.stepForm.get('settings.mode')?.setValue('upscale_image');
    fixture.detectChanges();

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

    const baseInputImage = component
      .getBaseInputs()
      .find(i => i.name === 'input_image');
    expect(baseInputImage?.hidden).toBeFalse();
    const portEl = fixture.nativeElement.querySelector(
      '[data-port-name="input_image"]',
    );
    expect(portEl).not.toBeNull();
  });

  it('should dynamically switch to virtual_try_on mode', () => {
    component.stepForm.get('settings.mode')?.setValue('virtual_try_on');
    fixture.detectChanges();

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

    const baseModelImage = component
      .getBaseInputs()
      .find(i => i.name === 'model_image');
    expect(baseModelImage?.hidden).toBeFalse();
    const portEl = fixture.nativeElement.querySelector(
      '[data-port-name="model_image"]',
    );
    expect(portEl).not.toBeNull();
  });

  it('should return mode setting from getModeSetting', () => {
    const modeSetting = component.getModeSetting();
    expect(modeSetting).toBeDefined();
    expect(modeSetting?.name).toBe('mode');
    expect(modeSetting?.options?.length).toBe(4);
  });

  it('should preset mode to edit_image for legacy edit_image step without explicit mode', () => {
    const editStepForm = fb.group({
      stepId: ['legacy_edit_1'],
      type: ['edit_image'],
      status: ['idle'],
      inputs: fb.group({
        prompt: ['Modify picture'],
        input_images: [[1]],
      }),
      settings: fb.group({
        model: ['gemini-3.1-flash-image'],
      }),
      outputs: fb.group({}),
    });

    component.stepForm = editStepForm;
    component.config = IMAGE_STEP_CONFIG;
    component.ngOnChanges({
      stepForm: {
        currentValue: editStepForm,
        previousValue: null,
        firstChange: false,
        isFirstChange: () => false,
      },
    });

    expect((editStepForm.get('settings') as FormGroup).get('mode')?.value).toBe(
      'edit_image',
    );
  });

  it('should preset mode to upscale_image for legacy upscale_image step', () => {
    const upscaleStepForm = fb.group({
      stepId: ['legacy_upscale_1'],
      type: ['upscale_image'],
      status: ['idle'],
      inputs: fb.group({
        input_image: [1],
      }),
      settings: fb.group({
        upscale_factor: ['x2'],
      }),
      outputs: fb.group({}),
    });

    component.stepForm = upscaleStepForm;
    component.config = IMAGE_STEP_CONFIG;
    component.ngOnChanges({
      stepForm: {
        currentValue: upscaleStepForm,
        previousValue: null,
        firstChange: false,
        isFirstChange: () => false,
      },
    });

    expect(
      (upscaleStepForm.get('settings') as FormGroup).get('mode')?.value,
    ).toBe('upscale_image');
  });

  describe('Magnetic Snapping & Compatibility Methods', () => {
    it('should correctly identify magnetic target input', () => {
      component.activeMagneticPort = {
        stepId: 'image_step_1',
        inputName: 'prompt',
      };
      expect(component.isMagneticTarget('prompt')).toBeTrue();
      expect(component.isMagneticTarget('input_image')).toBeFalse();

      component.activeMagneticPort = {
        stepId: 'other_step',
        inputName: 'prompt',
      };
      expect(component.isMagneticTarget('prompt')).toBeFalse();
    });

    it('should evaluate compatibility with active drag source and block self-links and duplicates', () => {
      const textInput: StepInput = {
        name: 'prompt',
        label: 'Prompt',
        type: 'text',
        required: true,
      };
      const imageInput: StepInput = {
        name: 'input_image',
        label: 'Input Image',
        type: 'image',
        required: false,
      };

      component.dragSourcePort = {
        type: 'text',
        stepId: 'other_step',
        outputName: 'out_text',
      };

      expect(component.isCompatibleWithActiveDrag(textInput)).toBeTrue();
      expect(component.isIncompatibleWithActiveDrag(textInput)).toBeFalse();
      expect(component.isCompatibleWithActiveDrag(imageInput)).toBeFalse();
      expect(component.isIncompatibleWithActiveDrag(imageInput)).toBeTrue();

      // Block same-step (self) connection
      component.dragSourcePort = {
        type: 'text',
        stepId: 'image_step_1',
        outputName: 'out_text',
      };
      expect(component.isCompatibleWithActiveDrag(textInput)).toBeFalse();
      expect(component.isIncompatibleWithActiveDrag(textInput)).toBeTrue();

      // Block duplicate connection if already linked
      component.dragSourcePort = {
        type: 'text',
        stepId: 'other_step',
        outputName: 'out_text',
      };
      component.stepForm.get('inputs')?.get('prompt')?.setValue({
        step: 'other_step',
        output: 'out_text',
      });
      expect(component.isCompatibleWithActiveDrag(textInput)).toBeFalse();
      expect(component.isIncompatibleWithActiveDrag(textInput)).toBeTrue();

      // Null drag source should be incompatible
      component.dragSourcePort = null;
      expect(component.isCompatibleWithActiveDrag(textInput)).toBeFalse();
      expect(component.isIncompatibleWithActiveDrag(textInput)).toBeFalse();
    });

    it('should block connection to input port when port is full', () => {
      const inputImages: StepInput = {
        name: 'input_images',
        label: 'Input Images',
        type: 'image',
        required: false,
      };

      component.stepForm.get('settings.mode')?.setValue('edit_image');
      component.stepForm
        .get('settings.model')
        ?.setValue('gemini-2.5-flash-image'); // maxReferenceImages: 2
      component.dragSourcePort = {
        type: 'image',
        stepId: 'other_step',
        outputName: 'out_image_3',
      };

      // Initially empty: compatible
      component.stepForm.get('inputs.input_images')?.setValue(null);
      expect(component.isCompatibleWithActiveDrag(inputImages)).toBeTrue();
      expect(component.isIncompatibleWithActiveDrag(inputImages)).toBeFalse();

      // 1 image connected: still compatible (1 < 2)
      component.stepForm
        .get('inputs.input_images')
        ?.setValue([{step: 'other_step_1', output: 'out_image_1'}]);
      expect(component.isCompatibleWithActiveDrag(inputImages)).toBeTrue();

      // 2 images connected: FULL (2 >= 2) -> should be incompatible
      component.stepForm.get('inputs.input_images')?.setValue([
        {step: 'other_step_1', output: 'out_image_1'},
        {step: 'other_step_2', output: 'out_image_2'},
      ]);
      expect(component.isInputFull('input_images', 'image')).toBeTrue();
      expect(component.isCompatibleWithActiveDrag(inputImages)).toBeFalse();
      expect(component.isIncompatibleWithActiveDrag(inputImages)).toBeTrue();
    });

    it('should calculate getMaxMediaItems correctly for inputs', () => {
      component.stepForm
        .get('settings.model')
        ?.setValue('gemini-2.5-flash-image');
      expect(
        component.getMaxMediaItems({
          name: 'input_images',
          label: 'Images',
          type: 'image',
          required: false,
        }),
      ).toBe(2);
      expect(
        component.getMaxMediaItems({
          name: 'input_image',
          label: 'Image',
          type: 'image',
          required: false,
        }),
      ).toBe(1);
    });
  });

  describe('Video Node Duration Settings', () => {
    it('should initialize video node with duration_seconds setting and default value 8', () => {
      const videoStepForm = fb.group({
        stepId: ['video_step_1'],
        type: ['generate_video'],
        status: ['idle'],
        inputs: fb.group({
          prompt: ['A running horse'],
          input_images: [null],
          start_frame: [null],
          end_frame: [null],
        }),
        settings: fb.group({
          model: ['veo-3.1-generate-001'],
          input_mode: ['Text to Video'],
          aspect_ratio: ['16:9'],
          duration_seconds: [8],
          brand_guidelines: [false],
        }),
        outputs: fb.group({
          generated_video: [{type: 'video'}],
        }),
      });

      component.stepForm = videoStepForm;
      component.config = GENERATE_VIDEO_STEP_CONFIG;
      component.ngOnChanges({
        stepForm: {
          currentValue: videoStepForm,
          previousValue: null,
          firstChange: false,
          isFirstChange: () => false,
        },
      });

      const durationSetting = component.localConfig.settings.find(
        s => s.name === 'duration_seconds',
      );
      expect(durationSetting).toBeDefined();
      expect(durationSetting?.hidden).toBeFalse();
      expect(durationSetting?.options).toEqual([
        {value: 4, label: '4s'},
        {value: 6, label: '6s'},
        {value: 8, label: '8s'},
      ]);
      expect(videoStepForm.get('settings.duration_seconds')?.value).toBe(8);
    });

    it('should populate duration options dynamically when model changes', () => {
      const videoStepForm = fb.group({
        stepId: ['video_step_2'],
        type: ['generate_video'],
        status: ['idle'],
        inputs: fb.group({
          prompt: ['A spaceship landing'],
          input_images: [null],
          start_frame: [null],
          end_frame: [null],
        }),
        settings: fb.group({
          model: ['veo-3.1-fast-generate-001'],
          input_mode: ['Text to Video'],
          aspect_ratio: ['16:9'],
          duration_seconds: [6],
          brand_guidelines: [false],
        }),
        outputs: fb.group({
          generated_video: [{type: 'video'}],
        }),
      });

      component.stepForm = videoStepForm;
      component.config = GENERATE_VIDEO_STEP_CONFIG;
      component.ngOnInit();

      const durationSetting = component.localConfig.settings.find(
        s => s.name === 'duration_seconds',
      );
      expect(durationSetting?.options?.length).toBe(3);
      expect(videoStepForm.get('settings.duration_seconds')?.value).toBe(6);

      // Switch to another model
      videoStepForm
        .get('settings.model')
        ?.setValue('gemini-omni-flash-preview');
      expect(durationSetting?.options).toEqual([
        {value: 4, label: '4s'},
        {value: 6, label: '6s'},
        {value: 8, label: '8s'},
        {value: 10, label: '10s'},
      ]);
    });
  });

  describe('Video Node Ingredients Mode Reference Ports', () => {
    let videoStepForm: FormGroup;

    beforeEach(() => {
      videoStepForm = fb.group({
        stepId: ['video_step_ingredients'],
        type: ['generate-video'],
        status: ['idle'],
        inputs: fb.group({
          prompt: ['A dramatic movie scene'],
          input_images: [null],
          input_video: [null],
          input_audio: [null],
          start_frame: [null],
          end_frame: [null],
        }),
        settings: fb.group({
          model: ['veo-3.1-generate-001'],
          input_mode: ['Text to Video'],
          aspect_ratio: ['16:9'],
          duration_seconds: [8],
          brand_guidelines: [false],
        }),
        outputs: fb.group({
          generated_video: [{type: 'video'}],
        }),
      });

      component.stepForm = videoStepForm;
      component.config = GENERATE_VIDEO_STEP_CONFIG;
      component.ngOnInit();
    });

    it('should hide and disable input_video and input_audio when input_mode is Text to Video', () => {
      fixture.detectChanges();
      const inputVideo = component.localConfig.inputs.find(
        i => i.name === 'input_video',
      );
      const inputAudio = component.localConfig.inputs.find(
        i => i.name === 'input_audio',
      );
      const inputImages = component.localConfig.inputs.find(
        i => i.name === 'input_images',
      );

      expect(inputVideo?.hidden).toBeTrue();
      expect(inputAudio?.hidden).toBeTrue();
      expect(inputImages?.hidden).toBeTrue();
      expect(videoStepForm.get('inputs.input_video')?.disabled).toBeTrue();
      expect(videoStepForm.get('inputs.input_audio')?.disabled).toBeTrue();
      expect(videoStepForm.get('inputs.input_images')?.disabled).toBeTrue();

      expect(
        component.getBaseInputs().find(i => i.name === 'input_video')?.hidden,
      ).toBeTrue();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="input_video"]'),
      ).toBeNull();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="input_audio"]'),
      ).toBeNull();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="input_images"]'),
      ).toBeNull();
    });

    it('should show input_audio and input_video as disabled with message when video model is not Gemini Omni in Ingredients to Video mode', () => {
      // Model is 'veo-3.1-generate-001'
      videoStepForm
        .get('settings.input_mode')
        ?.setValue('Ingredients to Video');
      fixture.detectChanges();

      const inputVideo = component.localConfig.inputs.find(
        i => i.name === 'input_video',
      );
      const inputAudio = component.localConfig.inputs.find(
        i => i.name === 'input_audio',
      );
      const inputImages = component.localConfig.inputs.find(
        i => i.name === 'input_images',
      );

      expect(inputVideo?.hidden).toBeFalse();
      expect(inputAudio?.hidden).toBeFalse();
      expect(inputImages?.hidden).toBeFalse();
      expect(videoStepForm.get('inputs.input_images')?.enabled).toBeTrue();

      expect(
        component.getBaseInputs().find(i => i.name === 'input_video')?.hidden,
      ).toBeFalse();
      expect(
        component.getBaseInputs().find(i => i.name === 'input_audio')?.hidden,
      ).toBeFalse();
      expect(
        component.getBaseInputs().find(i => i.name === 'input_images')?.hidden,
      ).toBeFalse();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="input_video"]'),
      ).not.toBeNull();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="input_audio"]'),
      ).not.toBeNull();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="input_images"]'),
      ).not.toBeNull();

      // input_video should be disabled and show message
      expect(videoStepForm.get('inputs.input_video')?.disabled).toBeTrue();
      expect(component.getInputDisabledMessage('input_video')).toBe(
        'This model does not support Video as reference',
      );

      // input_audio should be disabled and show message
      expect(videoStepForm.get('inputs.input_audio')?.disabled).toBeTrue();
      expect(component.getInputDisabledMessage('input_audio')).toBe(
        'This model does not support Audio as reference',
      );

      // Dragging to disabled input_audio should not be compatible
      component.dragSourcePort = {
        stepId: 'other_step',
        outputName: 'generated_audio',
        type: 'audio',
      };
      expect(component.isCompatibleWithActiveDrag(inputAudio!)).toBeFalse();
      expect(component.isIncompatibleWithActiveDrag(inputAudio!)).toBeTrue();

      // Dragging to disabled input_video should not be compatible
      component.dragSourcePort = {
        stepId: 'other_step',
        outputName: 'generated_video',
        type: 'video',
      };
      expect(component.isCompatibleWithActiveDrag(inputVideo!)).toBeFalse();
      expect(component.isIncompatibleWithActiveDrag(inputVideo!)).toBeTrue();
    });

    it('should show and enable input_audio and input_video when model is Gemini Omni in Ingredients to Video mode', () => {
      videoStepForm
        .get('settings.model')
        ?.setValue('gemini-omni-flash-preview');
      videoStepForm
        .get('settings.input_mode')
        ?.setValue('Ingredients to Video');
      fixture.detectChanges();

      const inputAudio = component.localConfig.inputs.find(
        i => i.name === 'input_audio',
      );
      const inputVideo = component.localConfig.inputs.find(
        i => i.name === 'input_video',
      );

      expect(inputVideo?.hidden).toBeFalse();
      expect(videoStepForm.get('inputs.input_video')?.enabled).toBeTrue();
      expect(component.getInputDisabledMessage('input_video')).toBe('');
      expect(component.inputModes['input_video']).toBe('mixed');

      expect(inputAudio?.hidden).toBeFalse();
      expect(videoStepForm.get('inputs.input_audio')?.enabled).toBeTrue();
      expect(component.getInputDisabledMessage('input_audio')).toBe('');
      expect(component.inputModes['input_audio']).toBe('mixed');

      expect(
        fixture.nativeElement.querySelector('[data-port-name="input_video"]'),
      ).not.toBeNull();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="input_audio"]'),
      ).not.toBeNull();

      // Dragging to enabled input_audio should be compatible
      component.dragSourcePort = {
        stepId: 'other_step',
        outputName: 'generated_audio',
        type: 'audio',
      };
      expect(component.isCompatibleWithActiveDrag(inputAudio!)).toBeTrue();
      expect(component.isIncompatibleWithActiveDrag(inputAudio!)).toBeFalse();

      // Dragging to enabled input_video should be compatible
      component.dragSourcePort = {
        stepId: 'other_step',
        outputName: 'generated_video',
        type: 'video',
      };
      expect(component.isCompatibleWithActiveDrag(inputVideo!)).toBeTrue();
      expect(component.isIncompatibleWithActiveDrag(inputVideo!)).toBeFalse();
    });

    it('should hide and disable ingredient ports when switching to Frames to Video', () => {
      // First switch to Ingredients to Video
      videoStepForm
        .get('settings.input_mode')
        ?.setValue('Ingredients to Video');
      expect(
        component.localConfig.inputs.find(i => i.name === 'input_video')
          ?.hidden,
      ).toBeFalse();

      // Switch to Frames to Video
      videoStepForm.get('settings.input_mode')?.setValue('Frames to Video');
      fixture.detectChanges();

      const inputVideo = component.localConfig.inputs.find(
        i => i.name === 'input_video',
      );
      const inputAudio = component.localConfig.inputs.find(
        i => i.name === 'input_audio',
      );
      const inputImages = component.localConfig.inputs.find(
        i => i.name === 'input_images',
      );
      const startFrame = component.localConfig.inputs.find(
        i => i.name === 'start_frame',
      );
      const endFrame = component.localConfig.inputs.find(
        i => i.name === 'end_frame',
      );

      expect(inputVideo?.hidden).toBeTrue();
      expect(inputAudio?.hidden).toBeTrue();
      expect(inputImages?.hidden).toBeTrue();
      expect(videoStepForm.get('inputs.input_video')?.disabled).toBeTrue();
      expect(videoStepForm.get('inputs.input_audio')?.disabled).toBeTrue();

      expect(startFrame?.hidden).toBeFalse();
      expect(endFrame?.hidden).toBeFalse();
      expect(videoStepForm.get('inputs.start_frame')?.enabled).toBeTrue();
      expect(videoStepForm.get('inputs.end_frame')?.enabled).toBeTrue();

      expect(
        component.getBaseInputs().find(i => i.name === 'start_frame')?.hidden,
      ).toBeFalse();
      expect(
        component.getBaseInputs().find(i => i.name === 'end_frame')?.hidden,
      ).toBeFalse();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="start_frame"]'),
      ).not.toBeNull();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="end_frame"]'),
      ).not.toBeNull();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="input_video"]'),
      ).toBeNull();
      expect(
        fixture.nativeElement.querySelector('[data-port-name="input_audio"]'),
      ).toBeNull();
    });

    it('should emit portDrop when onInputPortMouseUp is called on an enabled input', () => {
      spyOn(component.portDrop, 'emit');
      const mockEvent = jasmine.createSpyObj('MouseEvent', ['stopPropagation']);

      component.onInputPortMouseUp(mockEvent, 'prompt');

      expect(mockEvent.stopPropagation).toHaveBeenCalled();
      expect(component.portDrop.emit).toHaveBeenCalledWith({
        stepId: 'video_step_ingredients',
        inputName: 'prompt',
      });
    });

    it('should not emit portDrop when onInputPortMouseUp is called on a disabled input', () => {
      spyOn(component.portDrop, 'emit');
      const mockEvent = jasmine.createSpyObj('MouseEvent', ['stopPropagation']);

      videoStepForm
        .get('settings.input_mode')
        ?.setValue('Ingredients to Video');
      // input_audio is disabled on non-Omni model
      expect(videoStepForm.get('inputs.input_audio')?.disabled).toBeTrue();

      component.onInputPortMouseUp(mockEvent, 'input_audio');

      expect(mockEvent.stopPropagation).toHaveBeenCalled();
      expect(component.portDrop.emit).not.toHaveBeenCalled();
    });

    it('should correctly report isInputDisabled status', () => {
      expect(component.isInputDisabled('prompt')).toBeFalse();

      videoStepForm
        .get('settings.input_mode')
        ?.setValue('Ingredients to Video');
      // input_audio is disabled on non-Omni model
      expect(component.isInputDisabled('input_audio')).toBeTrue();
      expect(component.isInputDisabled('input_video')).toBeTrue();
      expect(component.isInputDisabled('input_images')).toBeFalse();
    });
  });

  describe('GenericStepComponent - Generate Text Node Dynamic Variables', () => {
    let component: GenericStepComponent;
    let fixture: ComponentFixture<GenericStepComponent>;
    let fb: FormBuilder;
    let textStepForm: FormGroup;

    beforeEach(async () => {
      fb = TestBed.inject(FormBuilder);
      fixture = TestBed.createComponent(GenericStepComponent);
      component = fixture.componentInstance;

      textStepForm = fb.group({
        stepId: ['text_step_1'],
        type: ['generate-text'],
        status: ['idle'],
        inputs: fb.group({
          prompt: [''],
          input_images: [null],
          input_videos: [null],
        }),
        settings: fb.group({
          model: ['gemini-3-flash-preview'],
          temperature: [0.7],
        }),
        outputs: fb.group({
          generated_text: [{type: 'text'}],
        }),
      });

      component.stepForm = textStepForm;
      component.config = GENERATE_TEXT_STEP_CONFIG;
      component.stepIndex = 0;
      fixture.detectChanges();
    });

    it('should initialize without dynamic inputs when prompt is empty', () => {
      expect(component.localConfig.type).toBe('generate-text');
      expect(component.getBaseInputs().length).toBe(3);
      expect(component.getBaseInputs().map(i => i.name)).toEqual([
        'prompt',
        'input_images',
        'input_videos',
      ]);
      expect(component.getVariableInputs().length).toBe(0);
    });

    it('should return empty array from getBaseInputs and getVariableInputs when localConfig is undefined', () => {
      component.localConfig = undefined as any;
      expect(component.getBaseInputs()).toEqual([]);
      expect(component.getVariableInputs()).toEqual([]);
    });

    it('should extract variables from prompt and create dynamic text ports in Prompt variables section', () => {
      textStepForm
        .get('inputs.prompt')
        ?.setValue(
          'Create an image for a <animal> using a <article_of_clothing>',
        );
      component.onInputFieldBlur('prompt');

      expect(component.getVariableInputs().length).toBe(2);
      const inputNames = component.getVariableInputs().map(i => i.name);
      expect(inputNames).toContain('animal');
      expect(inputNames).toContain('article_of_clothing');

      const inputsGroup = textStepForm.get('inputs') as FormGroup;
      expect(inputsGroup.contains('animal')).toBeTrue();
      expect(inputsGroup.contains('article_of_clothing')).toBeTrue();
      expect(component.inputModes['animal']).toBe('fixed');
      expect(component.inputModes['article_of_clothing']).toBe('fixed');
      expect(component.isVariableUsedInPrompt('animal')).toBeTrue();
      expect(
        component.isVariableUsedInPrompt('article_of_clothing'),
      ).toBeTrue();
    });

    it('should deduplicate repeated variable names in prompt', () => {
      textStepForm
        .get('inputs.prompt')
        ?.setValue('The <animal> looked at another <animal>');
      component.onInputFieldBlur('prompt');

      const dynamicInputs = component
        .getVariableInputs()
        .filter(i => i.name === 'animal');
      expect(dynamicInputs.length).toBe(1);
    });

    it('should ignore variable creation when name is empty or undefined', () => {
      component.addVariable();
      expect(component.getVariableInputs().length).toBe(0);

      component.addVariable('   ');
      expect(component.getVariableInputs().length).toBe(0);
    });

    it('should add variable with custom valid name', () => {
      component.addVariable('custom_var');

      expect(component.getVariableInputs().length).toBe(1);
      expect(component.getVariableInputs()[0].name).toBe('custom_var');

      const inputsGroup = textStepForm.get('inputs') as FormGroup;
      expect(inputsGroup.contains('custom_var')).toBeTrue();
    });

    it('should prevent variable creation when variable name matches a real base port', () => {
      // Trying to add base port names as dynamic variables must be blocked (case-insensitively)
      component.addVariable('prompt');
      component.addVariable('PROMPT');
      component.addVariable('input_images');
      component.addVariable('Input_Images');
      component.addVariable('input_videos');
      component.addVariable('INPUT_VIDEOS');

      expect(component.getVariableInputs().length).toBe(0);
      expect(component.isBasePortCollision('prompt')).toBeTrue();
      expect(component.isBasePortCollision('PROMPT')).toBeTrue();
      expect(component.isBasePortCollision('Prompt')).toBeTrue();
      expect(component.isBasePortCollision('input_images')).toBeTrue();
      expect(component.isBasePortCollision('Input_Images')).toBeTrue();
      expect(component.isBasePortCollision('input_videos')).toBeTrue();
      expect(component.isBasePortCollision('INPUT_VIDEOS')).toBeTrue();
      expect(component.isBasePortCollision('my_custom_var')).toBeFalse();

      // Also when typing in prompt with base port name (any casing), it should not create dynamic port
      textStepForm
        .get('inputs.prompt')
        ?.setValue('Test <prompt> and <PROMPT> collision');
      component.onInputFieldBlur('prompt');
      expect(component.getVariableInputs().length).toBe(0);
    });

    it('should prevent variable creation with invalid syntax', () => {
      component.addVariable('123invalid');
      component.addVariable('bad-var-name!');
      expect(component.getVariableInputs().length).toBe(0);
    });

    it('should add custom variable when setting newVariableName and calling addCustomVariable()', () => {
      component.newVariableName = 'custom_theme';
      expect(component.isValidNewVariableName()).toBeTrue();

      component.addCustomVariable();
      expect(component.newVariableName).toBe('');
      expect(component.getVariableInputs().length).toBe(1);
      expect(component.getVariableInputs()[0].name).toBe('custom_theme');

      const inputsGroup = textStepForm.get('inputs') as FormGroup;
      expect(inputsGroup.contains('custom_theme')).toBeTrue();
    });

    it('should reject invalid custom variable names via isValidNewVariableName', () => {
      component.newVariableName = '   ';
      expect(component.isValidNewVariableName()).toBeFalse();

      component.newVariableName = '123_invalid';
      expect(component.isValidNewVariableName()).toBeFalse();

      component.newVariableName = 'prompt'; // Collision with base input
      expect(component.isValidNewVariableName()).toBeFalse();

      component.newVariableName = 'PROMPT'; // Case-insensitive collision with base input
      expect(component.isValidNewVariableName()).toBeFalse();

      component.newVariableName = 'input_images'; // Collision with base input
      expect(component.isValidNewVariableName()).toBeFalse();

      component.newVariableName = 'Input_Images'; // Case-insensitive collision with base input
      expect(component.isValidNewVariableName()).toBeFalse();

      component.newVariableName = 'valid_var';
      expect(component.isValidNewVariableName()).toBeTrue();
      component.addCustomVariable();

      // Trying to add duplicate (exact or different casing)
      component.newVariableName = 'valid_var';
      expect(component.isValidNewVariableName()).toBeFalse();
      component.newVariableName = 'VALID_VAR';
      expect(component.isValidNewVariableName()).toBeFalse();
      component.newVariableName = 'Valid_Var';
      expect(component.isValidNewVariableName()).toBeFalse();
    });

    it('should handle prompt variables case-insensitively and avoid duplicates', () => {
      // Prompt with multiple casing variations of the same variable
      textStepForm
        .get('inputs.prompt')
        ?.setValue('The <Animal> saw another <animal> and <ANIMAL>');
      component.onInputFieldBlur('prompt');

      expect(component.getVariableInputs().length).toBe(1);
      expect(component.isVariableUsedInPrompt('animal')).toBeTrue();
      expect(component.isVariableUsedInPrompt('Animal')).toBeTrue();
      expect(component.isVariableUsedInPrompt('ANIMAL')).toBeTrue();

      // Trying to add duplicate with different case
      component.addVariable('ANIMAL');
      expect(component.getVariableInputs().length).toBe(1);
    });

    it('should show Prompt variables section as disabled when prompt is in linked mode', () => {
      component.addVariable('custom_var');
      expect(component.inputModes['prompt']).toBe('fixed');
      fixture.detectChanges();

      let promptVarsElement =
        fixture.nativeElement.querySelector('.prompt-variables');
      expect(promptVarsElement).not.toBeNull();
      expect(
        promptVarsElement.classList.contains('disabled-section'),
      ).toBeFalse();
      expect(component.isInputDisabled('custom_var')).toBeFalse();

      // Switch prompt mode to 'linked'
      component.toggleInputMode('prompt', 'linked');
      fixture.detectChanges();
      promptVarsElement =
        fixture.nativeElement.querySelector('.prompt-variables');
      // Section is STILL visible, but marked as disabled-section
      expect(promptVarsElement).not.toBeNull();
      expect(
        promptVarsElement.classList.contains('disabled-section'),
      ).toBeTrue();
      expect(component.isInputDisabled('custom_var')).toBeTrue();
      expect(component.getInputDisabledMessage('custom_var')).toBe(
        'Prompt is linked - variables inactive',
      );

      // Switch back to 'fixed'
      component.toggleInputMode('prompt', 'fixed');
      fixture.detectChanges();
      promptVarsElement =
        fixture.nativeElement.querySelector('.prompt-variables');
      expect(
        promptVarsElement.classList.contains('disabled-section'),
      ).toBeFalse();
      expect(component.isInputDisabled('custom_var')).toBeFalse();
    });

    it('should append variable placeholder to prompt when appendToPrompt() is called', () => {
      textStepForm.get('inputs.prompt')?.setValue('Generate a landscape with');
      component.addVariable('weather');
      expect(component.isVariableUsedInPrompt('weather')).toBeFalse();

      component.appendToPrompt('weather');
      expect(textStepForm.get('inputs.prompt')?.value).toBe(
        'Generate a landscape with <weather>',
      );
      expect(component.isVariableUsedInPrompt('weather')).toBeTrue();
    });

    it('should show warning message and allow variable removal via removeVariable', () => {
      component.addVariable('hero_name');
      expect(component.isVariableUsedInPrompt('hero_name')).toBeFalse();

      // When user adds <hero_name> to prompt
      textStepForm
        .get('inputs.prompt')
        ?.setValue('The brave <hero_name> saved the day');
      expect(component.isVariableUsedInPrompt('hero_name')).toBeTrue();

      // When user removes from prompt
      textStepForm
        .get('inputs.prompt')
        ?.setValue('The brave hero saved the day');
      expect(component.isVariableUsedInPrompt('hero_name')).toBeFalse();

      // User removes variable
      component.removeVariable('hero_name');
      expect(component.getVariableInputs().length).toBe(0);
      const inputsGroup = textStepForm.get('inputs') as FormGroup;
      expect(inputsGroup.contains('hero_name')).toBeFalse();
    });

    it('should not allow removing base input ports via removeVariable', () => {
      component.removeVariable('prompt');
      expect(component.getBaseInputs().map(i => i.name)).toContain('prompt');
      const inputsGroup = textStepForm.get('inputs') as FormGroup;
      expect(inputsGroup.contains('prompt')).toBeTrue();
    });

    it('should restore dynamic variables on initialization when loading existing form state', () => {
      const existingForm = fb.group({
        stepId: ['text_step_existing'],
        type: ['generate-text'],
        status: ['idle'],
        inputs: fb.group({
          prompt: ['Write a story about <protagonist> in <setting>'],
          input_images: [null],
          input_videos: [null],
          protagonist: ['Arthur'],
          setting: [{step: 'step_setting', output: 'generated_text'}],
          orphan_var: ['value'],
        }),
        settings: fb.group({
          model: ['gemini-3-flash-preview'],
          temperature: [0.7],
        }),
        outputs: fb.group({
          generated_text: [{type: 'text'}],
        }),
      });

      const newFixture = TestBed.createComponent(GenericStepComponent);
      const newComponent = newFixture.componentInstance;
      newComponent.stepForm = existingForm;
      newComponent.config = GENERATE_TEXT_STEP_CONFIG;
      newComponent.stepIndex = 0;
      newFixture.detectChanges();

      expect(newComponent.getBaseInputs().length).toBe(3);
      expect(newComponent.getVariableInputs().length).toBe(3);
      const varNames = newComponent.getVariableInputs().map(i => i.name);
      expect(varNames).toContain('protagonist');
      expect(varNames).toContain('setting');
      expect(varNames).toContain('orphan_var');
      expect(newComponent.inputModes['protagonist']).toBe('fixed');
      expect(newComponent.inputModes['setting']).toBe('linked');
      expect(newComponent.isVariableUsedInPrompt('protagonist')).toBeTrue();
      expect(newComponent.isVariableUsedInPrompt('setting')).toBeTrue();
      expect(newComponent.isVariableUsedInPrompt('orphan_var')).toBeFalse();
    });

    describe('initializeInputMode', () => {
      it('should set inputModes to linked or fixed via initializeInputMode', () => {
        const inputs = component.stepForm.get('inputs') as FormGroup;
        inputs.addControl('var_fixed', fb.control('hello'));
        inputs.addControl(
          'var_linked',
          fb.control({step: 'step_1', output: 'text'}),
        );

        (
          component as unknown as {
            initializeInputMode: (name: string, inputs: FormGroup) => void;
          }
        ).initializeInputMode('var_fixed', inputs);
        (
          component as unknown as {
            initializeInputMode: (name: string, inputs: FormGroup) => void;
          }
        ).initializeInputMode('var_linked', inputs);

        expect(component.inputModes['var_fixed']).toBe('fixed');
        expect(component.inputModes['var_linked']).toBe('linked');
      });
    });
  });

  describe('Image node resolution and aspect ratio features', () => {
    it('should include auto in aspect ratio options, disabled in generate_image and enabled in edit_image mode', () => {
      const aspectRatioSetting = component.localConfig.settings.find(
        s => s.name === 'aspect_ratio',
      );
      expect(aspectRatioSetting).toBeDefined();
      const autoOption = aspectRatioSetting?.options?.find(
        o => o.value === 'auto',
      );
      expect(autoOption).toBeDefined();
      expect(autoOption?.label).toBe('Auto (Dynamic)');

      // Default mode is generate_image -> auto must be disabled
      expect(autoOption?.disabled).toBeTrue();

      // Switch to edit_image ("Edit Image / Inpainting") -> auto must be enabled
      component.stepForm.get('settings.mode')?.setValue('edit_image');
      fixture.detectChanges();
      expect(autoOption?.disabled).toBeFalse();

      // Set aspect_ratio to auto in edit_image mode
      component.stepForm.get('settings.aspect_ratio')?.setValue('auto');
      expect(component.stepForm.get('settings.aspect_ratio')?.value).toBe(
        'auto',
      );

      // Switch back to generate_image -> auto must become disabled and reset to 1:1
      component.stepForm.get('settings.mode')?.setValue('generate_image');
      fixture.detectChanges();
      expect(autoOption?.disabled).toBeTrue();
      expect(component.stepForm.get('settings.aspect_ratio')?.value).toBe(
        '1:1',
      );
    });

    it('should have resolution setting visible in generate_image and edit_image modes, and hidden in upscale/vto', () => {
      const resolutionSetting = component.localConfig.settings.find(
        s => s.name === 'resolution',
      );
      expect(resolutionSetting).toBeDefined();

      // Default mode is generate_image
      expect(resolutionSetting?.hidden).toBeFalse();

      // Switch to edit_image
      component.stepForm.get('settings.mode')?.setValue('edit_image');
      expect(resolutionSetting?.hidden).toBeFalse();

      // Switch to upscale_image
      component.stepForm.get('settings.mode')?.setValue('upscale_image');
      expect(resolutionSetting?.hidden).toBeTrue();

      // Switch to virtual_try_on
      component.stepForm.get('settings.mode')?.setValue('virtual_try_on');
      expect(resolutionSetting?.hidden).toBeTrue();
    });

    it('should update resolution options based on model capabilities and reset if invalid', () => {
      // Default model is gemini-3.1-flash-image which supports 1K, 2K, 4K
      const resolutionSetting = component.localConfig.settings.find(
        s => s.name === 'resolution',
      );
      expect(resolutionSetting?.options?.map(o => o.value)).toEqual([
        '1K',
        '2K',
        '4K',
      ]);

      // Set resolution to 4K
      component.stepForm.get('settings.resolution')?.setValue('4K');
      expect(component.stepForm.get('settings.resolution')?.value).toBe('4K');

      // Change model to gemini-3.1-flash-lite-image which only supports 1K
      component.stepForm
        .get('settings.model')
        ?.setValue('gemini-3.1-flash-lite-image');

      expect(resolutionSetting?.options?.map(o => o.value)).toEqual(['1K']);
      // Should automatically reset to first option (1K) since 4K is not supported
      expect(component.stepForm.get('settings.resolution')?.value).toBe('1K');
    });
  });
});
