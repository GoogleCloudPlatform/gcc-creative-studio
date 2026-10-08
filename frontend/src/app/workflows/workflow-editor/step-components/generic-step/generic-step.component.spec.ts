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
  AbstractControl,
  FormBuilder,
  FormControl,
  FormGroup,
  FormsModule,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import {By} from '@angular/platform-browser';
import {MatCheckboxModule} from '@angular/material/checkbox';
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatIconModule} from '@angular/material/icon';
import {MatInputModule} from '@angular/material/input';
import {MatRadioModule} from '@angular/material/radio';
import {MatSelect, MatSelectModule} from '@angular/material/select';
import {MatSliderModule} from '@angular/material/slider';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {GENERATE_TEXT_STEP_CONFIG} from '../step-configs/generate-text-step.config';
import {GENERATE_VIDEO_STEP_CONFIG} from '../step-configs/generate-video-step.config';
import {IMAGE_STEP_CONFIG} from '../step-configs/image-step.config';
import {LoopItemType, NodeTypes} from '../../../workflow.models';
import {StepInput} from './step.model';
import {StudioSliderComponent} from '../../../../common/components/studio-slider/studio-slider.component';
import {WorkflowStatusPipe} from '../../../workflow-status.pipe';
import {GenericStepComponent} from './generic-step.component';
import {NEVER, Subject, of, throwError} from 'rxjs';
import {FolderService} from '../../../../common/services/folder.service';
import {WorkspaceStateService} from '../../../../services/workspace/workspace-state.service';
import {
  FolderSelectionResult,
  FolderTreeNode,
} from '../../../../common/models/folder.model';
import {
  ImageSelectorComponent,
  ImageSelectorDialogData,
} from '../../../../common/components/image-selector/image-selector.component';
import {
  LOOP_FOLDER_CHOOSE_VALUE,
  LOOP_FOLDER_MISSING_TOOLTIP,
  LOOP_ITEM_TYPE_MIME_MAP,
  LOOP_STEP_CONFIG,
  MAX_LOOP_ITEMS,
  loopFolderIdValidator,
  loopItemsTextValidator,
  loopLinkedItemsRequiredValidator,
  toLoopFolderId,
} from '../step-configs/loop-step.config';

type FolderDialogRef = MatDialogRef<
  ImageSelectorComponent,
  FolderSelectionResult | null | undefined
>;

describe('GenericStepComponent - Image Node Dynamic Mode Selection', () => {
  let component: GenericStepComponent;
  let fixture: ComponentFixture<GenericStepComponent>;
  let fb: FormBuilder;
  let dialogSpy: jasmine.SpyObj<MatDialog>;

  beforeEach(async () => {
    dialogSpy = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
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
      providers: [
        FormBuilder,
        {provide: MatDialog, useValue: dialogSpy},
        {
          provide: FolderService,
          useValue: jasmine.createSpyObj<FolderService>('FolderService', {
            getFolderTree: of([
              {
                id: 7,
                name: 'Campaign',
                children: [{id: 8, name: 'Shots', children: []}],
              },
            ]),
          }),
        },
        {
          provide: WorkspaceStateService,
          useValue: jasmine.createSpyObj<WorkspaceStateService>(
            'WorkspaceStateService',
            {getActiveWorkspaceId: 1},
          ),
        },
      ],
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
      collapsed: [false],
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
        ?.setValue('gemini-omni-1.1-flash-preview');
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
        type: [NodeTypes.GENERATE_VIDEO],
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
        ?.setValue('gemini-omni-1.1-flash-preview');
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
        type: [NodeTypes.GENERATE_TEXT],
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
      expect(component.localConfig.type).toBe(NodeTypes.GENERATE_TEXT);
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
        type: [NodeTypes.GENERATE_TEXT],
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

  describe('Collapsed State', () => {
    it('should initialize collapsed control on stepForm and set isCollapsed to false', () => {
      expect(component.stepForm.contains('collapsed')).toBeTrue();
      expect(component.stepForm.get('collapsed')?.value).toBeFalse();
      expect(component.isCollapsed).toBeFalse();
    });

    it('should update isCollapsed when collapsed form control value changes', () => {
      component.stepForm.get('collapsed')?.setValue(true);
      expect(component.isCollapsed).toBeTrue();

      component.stepForm.get('collapsed')?.setValue(false);
      expect(component.isCollapsed).toBeFalse();
    });

    it('should toggle collapse, mark form dirty, stop event propagation, and emit collapseChange', () => {
      const event = new MouseEvent('click');
      spyOn(event, 'stopPropagation');
      spyOn(component.collapseChange, 'emit');

      component.toggleCollapse(event);

      expect(event.stopPropagation).toHaveBeenCalled();
      expect(component.isCollapsed).toBeTrue();
      expect(component.stepForm.get('collapsed')?.value).toBeTrue();
      expect(component.stepForm.get('collapsed')?.dirty).toBeTrue();
      expect(component.stepForm.dirty).toBeTrue();
      expect(component.collapseChange.emit).toHaveBeenCalledWith(true);

      component.toggleCollapse();
      expect(component.isCollapsed).toBeFalse();
      expect(component.stepForm.get('collapsed')?.value).toBeFalse();
      expect(component.collapseChange.emit).toHaveBeenCalledWith(false);
    });
  });

  describe('Loop Node', () => {
    const query = (selector: string): HTMLElement | null =>
      fixture.nativeElement.querySelector(selector);

    function initLoopStep(
      mode: string,
      itemType = 'image',
      folderId: number | null = null,
    ): FormGroup {
      const loopForm = fb.group({
        stepId: ['loop_1'],
        type: [NodeTypes.LOOP],
        status: ['idle'],
        collapsed: [false],
        inputs: fb.group({
          items_text: [''],
          loop_ending: [null],
        }),
        settings: fb.group({
          mode: [mode],
          folder_id: [folderId],
          item_type: [itemType],
        }),
        outputs: fb.group({
          current_item: [{type: itemType}],
        }),
      });
      component.stepForm = loopForm;
      component.config = LOOP_STEP_CONFIG;
      component.ngOnChanges({
        stepForm: {
          currentValue: loopForm,
          previousValue: null,
          firstChange: false,
          isFirstChange: () => false,
        },
      });
      fixture.detectChanges();
      return loopForm;
    }

    const findSetting = (name: string) =>
      component.localConfig.settings.find(s => s.name === name);
    const findInput = (name: string) =>
      component.localConfig.inputs.find(i => i.name === name);
    const currentItemType = () =>
      component.localConfig.outputs.find(o => o.name === 'current_item')?.type;

    it('shows folder settings and hides items_text in folder mode', () => {
      initLoopStep('folder', 'video');

      expect(findSetting('folder_id')?.hidden).toBeFalsy();
      expect(findSetting('item_type')?.hidden).toBeFalsy();
      expect(findInput('items_text')?.hidden).toBeTrue();
      expect(component.stepForm.get('inputs.items_text')?.disabled).toBeTrue();
      expect(currentItemType()).toBe('video');
    });

    it('switches to text_input mode with a text current_item port', () => {
      const loopForm = initLoopStep('folder');
      loopForm.get('settings.mode')?.setValue('text_input');

      expect(findSetting('folder_id')?.hidden).toBeTrue();
      expect(findSetting('item_type')?.hidden).toBeTrue();
      expect(findInput('items_text')?.hidden).toBeFalse();
      expect(findInput('items_text')?.required).toBeTrue();
      expect(component.stepForm.get('inputs.items_text')?.enabled).toBeTrue();
      expect(currentItemType()).toBe('text');
      expect(loopForm.get('outputs.current_item')?.value).toEqual({
        type: 'text',
      });
    });

    it('updates the current_item type when item_type changes', () => {
      const loopForm = initLoopStep('folder');
      loopForm.get('settings.item_type')?.setValue('audio');
      expect(currentItemType()).toBe('audio');
    });

    it('indexes workspace folders to resolve the saved folder name and path', () => {
      initLoopStep('folder', 'image', 8);
      expect(component.loopFolderIndex()?.get(7)).toEqual({
        name: 'Campaign',
        path: 'Campaign',
      });
      expect(component.loopFolderOption()).toEqual({
        value: 8,
        label: 'Shots',
        path: 'Campaign / Shots',
        isPlaceholder: false,
        isMissing: false,
      });
    });

    it('always shows the static max loops hint', () => {
      initLoopStep('folder');
      expect(query('#loop-capacity-hint-loop_1')?.textContent).toContain(
        `Max ${MAX_LOOP_ITEMS} loops`,
      );
    });

    it('marks loop_ending as a linked-only input', () => {
      initLoopStep('folder');
      expect(findInput('loop_ending')?.linkedOnly).toBeTrue();
      expect(component.inputModes['loop_ending']).toBe('linked');
    });

    describe('Linked Items mode', () => {
      const imageRef = {step: 'img_a', output: 'generated_image'};
      const linkedItemsControl = (): AbstractControl =>
        component.stepForm.get('inputs.linked_items') as AbstractControl;
      const itemsTextControl = (): AbstractControl =>
        component.stepForm.get('inputs.items_text') as AbstractControl;
      const folderIdControl = (): AbstractControl =>
        component.stepForm.get('settings.folder_id') as AbstractControl;

      it('shows item_type and the linked_items port, hides folder_id', () => {
        initLoopStep('linked_items', 'video');

        const linkedItemsInput = findInput('linked_items');
        expect(findSetting('folder_id')?.hidden).toBeTrue();
        expect(findSetting('item_type')?.hidden).toBeFalse();
        expect(findInput('items_text')?.hidden).toBeTrue();
        expect(linkedItemsInput?.hidden).toBeFalse();
        expect(linkedItemsInput?.required).toBeTrue();
        expect(linkedItemsInput?.type).toBe('video');
        expect(currentItemType()).toBe('video');
        expect(linkedItemsInput?.linkedOnly).toBeFalsy();
        if (linkedItemsInput) {
          expect(component.getMaxMediaItems(linkedItemsInput)).toBe(100);
        }
      });

      it('applies only the linked_items validator', () => {
        initLoopStep('linked_items');

        const linkedItems = linkedItemsControl();
        const folderId = folderIdControl();
        expect(linkedItems.enabled).toBeTrue();
        expect(linkedItems.hasError('linkedItemsRequired')).toBeTrue();
        expect(itemsTextControl().disabled).toBeTrue();
        expect(folderId.hasValidator(Validators.required)).toBeFalse();
        expect(folderId.valid).toBeTrue();

        linkedItems.setValue([imageRef]);
        expect(linkedItems.valid).toBeTrue();

        linkedItems.setValue([{sourceAssetId: 7, previewUrl: ''}]);
        expect(linkedItems.valid).toBeTrue();
      });

      it('renders the port with its E2E test id', () => {
        initLoopStep('linked_items');
        const port = query('[data-testid="loop-linked-items-port"]');
        expect(port?.getAttribute('data-port-name')).toBe('linked_items');
      });

      it('keeps the port type in sync with item_type', () => {
        const loopForm = initLoopStep('linked_items');
        loopForm.get('settings.item_type')?.setValue('audio');

        expect(findInput('linked_items')?.type).toBe('audio');
        expect(currentItemType()).toBe('audio');
      });

      it('uses the dynamic port type for drag compatibility', () => {
        const loopForm = initLoopStep('linked_items', 'image');
        component.dragSourcePort = {
          stepId: 'img_a',
          outputName: 'generated_image',
          type: 'image',
        };
        const linkedItemsInput = findInput('linked_items');
        expect(linkedItemsInput).toBeDefined();
        if (!linkedItemsInput) return;
        expect(
          component.isCompatibleWithActiveDrag(linkedItemsInput),
        ).toBeTrue();

        loopForm.get('settings.item_type')?.setValue('video');
        expect(
          component.isCompatibleWithActiveDrag(linkedItemsInput),
        ).toBeFalse();
      });

      it('applies the right validators when switching through every mode', () => {
        const loopForm = initLoopStep('linked_items');
        const modeControl = loopForm.get('settings.mode');

        modeControl?.setValue('text_input');
        const itemsText = itemsTextControl();
        expect(linkedItemsControl().disabled).toBeTrue();
        expect(findInput('linked_items')?.hidden).toBeTrue();
        expect(itemsText.enabled).toBeTrue();
        expect(itemsText.hasValidator(Validators.required)).toBeTrue();
        expect(itemsText.hasValidator(loopItemsTextValidator)).toBeTrue();
        itemsText.setValue(' , ');
        expect(itemsText.hasError('loopItemsTextEmpty')).toBeTrue();
        itemsText.setValue({step: 'txt_1', output: 'generated_text'});
        expect(itemsText.valid).toBeTrue();

        modeControl?.setValue('folder');
        const folderId = folderIdControl();
        expect(itemsTextControl().disabled).toBeTrue();
        expect(linkedItemsControl().disabled).toBeTrue();
        expect(folderId.hasValidator(Validators.required)).toBeTrue();
        expect(findSetting('folder_id')?.hidden).toBeFalse();

        modeControl?.setValue('linked_items');
        expect(linkedItemsControl().enabled).toBeTrue();
        expect(
          linkedItemsControl().hasValidator(loopLinkedItemsRequiredValidator),
        ).toBeTrue();
        expect(folderIdControl().hasValidator(Validators.required)).toBeFalse();
      });

      it('keeps every source input disabled on a read-only form', () => {
        const loopForm = fb.group({
          stepId: ['loop_1'],
          type: [NodeTypes.LOOP],
          status: ['idle'],
          collapsed: [false],
          inputs: fb.group({
            items_text: [''],
            linked_items: [[imageRef]],
            loop_ending: [null],
          }),
          settings: fb.group({
            mode: ['linked_items'],
            folder_id: [null],
            item_type: ['image'],
          }),
          outputs: fb.group({current_item: [{type: 'image'}]}),
        });
        loopForm.disable();
        component.stepForm = loopForm;
        component.config = LOOP_STEP_CONFIG;
        component.ngOnChanges({
          stepForm: {
            currentValue: loopForm,
            previousValue: null,
            firstChange: false,
            isFirstChange: () => false,
          },
        });

        expect(linkedItemsControl().disabled).toBeTrue();
        expect(itemsTextControl().disabled).toBeTrue();
        expect(linkedItemsControl().value).toEqual([imageRef]);
      });
    });

    describe('Media Gallery folder select', () => {
      const LOOP_TREE: FolderTreeNode[] = [
        {
          id: 1,
          name: 'Marketing',
          children: [
            {
              id: 2,
              name: 'Summer',
              children: [{id: 3, name: 'Week 1', children: []}],
            },
          ],
        },
        {id: 4, name: 'Archive', children: []},
      ];
      const SUMMER_RESULT: FolderSelectionResult = {
        folderId: 2,
        folderName: 'Summer',
        path: 'Marketing / Summer',
      };
      const NEW_FOLDER_RESULT: FolderSelectionResult = {
        folderId: 99,
        folderName: 'Fresh Shoot',
        path: 'Archive / Fresh Shoot',
      };

      let folderServiceSpy: jasmine.SpyObj<FolderService>;
      let afterClosed$: Subject<FolderSelectionResult | null | undefined>;

      beforeEach(() => {
        folderServiceSpy = TestBed.inject(
          FolderService,
        ) as jasmine.SpyObj<FolderService>;
        folderServiceSpy.getFolderTree.and.returnValue(of(LOOP_TREE));
        (dialogSpy.open as jasmine.Spy).and.callFake(() => {
          afterClosed$ = new Subject();
          const ref = {
            afterClosed: () => afterClosed$.asObservable(),
          } as unknown as FolderDialogRef;
          return ref;
        });
      });

      const folderControl = (): AbstractControl =>
        component.stepForm.get('settings.folder_id') as AbstractControl;
      const savedFolderId = (): unknown =>
        component.stepForm.getRawValue().settings.folder_id;
      const getFolderSelect = (): MatSelect =>
        fixture.debugElement
          .query(By.css('#loop-folder-select-loop_1'))
          .injector.get(MatSelect);
      const lastDialogData = (): ImageSelectorDialogData =>
        dialogSpy.open.calls.mostRecent().args[1]
          ?.data as ImageSelectorDialogData;
      const selectTriggerText = (): string =>
        query(
          '#loop-folder-select-loop_1 .mat-mdc-select-value-text',
        )?.textContent?.trim() ?? '';

      /** Renders, then lets MatSelect re-apply the control value to new options. */
      async function renderSelection(): Promise<void> {
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
      }

      async function chooseFolderOption(): Promise<void> {
        const select = getFolderSelect();
        select.open();
        fixture.detectChanges();
        await fixture.whenStable();
        select.options.last._selectViaInteraction();
        fixture.detectChanges();
      }

      it('renders exactly two options for folder_id', () => {
        initLoopStep('folder', 'image', 2);
        const options = getFolderSelect().options.toArray();
        expect(options.length).toBe(2);
        expect(options[0].value).toBe(2);
        expect(options[1].value).toBe(LOOP_FOLDER_CHOOSE_VALUE);
        expect(options[1].viewValue).toContain('Choose folder…');
      });

      it('keeps the generic options for the other select settings', () => {
        initLoopStep('folder');
        const itemTypeSelect = fixture.debugElement
          .queryAll(By.directive(MatSelect))
          .map(el => el.injector.get(MatSelect))
          .find(select => select.ngControl?.name === 'item_type');
        expect(itemTypeSelect?.options.map(o => o.value)).toEqual([
          'image',
          'video',
          'audio',
        ]);
      });

      it('shows a disabled placeholder option when no folder is selected', () => {
        initLoopStep('folder');
        const currentOption = getFolderSelect().options.first;
        expect(currentOption.value).toBeNull();
        expect(currentOption.disabled).toBeTrue();
        expect(currentOption.viewValue).toBe('No folder selected');
        expect(component.loopFolderOption().isPlaceholder).toBeTrue();
      });

      it('shows the resolved folder name with its full path as title', () => {
        initLoopStep('folder', 'image', 2);
        const currentOption = getFolderSelect().options.first;
        expect(currentOption.viewValue).toBe('Summer');
        expect(currentOption.disabled).toBeFalse();
        expect(currentOption._getHostElement().title).toBe(
          'Marketing / Summer',
        );
        expect(query('.loop-folder-field')?.title).toBe('Marketing / Summer');
        expect(query('.loop-folder-missing-icon')).toBeNull();
      });

      it('flags a saved folder missing from the tree with a warning icon', () => {
        initLoopStep('folder', 'image', 42);
        const option = component.loopFolderOption();
        expect(option.label).toBe('Folder #42');
        expect(option.isMissing).toBeTrue();
        expect(folderControl().value).toBe(42);
        expect(folderControl().valid).toBeTrue();
        expect(query('.loop-folder-missing-icon')).not.toBeNull();
        expect(component.loopFolderMissingTooltip).toBe(
          LOOP_FOLDER_MISSING_TOOLTIP,
        );
      });

      it('shows the folder id without a warning while the tree is loading', () => {
        folderServiceSpy.getFolderTree.and.returnValue(NEVER);
        initLoopStep('folder', 'image', 2);
        const option = component.loopFolderOption();
        expect(option.label).toBe('Folder #2');
        expect(option.isMissing).toBeFalse();
        expect(query('.loop-folder-missing-icon')).toBeNull();
      });

      it('shows the folder id without a warning when the tree fails to load', () => {
        spyOn(console, 'error');
        folderServiceSpy.getFolderTree.and.returnValue(
          throwError(() => new Error('boom')),
        );
        initLoopStep('folder', 'image', 2);
        const option = component.loopFolderOption();
        expect(option.label).toBe('Folder #2');
        expect(option.isMissing).toBeFalse();
      });

      it('reverts "Choose folder…" synchronously and opens the folder dialog', async () => {
        const loopForm = initLoopStep('folder', 'image', 2);
        const emitted: unknown[] = [];
        loopForm
          .get('settings.folder_id')
          ?.valueChanges.subscribe(value => emitted.push(value));

        await chooseFolderOption();

        expect(folderControl().value).toBe(2);
        expect(savedFolderId()).toBe(2);
        expect(emitted[emitted.length - 1]).toBe(2);
        expect(getFolderSelect().value).toBe(2);
        expect(dialogSpy.open).toHaveBeenCalledTimes(1);
      });

      it('never keeps the choose value while the dialog is open or after cancel', async () => {
        initLoopStep('folder');
        await chooseFolderOption();
        expect(savedFolderId()).not.toBe(LOOP_FOLDER_CHOOSE_VALUE);
        expect(savedFolderId()).toBeNull();

        afterClosed$.next(undefined);
        afterClosed$.complete();
        expect(savedFolderId()).toBeNull();
        expect(folderControl().pristine).toBeTrue();
      });

      it('keeps the control dirty when it was already dirty before choosing', async () => {
        initLoopStep('folder', 'image', 2);
        folderControl().markAsDirty();
        await chooseFolderOption();
        expect(folderControl().dirty).toBeTrue();
      });

      it('restores pristine when the control was pristine before choosing', () => {
        initLoopStep('folder', 'image', 2);
        component.onLoopFolderOpenedChange(true);
        folderControl().setValue(LOOP_FOLDER_CHOOSE_VALUE);
        folderControl().markAsDirty();
        component.onLoopFolderSelectionChange({
          source: getFolderSelect(),
          value: LOOP_FOLDER_CHOOSE_VALUE,
        });
        expect(folderControl().value).toBe(2);
        expect(folderControl().pristine).toBeTrue();
      });

      it('ignores regular option selections', () => {
        initLoopStep('folder', 'image', 2);
        component.onLoopFolderSelectionChange({
          source: getFolderSelect(),
          value: 2,
        });
        component.onLoopFolderOpenedChange(false);
        expect(dialogSpy.open).not.toHaveBeenCalled();
        expect(folderControl().value).toBe(2);
      });

      it('opens the dialog again when "Choose folder…" is picked twice', async () => {
        initLoopStep('folder', 'image', 2);
        await chooseFolderOption();
        afterClosed$.next(undefined);
        await chooseFolderOption();
        expect(dialogSpy.open).toHaveBeenCalledTimes(2);
        expect(folderControl().value).toBe(2);
      });

      it('opens the selector in folder mode at the current folder', async () => {
        initLoopStep('folder', 'image', 2);
        await chooseFolderOption();
        const [dialogComponent, dialogConfig] =
          dialogSpy.open.calls.mostRecent().args;
        expect(dialogComponent).toBe(ImageSelectorComponent);
        expect(dialogConfig?.panelClass).toBe('image-selector-dialog');
        expect(lastDialogData()).toEqual(
          jasmine.objectContaining({
            selectionTarget: 'folder',
            initialFolderId: 2,
            mimeType: 'image/*',
          }),
        );
      });

      (['image', 'video', 'audio'] as LoopItemType[]).forEach(itemType => {
        it(`previews ${itemType} items in the folder dialog`, () => {
          initLoopStep('folder', itemType);
          component.openLoopFolderSelector();
          expect(lastDialogData().mimeType).toBe(
            LOOP_ITEM_TYPE_MIME_MAP[itemType],
          );
          expect(lastDialogData().initialFolderId).toBeNull();
        });
      });

      it('stores the confirmed folder and shows its name and path', async () => {
        initLoopStep('folder');
        component.openLoopFolderSelector();
        afterClosed$.next(SUMMER_RESULT);
        await renderSelection();

        const control = folderControl();
        expect(control.value).toBe(2);
        expect(control.dirty).toBeTrue();
        expect(control.touched).toBeTrue();
        expect(component.loopFolderId()).toBe(2);
        const select = getFolderSelect();
        const currentOption = select.options.first;
        expect(currentOption.viewValue).toBe('Summer');
        expect(currentOption._getHostElement().title).toBe(
          'Marketing / Summer',
        );
        expect(select.selected).toBe(currentOption);
        expect(selectTriggerText()).toBe('Summer');
      });

      it('shows a confirmed folder in the closed select after another folder', async () => {
        initLoopStep('folder', 'image', 2);
        await renderSelection();
        expect(selectTriggerText()).toBe('Summer');

        component.openLoopFolderSelector();
        afterClosed$.next(NEW_FOLDER_RESULT);
        await renderSelection();

        expect(selectTriggerText()).toBe('Fresh Shoot');
      });

      it('shows a newly created folder that is not in the loaded tree', () => {
        initLoopStep('folder', 'image', 2);
        component.openLoopFolderSelector();
        afterClosed$.next(NEW_FOLDER_RESULT);
        fixture.detectChanges();

        expect(folderControl().value).toBe(99);
        expect(component.loopFolderOption()).toEqual({
          value: 99,
          label: 'Fresh Shoot',
          path: 'Archive / Fresh Shoot',
          isPlaceholder: false,
          isMissing: false,
        });
        expect(component.loopFolderIndex()?.get(2)?.name).toBe('Summer');
      });

      it('ignores an invalid dialog result', () => {
        initLoopStep('folder', 'image', 2);
        component.openLoopFolderSelector();
        afterClosed$.next({...SUMMER_RESULT, folderId: 0});
        expect(folderControl().value).toBe(2);
        expect(folderControl().pristine).toBeTrue();
      });

      it('does not open the dialog when the form is read-only', () => {
        const loopForm = initLoopStep('folder', 'image', 2);
        loopForm.disable();
        component.openLoopFolderSelector();
        expect(dialogSpy.open).not.toHaveBeenCalled();
      });

      it('requires a folder only in folder mode', () => {
        const loopForm = initLoopStep('folder');
        const control = folderControl();
        expect(control.hasError('required')).toBeTrue();
        expect(loopForm.invalid).toBeTrue();

        control.setValue(LOOP_FOLDER_CHOOSE_VALUE);
        expect(control.hasError('invalidLoopFolder')).toBeTrue();
        control.setValue(null);

        loopForm.get('settings.mode')?.setValue('text_input');
        expect(control.valid).toBeTrue();
        expect(loopForm.get('settings')?.valid).toBeTrue();

        loopForm.get('settings.mode')?.setValue('folder');
        expect(control.hasError('required')).toBeTrue();
      });

      it('updates the current folder option when folder_id is patched externally', async () => {
        const loopForm = initLoopStep('folder', 'image', 2);
        await renderSelection();
        loopForm.patchValue({settings: {folder_id: 4}});
        await renderSelection();

        expect(component.loopFolderId()).toBe(4);
        const select = getFolderSelect();
        const currentOption = select.options.first;
        expect(currentOption.value).toBe(4);
        expect(currentOption.viewValue).toBe('Archive');
        expect(select.selected).toBe(currentOption);
        expect(selectTriggerText()).toBe('Archive');

        loopForm.reset();
        fixture.detectChanges();
        expect(component.loopFolderId()).toBeNull();
        expect(component.loopFolderOption().isPlaceholder).toBeTrue();
      });

      it('keeps the current folder when the choose value is emitted', () => {
        initLoopStep('folder', 'image', 2);
        folderControl().setValue(LOOP_FOLDER_CHOOSE_VALUE);
        expect(component.loopFolderId()).toBe(2);
        expect(component.loopFolderOption().label).toBe('Summer');
      });

      it('stops following folder_id changes once destroyed', () => {
        const loopForm = initLoopStep('folder', 'image', 2);
        component.ngOnDestroy();
        loopForm.patchValue({settings: {folder_id: 4}});
        expect(component.loopFolderId()).toBe(2);
      });
    });
  });

  describe('Loop folder helpers', () => {
    it('accepts only positive integer folder ids', () => {
      expect(toLoopFolderId(5)).toBe(5);
      expect(toLoopFolderId(0)).toBeNull();
      expect(toLoopFolderId(-3)).toBeNull();
      expect(toLoopFolderId(1.5)).toBeNull();
      expect(toLoopFolderId(LOOP_FOLDER_CHOOSE_VALUE)).toBeNull();
      expect(toLoopFolderId('5')).toBeNull();
      expect(toLoopFolderId(null)).toBeNull();
    });

    it('rejects any non-null value that is not a folder id', () => {
      expect(loopFolderIdValidator(new FormControl(null))).toBeNull();
      expect(loopFolderIdValidator(new FormControl(12))).toBeNull();
      expect(
        loopFolderIdValidator(new FormControl(LOOP_FOLDER_CHOOSE_VALUE)),
      ).toEqual({invalidLoopFolder: true});
      expect(loopFolderIdValidator(new FormControl(-1))).toEqual({
        invalidLoopFolder: true,
      });
    });

    it('maps each loop item type to a media preview type', () => {
      expect(LOOP_ITEM_TYPE_MIME_MAP).toEqual({
        image: 'image/*',
        video: 'video/*',
        audio: 'audio/*',
      });
    });
  });

  describe('Execution preview visibility', () => {
    const entry = {
      step_id: 'image_step_1',
      state: 'COMPLETED',
      attempts: 1,
      history: [
        {step_inputs: {prompt: 'a'}, step_outputs: {generated_image: [1]}},
        {step_inputs: {prompt: 'b'}, step_outputs: {generated_image: [2]}},
      ],
    };

    it('binds the latest history entry outputs', () => {
      component.stepExecution = entry;
      expect(component.latestStepOutputs()).toEqual({generated_image: [2]});
      expect(component.latestStepInputs()).toEqual({prompt: 'b'});
      expect(component.showExecutionResults()).toBeTrue();
    });

    it('hides the output preview when an output is linked', () => {
      component.stepExecution = entry;
      component.isOutputLinked = true;
      expect(component.showOutputPreview()).toBeFalse();
      expect(component.showExecutionResults()).toBeFalse();
    });

    it('still shows errors when an output is linked', () => {
      component.stepExecution = {
        ...entry,
        state: 'FAILED',
        last_error: {category: 'TRANSIENT', detail: 'boom'},
      };
      component.isOutputLinked = true;
      expect(component.showExecutionResults()).toBeTrue();
    });
  });

  describe('Loop Ending output port', () => {
    const loopEndingPortSelector =
      '[data-port-type="output"][data-port-name="loop_ending"]';
    const generatedImagePortSelector =
      '[data-port-type="output"][data-port-name="generated_image"]';

    it('hides the loop_ending output port by default', () => {
      const outputNames = component.visibleOutputs().map(o => o.name);
      expect(outputNames).not.toContain('loop_ending');
      expect(outputNames).toContain('generated_image');

      const host: HTMLElement = fixture.nativeElement;
      expect(host.querySelector(loopEndingPortSelector)).toBeNull();
      expect(host.querySelector(generatedImagePortSelector)).not.toBeNull();
    });

    it('shows the loop_ending output port when enabled', () => {
      component.showLoopEndingOutput = true;
      fixture.detectChanges();

      expect(component.visibleOutputs().map(o => o.name)).toContain(
        'loop_ending',
      );
      const host: HTMLElement = fixture.nativeElement;
      expect(host.querySelector(loopEndingPortSelector)).not.toBeNull();
    });

    it('hides the port again when disabled', () => {
      component.showLoopEndingOutput = true;
      fixture.detectChanges();
      component.showLoopEndingOutput = false;
      fixture.detectChanges();

      const host: HTMLElement = fixture.nativeElement;
      expect(host.querySelector(loopEndingPortSelector)).toBeNull();
    });

    it('keeps the loop_ending control in the outputs form group', () => {
      expect(component.stepForm.get('outputs.loop_ending')).not.toBeNull();
    });
  });
});
