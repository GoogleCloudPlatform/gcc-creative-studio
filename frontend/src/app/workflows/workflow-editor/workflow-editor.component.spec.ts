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

import {NO_ERRORS_SCHEMA, PLATFORM_ID} from '@angular/core';
import {
  ComponentFixture,
  TestBed,
  discardPeriodicTasks,
  fakeAsync,
  tick,
} from '@angular/core/testing';
import {FormBuilder, FormGroup, ReactiveFormsModule} from '@angular/forms';
import {MatDialog} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatMenuModule} from '@angular/material/menu';
import {MatSelectModule} from '@angular/material/select';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {ActivatedRoute, Router} from '@angular/router';
import {of, throwError} from 'rxjs';
import {MediaResolutionService} from '../shared/media-resolution.service';
import {collectReferenceEdges} from '../utils/workflow-loop.util';
import {
  DynamicStepRecord,
  NodeTypes,
  StepOutputReference,
  StepStatusEnum,
  WorkflowTemplate,
} from '../workflow.models';
import {WorkflowStatusPipe} from '../workflow-status.pipe';
import {WorkflowService} from '../workflow.service';
import {
  loopItemsTextValidator,
  loopLinkedItemsRequiredValidator,
} from './step-components/step-configs/loop-step.config';
import {SaveTemplateModalComponent} from './save-template-modal/save-template-modal.component';
import {EditorMode, WorkflowEditorComponent} from './workflow-editor.component';
import {WorkflowFormService} from './workflow-form.service';

describe('WorkflowEditorComponent - Magnetic Connection Snapping', () => {
  let component: WorkflowEditorComponent;
  let fixture: ComponentFixture<WorkflowEditorComponent>;
  let formService: WorkflowFormService;
  let fb: FormBuilder;

  beforeEach(async () => {
    const activatedRouteMock = {
      snapshot: {
        paramMap: {
          get: (key: string) => null,
        },
        queryParamMap: {
          get: (key: string) => null,
        },
      },
      queryParams: of({}),
      params: of({}),
      queryParamMap: of({
        get: (key: string) => null,
      }),
      paramMap: of({
        get: (key: string) => null,
      }),
    };

    const routerMock = {
      navigate: jasmine.createSpy('navigate'),
    };

    const workflowServiceMock = {
      getWorkflow: jasmine.createSpy('getWorkflow').and.returnValue(of(null)),
      getWorkflowById: jasmine
        .createSpy('getWorkflowById')
        .and.returnValue(of(null)),
      createWorkflow: jasmine
        .createSpy('createWorkflow')
        .and.returnValue(of({})),
      updateWorkflow: jasmine
        .createSpy('updateWorkflow')
        .and.returnValue(of({})),
      executeWorkflow: jasmine
        .createSpy('executeWorkflow')
        .and.returnValue(of({})),
      getRunDetails: jasmine.createSpy('getRunDetails').and.returnValue(of({})),
      pollRunDetails: jasmine
        .createSpy('pollRunDetails')
        .and.returnValue(of({})),
      createTemplate: jasmine
        .createSpy('createTemplate')
        .and.returnValue(of({id: 'tpl-1', name: 'Saved Template', steps: []})),
      getUserTemplates: jasmine
        .createSpy('getUserTemplates')
        .and.returnValue(of([])),
      deleteTemplate: jasmine
        .createSpy('deleteTemplate')
        .and.returnValue(of({message: 'Deleted'})),
      getPredefinedTemplates: jasmine
        .createSpy('getPredefinedTemplates')
        .and.returnValue([]),
      validateWorkflow: jasmine
        .createSpy('validateWorkflow')
        .and.returnValue(of({valid: true, message: 'Valid'})),
    };

    const dialogMock = {
      open: jasmine.createSpy('open'),
    };

    const snackBarMock = {
      open: jasmine.createSpy('open'),
    };

    const mediaResolutionMock = {
      resolveMediaUrls: jasmine.createSpy('resolveMediaUrls'),
    };

    await TestBed.configureTestingModule({
      declarations: [WorkflowEditorComponent],
      imports: [
        ReactiveFormsModule,
        MatFormFieldModule,
        MatSelectModule,
        MatInputModule,
        MatMenuModule,
        NoopAnimationsModule,
        WorkflowStatusPipe,
      ],
      providers: [
        FormBuilder,
        WorkflowFormService,
        {provide: PLATFORM_ID, useValue: 'browser'},
        {provide: ActivatedRoute, useValue: activatedRouteMock},
        {provide: Router, useValue: routerMock},
        {provide: WorkflowService, useValue: workflowServiceMock},
        {provide: MatDialog, useValue: dialogMock},
        {provide: MatSnackBar, useValue: snackBarMock},
        {provide: MediaResolutionService, useValue: mediaResolutionMock},
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fb = TestBed.inject(FormBuilder);
    fixture = TestBed.createComponent(WorkflowEditorComponent);
    component = fixture.componentInstance;
    formService = (component as any).formService;
    fixture.detectChanges();
  });

  it('should initialize component', () => {
    expect(component).toBeTruthy();
    expect(component.dragSourcePort).toBeNull();
    expect(component.magneticTargetPort).toBeNull();
  });

  it('should initialize dragSourcePort and candidateMagneticPorts on onPortDragStart', () => {
    const mouseEvent = new MouseEvent('mousedown');
    spyOn(mouseEvent, 'stopPropagation');
    spyOn(mouseEvent, 'preventDefault');

    component.onPortDragStart({
      stepId: 'user_input',
      outputName: 'prompt',
      mouseEvent,
    });

    expect(component.dragSourcePort).not.toBeNull();
    expect(component.dragSourcePort?.stepId).toBe('user_input');
    expect(component.dragSourcePort?.outputName).toBe('prompt');
    expect(mouseEvent.stopPropagation).toHaveBeenCalled();
    expect(mouseEvent.preventDefault).toHaveBeenCalled();
  });

  it('should cancel active drag wire when Escape key is pressed', () => {
    component.dragSourcePort = {
      stepId: 'step_1',
      outputName: 'out1',
      type: 'text',
    };
    component.activeDragWire = {path: 'M 0 0 L 10 10'};
    component.magneticTargetPort = {
      stepId: 'step_2',
      inputName: 'in1',
      position: {x: 100, y: 100},
    };

    const escapeEvent = new KeyboardEvent('keydown', {key: 'Escape'});
    component.onDocumentKeydown(escapeEvent);

    expect(component.dragSourcePort).toBeNull();
    expect(component.activeDragWire).toBeNull();
    expect(component.magneticTargetPort).toBeNull();
    expect(component.candidateMagneticPorts.length).toBe(0);
  });

  it('should auto-connect on mouseup when magneticTargetPort is active', () => {
    spyOn(component, 'onPortDrop');

    component.dragSourcePort = {
      stepId: 'step_1',
      outputName: 'out1',
      type: 'text',
    };
    component.magneticTargetPort = {
      stepId: 'step_2',
      inputName: 'prompt',
      position: {x: 200, y: 150},
    };

    component.onMouseUp();

    expect(component.onPortDrop).toHaveBeenCalledWith(
      {stepId: 'step_2', inputName: 'prompt'},
      'step_2',
    );
    expect(component.dragSourcePort).toBeNull();
    expect(component.magneticTargetPort).toBeNull();
    expect(component.activeDragWire).toBeNull();
  });

  it('should clear drag state on mouseup without connecting when no magnetic target is locked', () => {
    spyOn(component, 'onPortDrop');

    component.dragSourcePort = {
      stepId: 'step_1',
      outputName: 'out1',
      type: 'text',
    };
    component.magneticTargetPort = null;

    component.onMouseUp();

    expect(component.onPortDrop).not.toHaveBeenCalled();
    expect(component.dragSourcePort).toBeNull();
    expect(component.activeDragWire).toBeNull();
  });

  it('should return stepId and inputName when magneticTargetPort is set', () => {
    component.magneticTargetPort = {
      stepId: 'step_2',
      inputName: 'prompt',
      position: {x: 200, y: 150},
    };

    expect(component.getCurrentLocked()).toEqual({
      stepId: 'step_2',
      inputName: 'prompt',
    });
  });

  it('should return null from getCurrentLocked when no magnetic target is set', () => {
    component.magneticTargetPort = null;

    expect(component.getCurrentLocked()).toBeNull();
  });

  it('should block self-connection to the same node in onPortDrop', () => {
    component.dragSourcePort = {
      stepId: 'step_1',
      outputName: 'out1',
      type: 'text',
    };

    component.onPortDrop({stepId: 'step_1', inputName: 'in1'}, 'step_1');

    expect(component.dragSourcePort).toBeNull();
    expect(component.activeDragWire).toBeNull();
  });

  it('should block duplicate connection if target input is already linked to the same portOut', () => {
    const step1Form = fb.group({
      stepId: ['step_target'],
      type: ['image'],
      inputs: fb.group({
        prompt: [{step: 'step_source', output: 'prompt_out'}],
      }),
    });
    component.stepsArray.push(step1Form);

    component.dragSourcePort = {
      stepId: 'step_source',
      outputName: 'prompt_out',
      type: 'text',
    };

    component.onPortDrop(
      {stepId: 'step_target', inputName: 'prompt'},
      'step_target',
    );

    expect(component.dragSourcePort).toBeNull();
    expect(step1Form.get('inputs')?.get('prompt')?.value).toEqual({
      step: 'step_source',
      output: 'prompt_out',
    });
  });

  it('should block connection from text source to image target in onPortDrop and clear active drag wire', () => {
    const stepTargetForm = fb.group({
      stepId: ['step_image_node'],
      type: ['image'],
      inputs: fb.group({
        prompt: [''],
        input_images: [null],
      }),
    });
    component.stepsArray.push(stepTargetForm);

    component.dragSourcePort = {
      stepId: 'step_text_node',
      outputName: 'generated_text',
      type: 'text',
    };
    component.activeDragWire = {path: 'M 0 0 L 100 100'};

    component.onPortDrop(
      {stepId: 'step_image_node', inputName: 'input_images'},
      'step_image_node',
    );

    expect(component.dragSourcePort).toBeNull();
    expect(component.activeDragWire).toBeNull();
    expect(component.magneticTargetPort).toBeNull();
    expect(component.candidateMagneticPorts.length).toBe(0);
    // Input must remain null (not connected)
    expect(stepTargetForm.get('inputs')?.get('input_images')?.value).toBeNull();
  });

  it('should allow connection from text source to prompt input in onPortDrop', () => {
    const stepTargetForm = fb.group({
      stepId: ['step_image_node'],
      type: ['image'],
      inputs: fb.group({
        prompt: [''],
        input_images: [null],
      }),
    });
    component.stepsArray.push(stepTargetForm);

    component.dragSourcePort = {
      stepId: 'step_text_node',
      outputName: 'generated_text',
      type: 'text',
    };

    component.onPortDrop(
      {stepId: 'step_image_node', inputName: 'prompt'},
      'step_image_node',
    );

    expect(component.dragSourcePort).toBeNull();
    expect(stepTargetForm.get('inputs')?.get('prompt')?.value as any).toEqual({
      step: 'step_text_node',
      output: 'generated_text',
    });
  });

  it('should allow connection from image source to image input in onPortDrop', () => {
    const stepTargetForm = fb.group({
      stepId: ['step_image_node'],
      type: ['image'],
      inputs: fb.group({
        prompt: [''],
        input_images: [null],
      }),
    });
    component.stepsArray.push(stepTargetForm);

    component.dragSourcePort = {
      stepId: 'step_image_source',
      outputName: 'generated_image',
      type: 'image',
    };

    component.onPortDrop(
      {stepId: 'step_image_node', inputName: 'input_images'},
      'step_image_node',
    );

    expect(component.dragSourcePort).toBeNull();
    expect(
      stepTargetForm.get('inputs')?.get('input_images')?.value as any,
    ).toEqual([
      {
        step: 'step_image_source',
        output: 'generated_image',
      },
    ]);
  });

  it('should block connecting a 3rd image when target input allows maximum 2 images in onPortDrop', () => {
    const stepTargetForm = fb.group({
      stepId: ['step_image_node'],
      type: ['image'],
      settings: fb.group({
        model: ['gemini-2.5-flash-image'],
      }),
      inputs: fb.group({
        prompt: [''],
        input_images: [
          [
            {step: 'source_1', output: 'img_1'},
            {step: 'source_2', output: 'img_2'},
          ],
        ],
      }),
    });
    component.stepsArray.push(stepTargetForm);

    component.dragSourcePort = {
      stepId: 'source_3',
      outputName: 'img_3',
      type: 'image',
    };
    component.activeDragWire = {path: 'M 0 0 L 100 100'};

    component.onPortDrop(
      {stepId: 'step_image_node', inputName: 'input_images'},
      'step_image_node',
    );

    expect(component.dragSourcePort).toBeNull();
    expect(component.activeDragWire).toBeNull();
    // Input must still have only 2 images (3rd image is blocked)
    const currentVal = stepTargetForm.get('inputs')?.get('input_images')?.value;
    expect(currentVal?.length).toBe(2);
    expect(currentVal).toEqual([
      {step: 'source_1', output: 'img_1'},
      {step: 'source_2', output: 'img_2'},
    ]);
  });

  it('should exclude full target input ports in collectMagneticCandidatePorts', () => {
    const stepTargetForm = fb.group({
      stepId: ['step_image_node'],
      type: ['image'],
      settings: fb.group({
        model: ['gemini-2.5-flash-image'],
      }),
      inputs: fb.group({
        prompt: [''],
        input_images: [
          [
            {step: 'source_1', output: 'img_1'},
            {step: 'source_2', output: 'img_2'},
          ],
        ],
      }),
    });
    component.stepsArray.push(stepTargetForm);

    spyOn(document, 'querySelector').and.returnValue({} as any);
    spyOn<any>(component, 'getPortPosition').and.returnValue({x: 100, y: 100});

    const candidates = component.collectMagneticCandidatePorts(
      'source_3',
      'img_3',
    );

    expect(candidates.find(c => c.portName === 'input_images')).toBeUndefined();
  });

  it('should include enabled video and audio input ports in collectMagneticCandidatePorts', () => {
    const videoStepForm = fb.group({
      stepId: ['step_video_node'],
      type: [NodeTypes.GENERATE_VIDEO],
      settings: fb.group({
        model: ['gemini-experimental-omni'],
        input_mode: ['Ingredients to Video'],
      }),
      inputs: fb.group({
        prompt: [''],
        input_images: [null],
        input_video: [null],
        input_audio: [null],
      }),
    });
    component.stepsArray.push(videoStepForm);

    spyOn(document, 'querySelector').and.returnValue({} as any);
    spyOn<any>(component, 'getPortPosition').and.returnValue({x: 200, y: 300});

    const videoCandidates = component.collectMagneticCandidatePorts(
      'source_node',
      'generated_video',
    );
    expect(
      videoCandidates.find(c => c.portName === 'input_video'),
    ).toBeDefined();

    const audioCandidates = component.collectMagneticCandidatePorts(
      'source_audio_node',
      'generated_audio',
    );
    expect(
      audioCandidates.find(c => c.portName === 'input_audio'),
    ).toBeDefined();
  });

  it('should exclude disabled video/audio input ports in collectMagneticCandidatePorts', () => {
    const videoControl = fb.control({value: null, disabled: true});
    const videoStepForm = fb.group({
      stepId: ['step_video_node'],
      type: [NodeTypes.GENERATE_VIDEO],
      settings: fb.group({
        model: ['veo-3.1-generate-001'],
      }),
      inputs: fb.group({
        prompt: [''],
        input_video: videoControl,
      }),
    });
    component.stepsArray.push(videoStepForm);

    spyOn(document, 'querySelector').and.returnValue({} as any);
    spyOn<any>(component, 'getPortPosition').and.returnValue({x: 200, y: 300});

    const videoCandidates = component.collectMagneticCandidatePorts(
      'source_node',
      'generated_video',
    );
    expect(
      videoCandidates.find(c => c.portName === 'input_video'),
    ).toBeUndefined();
  });

  it('should allow connection from video source to input_video in onPortDrop', () => {
    const videoStepForm = fb.group({
      stepId: ['step_video_node'],
      type: [NodeTypes.GENERATE_VIDEO],
      inputs: fb.group({
        prompt: [''],
        input_video: [null],
      }),
    });
    component.stepsArray.push(videoStepForm);

    component.dragSourcePort = {
      stepId: 'step_video_source',
      outputName: 'generated_video',
      type: 'video',
    };

    component.onPortDrop(
      {stepId: 'step_video_node', inputName: 'input_video'},
      'step_video_node',
    );

    expect(component.dragSourcePort).toBeNull();
    expect(
      videoStepForm.get('inputs')?.get('input_video')?.value as any,
    ).toEqual({
      step: 'step_video_source',
      output: 'generated_video',
    });
  });

  it('should allow connection from audio source to input_audio in onPortDrop', () => {
    const videoStepForm = fb.group({
      stepId: ['step_video_node'],
      type: [NodeTypes.GENERATE_VIDEO],
      inputs: fb.group({
        prompt: [''],
        input_audio: [null],
      }),
    });
    component.stepsArray.push(videoStepForm);

    component.dragSourcePort = {
      stepId: 'step_audio_source',
      outputName: 'generated_audio',
      type: 'audio',
    };

    component.onPortDrop(
      {stepId: 'step_video_node', inputName: 'input_audio'},
      'step_video_node',
    );

    expect(component.dragSourcePort).toBeNull();
    expect(
      videoStepForm.get('inputs')?.get('input_audio')?.value as any,
    ).toEqual({
      step: 'step_audio_source',
      output: 'generated_audio',
    });
  });

  it('should support adding video output definition to user input node and connecting it to video input', () => {
    formService.addOutputDefinition('User Video', 'video');
    const lastDef = component.outputDefinitionsArray.at(
      component.outputDefinitionsArray.length - 1,
    );
    expect(lastDef.get('type')?.value).toBe('video');
    expect(lastDef.get('name')?.value).toBe('User Video');

    const stepVideoForm = fb.group({
      stepId: ['step_video_node'],
      type: [NodeTypes.GENERATE_VIDEO],
      inputs: fb.group({
        prompt: [''],
        input_video: [null],
      }),
    });
    component.stepsArray.push(stepVideoForm);

    component.dragSourcePort = {
      stepId: 'user_input',
      outputName: 'User Video',
      type: 'video',
    };

    component.onPortDrop(
      {stepId: 'step_video_node', inputName: 'input_video'},
      'step_video_node',
    );

    expect(
      stepVideoForm.get('inputs')?.get('input_video')?.value as any,
    ).toEqual({
      step: 'user_input',
      output: 'User Video',
    });
  });

  it('should allow connection from text source to dynamic prompt variable input in onPortDrop', () => {
    const textStepForm = fb.group({
      stepId: ['step_text_node'],
      type: [NodeTypes.GENERATE_TEXT],
      inputs: fb.group({
        prompt: ['A <animal> wearing a <hat>'],
        animal: [null],
        hat: [null],
      }),
    });
    component.stepsArray.push(textStepForm);

    component.dragSourcePort = {
      stepId: 'step_text_source',
      outputName: 'generated_text',
      type: 'text',
    };

    component.onPortDrop(
      {stepId: 'step_text_node', inputName: 'animal'},
      'step_text_node',
    );

    expect(component.dragSourcePort).toBeNull();
    expect(textStepForm.get('inputs')?.get('animal')?.value as any).toEqual({
      step: 'step_text_source',
      output: 'generated_text',
    });
  });

  it('should not save dynamic prompt variables in prepareSteps when prompt is linked', () => {
    const formValue = {
      name: 'Test Workflow',
      description: 'Test description',
      userInput: {
        outputs: {},
      },
      steps: [
        {
          stepId: 'text_step_linked',
          type: NodeTypes.GENERATE_TEXT,
          inputs: {
            prompt: {step: 'upstream_step', output: 'generated_text'},
            animal: 'Lion',
            input_images: null,
            input_videos: null,
          },
          settings: {model: 'gemini-3-flash-preview'},
          outputs: {generated_text: {type: 'text'}},
        },
      ],
    };

    const preparedSteps = (component as any).prepareSteps(formValue);
    const textStep = preparedSteps.find(
      (s: any) => s.stepId === 'text_step_linked',
    );
    expect(textStep.inputs.prompt).toEqual({
      step: 'upstream_step',
      output: 'generated_text',
    });
    // 'animal' dynamic variable should be omitted from saved step inputs
    expect(textStep.inputs.animal).toBeUndefined();
    expect(textStep.inputs.input_images).toBeNull();
  });

  it('should return dynamic inputs in getDynamicInputs', () => {
    const config = {
      type: NodeTypes.GENERATE_TEXT,
      inputs: [{name: 'prompt', label: 'Prompt', type: 'text'}],
    };
    const inputsGroup = fb.group({
      prompt: ['A photo of a <animal> and <color> flower'],
      animal: [''],
      color: [''],
    });

    const dynamicInputs = component.getDynamicInputs(config, inputsGroup);
    expect(dynamicInputs).toEqual([
      {name: 'animal', label: 'animal', type: 'text'},
      {name: 'color', label: 'color', type: 'text'},
    ]);
  });

  it('should return empty list in getDynamicInputs when prompt is linked for generate_text', () => {
    const config = {
      type: NodeTypes.GENERATE_TEXT,
      inputs: [{name: 'prompt', label: 'Prompt', type: 'text'}],
    };
    const inputsGroup = fb.group({
      prompt: [{step: 'step_prev', output: 'text_out'}],
      animal: [''],
    });

    const dynamicInputs = component.getDynamicInputs(config, inputsGroup);
    expect(dynamicInputs).toEqual([]);
  });

  describe('Loop Linked Items wiring', () => {
    type StepSeed = {
      stepId: string;
      type: NodeTypes;
      inputs?: DynamicStepRecord;
      settings?: DynamicStepRecord;
    };

    const addStep = (seed: StepSeed): void =>
      formService.addStep(seed.type, {
        stepId: seed.stepId,
        type: seed.type,
        status: StepStatusEnum.IDLE,
        position: {x: 0, y: 0},
        collapsed: false,
        inputs: seed.inputs ?? {},
        outputs: {},
        settings: seed.settings ?? {},
      });

    const findStep = (stepId: string): FormGroup =>
      component.stepsArray.controls.find(
        c => c.get('stepId')?.value === stepId,
      ) as FormGroup;

    const imageRef = (stepId: string): StepOutputReference => ({
      step: stepId,
      output: 'generated_image',
    });

    function addLoop(
      mode: string,
      inputs: DynamicStepRecord = {},
      stepId = 'loop_1',
    ): FormGroup {
      addStep({
        stepId,
        type: NodeTypes.LOOP,
        inputs: {
          items_text: null,
          linked_items: null,
          loop_ending: null,
          ...inputs,
        },
        settings: {mode, folder_id: null, item_type: 'image'},
      });
      return findStep(stepId);
    }

    function addSources(): void {
      ['img_a', 'img_b', 'img_c'].forEach(stepId =>
        addStep({stepId, type: NodeTypes.IMAGE}),
      );
      addStep({stepId: 'vid_a', type: NodeTypes.GENERATE_VIDEO});
      addStep({stepId: 'txt_1', type: NodeTypes.GENERATE_TEXT});
    }

    function drop(sourceStepId: string, outputName: string): void {
      component.dragSourcePort = {stepId: sourceStepId, outputName};
      component.onPortDrop(
        {stepId: 'loop_1', inputName: 'linked_items'},
        'loop_1',
      );
    }

    const linkedItemsValue = (): unknown =>
      findStep('loop_1').get('inputs.linked_items')?.value;

    beforeEach(() => {
      addSources();
    });

    it('appends dropped image outputs to linked_items in link order', () => {
      addLoop('linked_items');

      ['img_a', 'img_b', 'img_c'].forEach(stepId =>
        drop(stepId, 'generated_image'),
      );

      expect(linkedItemsValue()).toEqual([
        imageRef('img_a'),
        imageRef('img_b'),
        imageRef('img_c'),
      ]);
    });

    it('rejects a video output while item_type is image', () => {
      addLoop('linked_items');

      drop('vid_a', 'generated_video');

      expect(linkedItemsValue()).toBeNull();
      expect(component.dragSourcePort).toBeNull();
    });

    it('accepts a video output once item_type is video', () => {
      const loop = addLoop('linked_items');
      loop.get('settings.item_type')?.setValue('video');

      drop('vid_a', 'generated_video');

      expect(linkedItemsValue()).toEqual([
        {step: 'vid_a', output: 'generated_video'},
      ]);
    });

    it('rejects linking the same step output twice', () => {
      addLoop('linked_items', {linked_items: [imageRef('img_a')]});

      drop('img_a', 'generated_image');

      expect(linkedItemsValue()).toEqual([imageRef('img_a')]);
    });

    it('rejects the 101st link', () => {
      const fullLinks = Array.from({length: 100}, (_, index) =>
        imageRef(`img_${index}`),
      );
      addLoop('linked_items', {linked_items: fullLinks});

      drop('img_c', 'generated_image');

      expect((linkedItemsValue() as StepOutputReference[]).length).toBe(100);
    });

    it('appends a wire after existing gallery picks, keeping the order', () => {
      const assetPick = {sourceAssetId: 7, previewUrl: ''};
      addLoop('linked_items', {linked_items: [assetPick]});

      drop('img_a', 'generated_image');

      expect(linkedItemsValue()).toEqual([assetPick, imageRef('img_a')]);
    });

    it('rejects a drop when wires and gallery picks already total 100', () => {
      const mixed = [
        ...Array.from({length: 99}, (_, index) => imageRef(`img_${index}`)),
        {sourceAssetId: 7, previewUrl: ''},
      ];
      addLoop('linked_items', {linked_items: mixed});

      drop('img_c', 'generated_image');

      expect(linkedItemsValue()).toEqual(mixed);
    });

    it('rejects a body step of another loop feeding linked_items', () => {
      addLoop('folder', {loop_ending: imageRef('edit_1')}, 'loop_a');
      addStep({
        stepId: 'edit_1',
        type: NodeTypes.IMAGE,
        inputs: {input_images: [{step: 'loop_a', output: 'current_item'}]},
      });
      addLoop('linked_items');

      drop('edit_1', 'generated_image');

      expect(linkedItemsValue()).toBeNull();
    });

    describe('magnetic candidates', () => {
      beforeEach(() => {
        spyOn(document, 'querySelector').and.returnValue(
          document.createElement('div'),
        );
        spyOn<any>(component, 'getPortPosition').and.returnValue({
          x: 10,
          y: 10,
        });
      });

      const linkedItemsCandidate = (sourceStepId: string, output: string) =>
        component
          .collectMagneticCandidatePorts(sourceStepId, output)
          .find(c => c.stepId === 'loop_1' && c.portName === 'linked_items');

      it('offers linked_items for a matching type with the dynamic port type', () => {
        addLoop('linked_items');
        expect(linkedItemsCandidate('img_a', 'generated_image')?.type).toBe(
          'image',
        );
      });

      it('hides linked_items for a different media type', () => {
        addLoop('linked_items');
        expect(
          linkedItemsCandidate('vid_a', 'generated_video'),
        ).toBeUndefined();
      });

      it('hides linked_items outside Linked Items mode (disabled control)', () => {
        const loop = addLoop('folder');
        loop.get('inputs.linked_items')?.disable();
        expect(
          linkedItemsCandidate('img_a', 'generated_image'),
        ).toBeUndefined();
      });
    });

    describe('save validation', () => {
      let consoleErrorSpy: jasmine.Spy;

      beforeEach(() => {
        consoleErrorSpy = spyOn(console, 'error');
      });

      const expectSaveBlockedWith = (message: string): void => {
        let result: unknown = 'not emitted';
        component.saveWorkflow(true).subscribe(value => (result = value));
        expect(result).toBeNull();
        expect(consoleErrorSpy).toHaveBeenCalledWith(
          'Save workflow error:',
          jasmine.objectContaining({message}),
        );
      };

      it('blocks Save with zero links in Linked Items mode', () => {
        const loop = addLoop('linked_items');
        const linkedItems = loop.get('inputs.linked_items');
        linkedItems?.setValidators(loopLinkedItemsRequiredValidator);
        linkedItems?.updateValueAndValidity();

        expectSaveBlockedWith('Add at least one item to the Loop.');
      });

      it('blocks Save with a separator-only fixed items_text', () => {
        const loop = addLoop('text_input', {items_text: ' , '});
        const itemsText = loop.get('inputs.items_text');
        itemsText?.setValidators(loopItemsTextValidator);
        itemsText?.updateValueAndValidity();

        expectSaveBlockedWith('Enter at least one item.');
      });
    });

    it('drops the upstream -> Loop edge after leaving Text Input mode with a linked items_text', () => {
      spyOn<any>(component, 'getPortPosition').and.returnValue({x: 5, y: 5});
      const loop = addLoop('text_input', {
        items_text: {step: 'txt_1', output: 'generated_text'},
      });
      const textEdgeExists = (): boolean =>
        collectReferenceEdges(component.stepsArray.getRawValue()).some(
          edge =>
            edge.sourceStepId === 'txt_1' && edge.targetStepId === 'loop_1',
        );
      (component as any).updateEdges();
      expect(component.edges.some(e => e.sourceId === 'txt_1')).toBeTrue();
      expect(textEdgeExists()).toBeTrue();

      loop.get('settings.mode')?.setValue('folder');

      expect(textEdgeExists()).toBeFalse();
      expect(component.edges.some(e => e.sourceId === 'txt_1')).toBeFalse();
    });
  });

  describe('Workflow Templates Integration', () => {
    it('should open and close welcome view', () => {
      component.mode = EditorMode.Edit;
      component.openWelcomeView();
      expect(component.showWelcomeView).toBeTrue();

      component.closeWelcomeView();
      expect(component.showWelcomeView).toBeFalse();
    });

    it('should navigate back if closeWelcomeView is called in initial empty create mode', () => {
      component.mode = EditorMode.Create;
      spyOn(component, 'goBack');

      component.closeWelcomeView();

      expect(component.goBack).toHaveBeenCalled();
    });

    it('should not render header when welcome view is showing', () => {
      component.showWelcomeView = true;
      fixture.detectChanges();

      const headerEl = fixture.nativeElement.querySelector(
        'header.header-section',
      );
      expect(headerEl).toBeNull();

      component.showWelcomeView = false;
      fixture.detectChanges();

      const visibleHeaderEl = fixture.nativeElement.querySelector(
        'header.header-section',
      );
      expect(visibleHeaderEl).not.toBeNull();
    });

    it('should not render add-btn-wrapper when welcome view is showing', () => {
      component.mode = EditorMode.Create;
      component.showWelcomeView = true;
      fixture.detectChanges();

      const addBtnWrapper =
        fixture.nativeElement.querySelector('.add-btn-wrapper');
      expect(addBtnWrapper).toBeNull();

      component.showWelcomeView = false;
      fixture.detectChanges();

      const visibleAddBtnWrapper =
        fixture.nativeElement.querySelector('.add-btn-wrapper');
      expect(visibleAddBtnWrapper).not.toBeNull();
    });

    it('should reset canvas when blank workflow is selected', () => {
      component.showWelcomeView = true;
      component.onTemplateSelected(null);

      expect(component.showWelcomeView).toBeFalse();
      expect(component.stepsArray.length).toBe(0);
      expect(component.workflowForm.get('name')?.value).toBe(
        'Untitled Workflow',
      );
    });

    it('should populate form and positions when a template is selected', () => {
      const mockTemplate: any = {
        id: 'tpl-100',
        name: 'Human Model Outfit Editor',
        description: 'Edits suit or dress color',
        steps: [
          {
            stepId: 'user_input',
            type: NodeTypes.USER_INPUT,
            position: {x: 80, y: 150},
            outputs: {model_image: {type: 'image'}},
            inputs: {},
            settings: {},
          },
          {
            stepId: 'gen_text',
            type: NodeTypes.GENERATE_TEXT,
            position: {x: 450, y: 150},
            inputs: {prompt: 'Prompt'},
            outputs: {generated_text: {type: 'text'}},
            settings: {model: 'gemini-3.8-flash', temperature: 0.7},
          },
        ],
      };

      component.onTemplateSelected(mockTemplate);

      expect(component.showWelcomeView).toBeFalse();
      expect(component.workflowForm.get('name')?.value).toBe('');
      expect(component.hasWorkflowName).toBeFalse();
      expect(component.workflowForm.get('description')?.value).toBe('');
      expect(component.nodePositions['gen_text']).toEqual({x: 450, y: 150});
      expect(component.workflowForm.dirty).toBeTrue();
    });

    it('should disable Run button when workflow has no name and enable when name is provided', () => {
      const mockTemplate: any = {
        id: 'tpl-100',
        name: 'Human Model Outfit Editor',
        description: 'Edits suit or dress color',
        steps: [
          {
            stepId: 'user_input',
            type: NodeTypes.USER_INPUT,
            outputs: {model_image: {type: 'image'}},
            inputs: {},
            settings: {},
          },
          {
            stepId: 'gen_text',
            type: NodeTypes.GENERATE_TEXT,
            inputs: {prompt: 'Prompt'},
            outputs: {generated_text: {type: 'text'}},
            settings: {model: 'gemini-3.8-flash', temperature: 0.7},
          },
        ],
      };

      component.onTemplateSelected(mockTemplate);
      fixture.detectChanges();

      expect(component.hasWorkflowName).toBeFalse();
      expect(component.isRunDisabled).toBeTrue();
      const runBtn = fixture.nativeElement.querySelector('#workflow-run-btn');
      expect(runBtn.disabled).toBeTrue();

      // Set only whitespace name
      component.workflowForm.get('name')?.setValue('   ');
      fixture.detectChanges();
      expect(component.hasWorkflowName).toBeFalse();
      expect(component.isRunDisabled).toBeTrue();
      expect(runBtn.disabled).toBeTrue();

      // Set valid name
      component.workflowForm.get('name')?.setValue('My Brand New Workflow');
      fixture.detectChanges();
      expect(component.hasWorkflowName).toBeTrue();
      expect(component.isRunDisabled).toBeFalse();
      expect(runBtn.disabled).toBeFalse();
    });

    it('should not call saveWorkflow or createWorkflow when run is called without a workflow name', () => {
      const workflowService = TestBed.inject(WorkflowService);
      (workflowService.createWorkflow as jasmine.Spy).calls.reset();
      spyOn(component, 'saveWorkflow').and.callThrough();

      component.workflowForm.get('name')?.setValue('');
      expect(component.isRunDisabled).toBeTrue();
      component.run();

      expect(component.saveWorkflow).not.toHaveBeenCalled();
      expect(workflowService.createWorkflow).not.toHaveBeenCalled();
    });

    it('should open SaveTemplateModalComponent with workflow steps when saveAsNewTemplate succeeds without saving workflow', () => {
      const dialog = TestBed.inject(MatDialog);
      const workflowService = TestBed.inject(WorkflowService);
      (workflowService.createWorkflow as jasmine.Spy).calls.reset();
      (workflowService.updateWorkflow as jasmine.Spy).calls.reset();
      (workflowService.validateWorkflow as jasmine.Spy).calls.reset();
      const createdTemplate = {
        id: 'tmpl-1',
        name: 'My Blueprint',
        description: 'Desc',
        steps: [],
      };
      (dialog.open as jasmine.Spy).and.returnValue({
        afterClosed: () => of(createdTemplate),
      });

      component.saveAsNewTemplate();

      expect(workflowService.validateWorkflow).toHaveBeenCalled();
      expect(workflowService.createWorkflow).not.toHaveBeenCalled();
      expect(workflowService.updateWorkflow).not.toHaveBeenCalled();
      expect(dialog.open).toHaveBeenCalledWith(
        SaveTemplateModalComponent,
        jasmine.objectContaining({
          data: jasmine.objectContaining({
            steps: jasmine.any(Array),
          }),
        }),
      );
    });

    it('should handle when save template dialog is cancelled', () => {
      const dialog = TestBed.inject(MatDialog);
      const workflowService = TestBed.inject(WorkflowService);
      (workflowService.createTemplate as jasmine.Spy).calls.reset();
      (dialog.open as jasmine.Spy).and.returnValue({
        afterClosed: () => of(null),
      });

      component.saveAsNewTemplate();

      expect(dialog.open).toHaveBeenCalled();
      expect(workflowService.createTemplate).not.toHaveBeenCalled();
    });

    it('should not open save template dialog when steps are empty', () => {
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as jasmine.Spy).calls.reset();
      spyOn<any>(component, 'prepareSteps').and.returnValue([]);

      component.saveAsNewTemplate();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('should not open save template dialog when cycle is detected', () => {
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as jasmine.Spy).calls.reset();
      spyOn<any>(component, 'hasCycle').and.returnValue(true);

      component.saveAsNewTemplate();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('should not open save template dialog when validateWorkflow fails', () => {
      const dialog = TestBed.inject(MatDialog);
      const workflowService = TestBed.inject(WorkflowService);
      (dialog.open as jasmine.Spy).calls.reset();
      (workflowService.validateWorkflow as jasmine.Spy).and.returnValue(
        throwError(() => ({error: {detail: 'Invalid structure'}})),
      );

      component.saveAsNewTemplate();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('should not save workflow when form is pristine during save()', () => {
      const workflowService = TestBed.inject(WorkflowService);
      (workflowService.createWorkflow as jasmine.Spy).calls.reset();
      (workflowService.updateWorkflow as jasmine.Spy).calls.reset();
      component.workflowForm.markAsPristine();

      component.save();

      expect(workflowService.createWorkflow).not.toHaveBeenCalled();
      expect(workflowService.updateWorkflow).not.toHaveBeenCalled();
    });
  });

  describe('Node Coordinates Persistence (Workflows & Templates)', () => {
    it('should include node coordinates from nodePositions in prepareSteps for user_input and all steps', () => {
      component.addStepToForm(NodeTypes.IMAGE, {
        stepId: 'step_img_1',
        type: NodeTypes.IMAGE,
        inputs: {prompt: 'test'},
        outputs: {},
        settings: {},
      });

      component.nodePositions = {
        user_input: {x: 120, y: 220},
        step_img_1: {x: 540, y: 310},
      };

      const formValue = component.workflowForm.getRawValue();
      const prepared = (component as any).prepareSteps(formValue);

      const userInputStep = prepared.find(
        (s: any) => s.stepId === 'user_input',
      );
      const imgStep = prepared.find((s: any) => s.stepId === 'step_img_1');

      expect(userInputStep.position).toEqual({x: 120, y: 220});
      expect(imgStep.position).toEqual({x: 540, y: 310});
    });

    it('should load node positions from step.position when loading a workflow from database', () => {
      const savedWorkflow: any = {
        id: 'wf-db-coords',
        name: 'Saved Workflow',
        description: '',
        userId: '1',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        steps: [
          {
            stepId: 'user_input',
            type: NodeTypes.USER_INPUT,
            position: {x: 150, y: 250},
            inputs: {},
            outputs: {},
            settings: {definitions: []},
          },
          {
            stepId: 'gen_txt_1',
            type: NodeTypes.GENERATE_TEXT,
            position: {x: 600, y: 250},
            inputs: {prompt: 'hello'},
            outputs: {},
            settings: {model: 'gemini-3-flash-preview', temperature: 0.7},
          },
        ],
      };

      component.displayedWorkflow = savedWorkflow;
      (component as any).loadAndSetData();

      expect(component.nodePositions['user_input']).toEqual({x: 150, y: 250});
      expect(component.nodePositions['gen_txt_1']).toEqual({x: 600, y: 250});
    });

    it('should load node positions from step.position when selecting a user template', () => {
      const userTemplate: any = {
        id: 'tmpl-user-1',
        name: 'User Saved Template',
        description: 'Has step.position on steps',
        steps: [
          {
            stepId: 'user_input',
            type: NodeTypes.USER_INPUT,
            position: {x: 90, y: 140},
            inputs: {},
            outputs: {},
            settings: {definitions: []},
          },
          {
            stepId: 'step_video_1',
            type: NodeTypes.GENERATE_VIDEO,
            position: {x: 490, y: 140},
            inputs: {prompt: 'video prompt'},
            outputs: {},
            settings: {model: 'veo-3.1-generate-001'},
          },
        ],
      };

      component.onTemplateSelected(userTemplate);

      expect(component.nodePositions['user_input']).toEqual({x: 90, y: 140});
      expect(component.nodePositions['step_video_1']).toEqual({x: 490, y: 140});
    });

    it('should mark workflowForm as dirty when node drag ends in onMouseUp so save() persists coordinates', () => {
      const workflowService = TestBed.inject(WorkflowService);
      (workflowService.createWorkflow as jasmine.Spy).calls.reset();

      component.workflowForm.patchValue({name: 'Dirty Drag Workflow'});
      component.workflowForm.markAsPristine();
      expect(component.workflowForm.pristine).toBeTrue();

      // Simulate dragging a node and releasing mouse
      (component as any).draggingNodeId = 'user_input';
      component.nodePositions['user_input'] = {x: 333, y: 444};
      component.onMouseUp();

      expect(component.workflowForm.dirty).toBeTrue();

      component.save();
      expect(workflowService.createWorkflow).toHaveBeenCalledWith(
        jasmine.objectContaining({
          steps: jasmine.arrayContaining([
            jasmine.objectContaining({
              stepId: 'user_input',
              position: {x: 333, y: 444},
            }),
          ]),
        }),
      );
    });
  });

  describe('Template Insertion into Active Canvas', () => {
    const sampleTemplateToInsert: WorkflowTemplate = {
      id: 'tmpl-active-insert',
      name: 'Insertable Template',
      description: 'Template for active workflow insertion',
      steps: [
        {
          stepId: 'user_input',
          type: NodeTypes.USER_INPUT,
          status: StepStatusEnum.IDLE,
          position: {x: 0, y: 0},
          collapsed: false,
          inputs: {},
          outputs: {City: {type: 'text'}},
          settings: {
            definitions: [{id: 'def_city', name: 'City', type: 'text'}],
          },
        },
        {
          stepId: 'inserted_step_1',
          type: NodeTypes.GENERATE_TEXT,
          status: StepStatusEnum.IDLE,
          position: {x: 100, y: 50},
          collapsed: false,
          inputs: {
            prompt: 'Weather in <city>',
            city: {
              step: 'user_input',
              output: 'City',
              _definitionId: 'def_city',
            },
          },
          outputs: {generated_text: {type: 'text'}},
          settings: {model: 'gemini-2.5-flash'},
        },
        {
          stepId: 'inserted_step_2',
          type: NodeTypes.IMAGE,
          status: StepStatusEnum.IDLE,
          position: {x: 450, y: 120},
          collapsed: false,
          inputs: {
            prompt: {step: 'inserted_step_1', output: 'generated_text'},
          },
          outputs: {generated_image: {type: 'image'}},
          settings: {mode: 'generate_image'},
        },
      ],
    };

    it('should set isInitialWelcome to false when openWelcomeView(false) is called from toolbar', () => {
      component.isInitialWelcome.set(true);
      component.openWelcomeView(false);

      expect(component.isInitialWelcome()).toBeFalse();
      expect(component.showWelcomeView).toBeTrue();
    });

    it('should preserve existing node coordinates and place new template nodes below maxExistingBottomY + 140', fakeAsync(() => {
      // Set up an active workflow with an existing step
      component.isInitialWelcome.set(false);
      component.nodePositions['user_input'] = {x: 100, y: 100};
      formService.addStep(NodeTypes.GENERATE_TEXT, {
        stepId: 'existing_step',
        type: NodeTypes.GENERATE_TEXT,
        status: StepStatusEnum.IDLE,
        position: {x: 600, y: 200},
        inputs: {},
        outputs: {},
        settings: {},
      });
      component.nodePositions['existing_step'] = {x: 600, y: 200};

      spyOn(component, 'fitView');

      component.onTemplateSelected(sampleTemplateToInsert);

      // Existing node coordinates MUST NOT be modified
      expect(component.nodePositions['user_input']).toEqual({x: 100, y: 100});
      expect(component.nodePositions['existing_step']).toEqual({
        x: 600,
        y: 200,
      });

      // Default fallback node height in test env is 440.
      // existing_step is at y=200 => bottom is 200 + 440 = 640.
      // With VERTICAL_MARGIN = 140, top-most template node (inserted_step_1, minTemplateY=50)
      // must be placed at y = 640 + 140 = 780.
      // inserted_step_2 (orig y=120, dy=+70) must be placed at y = 780 + 70 = 850.
      expect(component.nodePositions['inserted_step_1'].y).toBe(780);
      expect(component.nodePositions['inserted_step_2'].y).toBe(850);

      // Relative X difference between inserted_step_1 (x=100) and inserted_step_2 (x=450) preserved (dx = 350)
      expect(
        component.nodePositions['inserted_step_2'].x -
          component.nodePositions['inserted_step_1'].x,
      ).toBe(350);

      tick(100);
      expect(component.fitView).toHaveBeenCalled();
      tick(5000);
    }));

    it('should highlight newly inserted nodes immediately and clear highlight after 5000ms', fakeAsync(() => {
      component.isInitialWelcome.set(false);
      component.nodePositions['user_input'] = {x: 100, y: 100};
      spyOn(component, 'fitView');

      component.onTemplateSelected(sampleTemplateToInsert);

      // Immediately highlighted
      expect(component.isNodeHighlighted('inserted_step_1')).toBeTrue();
      expect(component.isNodeHighlighted('inserted_step_2')).toBeTrue();
      expect(component.highlightedNodeMap()['inserted_step_1']).toBeTrue();
      expect(component.highlightedNodeMap()['inserted_step_2']).toBeTrue();

      // Still highlighted at 4999ms
      tick(4999);
      expect(component.isNodeHighlighted('inserted_step_1')).toBeTrue();

      // Cleared at 5000ms
      tick(1);
      expect(component.isNodeHighlighted('inserted_step_1')).toBeFalse();
      expect(component.isNodeHighlighted('inserted_step_2')).toBeFalse();
      expect(component.highlightedNodeMap()['inserted_step_1']).toBeUndefined();
      discardPeriodicTasks();
    }));
  });

  describe('Node Collapsed State & Serialization', () => {
    it('should toggle userInput collapsed state, mark form dirty, save history, and update edges', fakeAsync(() => {
      spyOn(component, 'saveHistoryState');
      spyOn<any>(component, 'updateEdges');

      expect(component.isUserInputCollapsed).toBeFalse();

      const mouseEvent = new MouseEvent('click');
      spyOn(mouseEvent, 'stopPropagation');

      component.toggleUserInputCollapse(mouseEvent);

      expect(mouseEvent.stopPropagation).toHaveBeenCalled();
      expect(component.isUserInputCollapsed).toBeTrue();
      expect(
        component.workflowForm.get('userInput.collapsed')?.value,
      ).toBeTrue();
      expect(component.workflowForm.dirty).toBeTrue();
      expect(component.saveHistoryState).toHaveBeenCalled();

      tick(500);
      expect((component as any).updateEdges).toHaveBeenCalled();
      discardPeriodicTasks();
    }));

    it('should mark form dirty, save history, and update edges on step collapse change', fakeAsync(() => {
      spyOn(component, 'saveHistoryState');
      spyOn<any>(component, 'updateEdges');

      component.onStepCollapseChange();

      expect(component.workflowForm.dirty).toBeTrue();
      expect(component.saveHistoryState).toHaveBeenCalled();

      tick(500);
      expect((component as any).updateEdges).toHaveBeenCalled();
      discardPeriodicTasks();
    }));

    it('should serialize collapsed state for user_input and generic steps in prepareSteps', () => {
      component.workflowForm.get('userInput.collapsed')?.setValue(true);

      formService.addStep(NodeTypes.GENERATE_TEXT, {
        stepId: 'text_step_1',
        type: NodeTypes.GENERATE_TEXT,
        collapsed: true,
        inputs: {},
        outputs: {},
        settings: {},
      });

      formService.addStep(NodeTypes.IMAGE, {
        stepId: 'image_step_1',
        type: NodeTypes.IMAGE,
        collapsed: false,
        inputs: {},
        outputs: {},
        settings: {},
      });

      const rawValue = component.workflowForm.getRawValue();
      const prepared = (component as any).prepareSteps(rawValue);

      const userInputStep = prepared.find(
        (s: any) => s.stepId === NodeTypes.USER_INPUT,
      );
      const textStep = prepared.find((s: any) => s.stepId === 'text_step_1');
      const imageStep = prepared.find((s: any) => s.stepId === 'image_step_1');

      expect(userInputStep.collapsed).toBeTrue();
      expect(textStep.collapsed).toBeTrue();
      expect(imageStep.collapsed).toBeFalse();
    });

    it('should preserve collapsed state when saving as a template', () => {
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as jasmine.Spy).and.returnValue({
        afterClosed: () => of(null),
      });
      const workflowService = TestBed.inject(WorkflowService);
      component.workflowForm.get('userInput.collapsed')?.setValue(true);
      formService.addStep(NodeTypes.GENERATE_TEXT, {
        stepId: 'collapsed_step',
        type: NodeTypes.GENERATE_TEXT,
        collapsed: true,
        inputs: {prompt: 'Hello'},
        outputs: {},
        settings: {},
      });

      component.saveAsNewTemplate();

      expect(workflowService.validateWorkflow).toHaveBeenCalled();
      const validatedPayload = (
        workflowService.validateWorkflow as jasmine.Spy
      ).calls.mostRecent().args[0];
      const userInput = validatedPayload.steps.find(
        (s: any) => s.stepId === NodeTypes.USER_INPUT,
      );
      const textStep = validatedPayload.steps.find(
        (s: any) => s.stepId === 'collapsed_step',
      );
      expect(userInput.collapsed).toBeTrue();
      expect(textStep.collapsed).toBeTrue();
    });

    it('should calculate port positions using card element bounding box when node is collapsed', () => {
      const transformLayer =
        component.canvasContent.nativeElement.querySelector('.transform-layer');
      const mockCard = document.createElement('div');
      mockCard.className = 'step-card';
      const mockGenericStep = document.createElement('app-generic-step');
      mockGenericStep.setAttribute('data-node-id', 'step_dom_collapsed');
      mockGenericStep.appendChild(mockCard);
      transformLayer.appendChild(mockGenericStep);

      spyOn(transformLayer, 'getBoundingClientRect').and.returnValue({
        left: 100,
        top: 50,
        width: 1000,
        height: 800,
      } as DOMRect);

      spyOn(mockCard, 'getBoundingClientRect').and.returnValue({
        left: 300,
        top: 150,
        width: 400,
        height: 54,
      } as DOMRect);

      const inputPos = (component as any).getPortPosition(
        'step_dom_collapsed',
        'prompt',
        'input',
      );
      const outputPos = (component as any).getPortPosition(
        'step_dom_collapsed',
        'generated_text',
        'output',
      );

      // Relative to layerRect (100, 50) at scale k=1: left=200, top=100, width=400, height=54
      expect(inputPos).toEqual({x: 200, y: 127});
      expect(outputPos).toEqual({x: 600, y: 127});

      transformLayer.removeChild(mockGenericStep);
    });

    it('should fallback to nodePositions when card element is not in DOM yet', () => {
      component.nodePositions['step_collapsed'] = {x: 300, y: 200};

      // When card element is not in DOM, fallback uses NODE_WIDTH=400, HEADER_HEIGHT=54
      const inputPos = (component as any).getPortPosition(
        'step_collapsed',
        'prompt',
        'input',
      );
      const outputPos = (component as any).getPortPosition(
        'step_collapsed',
        'generated_text',
        'output',
      );

      expect(inputPos).toEqual({x: 300, y: 227});
      expect(outputPos).toEqual({x: 700, y: 227});
    });
  });

  describe('Runs in Flight (HTTP 409) & Workflow Run Polling', () => {
    it('should surface runs-in-flight conflict banner on HTTP 409 when saving workflow and navigate to Execution History', () => {
      const workflowService = TestBed.inject(WorkflowService);
      const router = TestBed.inject(Router);
      (workflowService.updateWorkflow as jasmine.Spy).and.returnValue(
        throwError(() => ({
          status: 409,
          error: {detail: 'Active runs in flight'},
        })),
      );

      component.mode = EditorMode.Edit;
      component.workflowId = 'wf-conflict-1';
      component.workflowForm.patchValue({
        id: 'wf-conflict-1',
        name: 'Updated Name',
      });
      component.workflowForm.markAsDirty();

      component.save();
      fixture.detectChanges();

      expect(component.conflictBannerMessage()).toContain('runs in flight');
      expect(component.conflictBannerMessage()).toContain('Execution History');
      expect(component.errorMessage).toContain('runs in flight');

      const bannerEl = fixture.nativeElement.querySelector(
        '#runs-in-flight-conflict-banner',
      );
      expect(bannerEl).not.toBeNull();

      component.navigateToExecutionHistory();
      expect(component.conflictBannerMessage()).toBeNull();
      expect(router.navigate).toHaveBeenCalledWith([
        '/workflows',
        'wf-conflict-1',
        'executions',
      ]);
    });

    it('should map step_states from getRunDetails onto step form controls and start polling while run is non-terminal', () => {
      const workflowService = TestBed.inject(WorkflowService);
      component.workflowId = 'wf-run-1';
      formService.addStep(NodeTypes.GENERATE_TEXT, {
        stepId: 'step_text_1',
        type: NodeTypes.GENERATE_TEXT,
        status: StepStatusEnum.IDLE,
        inputs: {},
        outputs: {},
        settings: {},
      });
      formService.addStep(NodeTypes.IMAGE, {
        stepId: 'step_img_1',
        type: NodeTypes.IMAGE,
        status: StepStatusEnum.IDLE,
        inputs: {},
        outputs: {},
        settings: {},
      });

      const runDetail = {
        id: 'run-101',
        workflow_id: 'wf-run-1',
        status: 'step_failed',
        step_states: {
          step_text_1: {
            status: 'COMPLETED',
            attempts: 1,
            outputs: {generated_text: 'Cached text output'},
            last_error: null,
          },
          step_img_1: {
            status: 'RUNNING',
            attempts: 2,
            outputs: {},
            last_error: {
              category: 'TRANSIENT',
              detail: '503 Service Unavailable',
            },
          },
        },
      };

      (workflowService.getRunDetails as jasmine.Spy).and.returnValue(
        of(runDetail),
      );
      (workflowService.pollRunDetails as jasmine.Spy).and.returnValue(
        of({
          ...runDetail,
          status: 'completed',
          step_states: {
            ...runDetail.step_states,
            step_img_1: {
              status: 'COMPLETED',
              attempts: 2,
              outputs: {generated_image: 999},
              last_error: null,
            },
          },
        }),
      );

      component.onExecutionSelected('run-101');

      expect(workflowService.getRunDetails).toHaveBeenCalledWith(
        'wf-run-1',
        'run-101',
      );
      expect(workflowService.pollRunDetails).toHaveBeenCalledWith(
        'wf-run-1',
        'run-101',
      );

      const textStepCtrl = component.stepsArray.controls.find(
        c => c.get('stepId')?.value === 'step_text_1',
      );
      const imgStepCtrl = component.stepsArray.controls.find(
        c => c.get('stepId')?.value === 'step_img_1',
      );
      expect(textStepCtrl?.get('status')?.value).toBe(StepStatusEnum.COMPLETED);
      expect(textStepCtrl?.get('outputs')?.value).toEqual({
        generated_text: 'Cached text output',
      });
      expect(imgStepCtrl?.get('status')?.value).toBe(StepStatusEnum.COMPLETED);
      expect(imgStepCtrl?.get('outputs')?.value).toEqual({
        generated_image: 999,
      });
    });

    describe('Loop workflows', () => {
      function addLoopWorkflow(): void {
        formService.addStep(NodeTypes.LOOP, {
          stepId: 'loop_1',
          type: NodeTypes.LOOP,
          status: StepStatusEnum.IDLE,
          inputs: {loop_ending: {step: 'gen_image', output: 'loop_ending'}},
          outputs: {},
          settings: {mode: 'folder', folder_id: 42, item_type: 'image'},
        });
        formService.addStep(NodeTypes.IMAGE, {
          stepId: 'gen_image',
          type: NodeTypes.IMAGE,
          status: StepStatusEnum.IDLE,
          inputs: {input_images: {step: 'loop_1', output: 'current_item'}},
          outputs: {},
          settings: {mode: 'edit_image'},
        });
      }

      const loopRunDetail = {
        id: 'run-loop',
        workflow_id: 'wf-loop',
        status: 'running',
        step_states: {
          loop_1: {
            status: 'COMPLETED',
            inputs: {mode: 'folder', folder_name: 'Photos', item_type: 'image'},
            outputs: {items: [101, 102], total_iterations: 2},
          },
          'gen_image#0': {
            status: 'COMPLETED',
            inputs: {input_images: 101},
            outputs: {generated_image: [501]},
          },
          'gen_image#1': {status: 'RUNNING'},
        },
      };

      it('groups iteration keys into history and keeps the Loop running', () => {
        const workflowService = TestBed.inject(WorkflowService);
        component.workflowId = 'wf-loop';
        addLoopWorkflow();
        (workflowService.getRunDetails as jasmine.Spy).and.returnValue(
          of(loopRunDetail),
        );
        (workflowService.pollRunDetails as jasmine.Spy).and.returnValue(
          of(loopRunDetail),
        );

        component.onExecutionSelected('run-loop');

        const genImage = component.getStepExecution('gen_image');
        expect(genImage?.history.length).toBe(1);
        expect(genImage?.total_iterations).toBe(2);
        expect(component.getStepExecution('gen_image#0')).toBeNull();

        const loopCtrl = component.stepsArray.controls.find(
          c => c.get('stepId')?.value === 'loop_1',
        );
        const imgCtrl = component.stepsArray.controls.find(
          c => c.get('stepId')?.value === 'gen_image',
        );
        expect(loopCtrl?.get('status')?.value).toBe(StepStatusEnum.RUNNING);
        expect(imgCtrl?.get('status')?.value).toBe(StepStatusEnum.RUNNING);
        expect(imgCtrl?.get('outputs.generated_image')?.value).toEqual([501]);
      });

      it('opens the history sidebar for a step with execution data', () => {
        const workflowService = TestBed.inject(WorkflowService);
        component.workflowId = 'wf-loop';
        addLoopWorkflow();
        (workflowService.getRunDetails as jasmine.Spy).and.returnValue(
          of(loopRunDetail),
        );
        (workflowService.pollRunDetails as jasmine.Spy).and.returnValue(
          of(loopRunDetail),
        );
        component.onExecutionSelected('run-loop');

        const imgIndex = component.stepsArray.controls.findIndex(
          c => c.get('stepId')?.value === 'gen_image',
        );
        component.onStepClick(imgIndex, 'gen_image');

        expect(component.historySidebarStep()?.type).toBe(NodeTypes.IMAGE);
        expect(component.historySidebarStep()?.mode).toBe('edit_image');
        expect(component.historySidebarEntry()?.step_id).toBe('gen_image');

        component.closeHistorySidebar();
        expect(component.historySidebarEntry()).toBeNull();
      });

      it('does not open the sidebar without execution data', () => {
        addLoopWorkflow();
        component.onStepClick(0, 'loop_1');
        expect(component.historySidebarStep()).toBeNull();
        expect(component.selectedNodeId).toBe('loop_1');
      });

      it('does not treat the loop_ending back-edge as a cycle', () => {
        addLoopWorkflow();
        const steps = component.stepsArray.getRawValue();
        expect(component['hasCycle'](steps)).toBeFalse();
      });

      describe('Loop Ending port visibility', () => {
        function addOutsideImageStep(inputs: Record<string, unknown>): void {
          formService.addStep(NodeTypes.IMAGE, {
            stepId: 'outside_image',
            type: NodeTypes.IMAGE,
            status: StepStatusEnum.IDLE,
            inputs,
            outputs: {},
            settings: {mode: 'generate_image'},
          });
        }

        it('shows the port for steps inside a loop body', () => {
          addLoopWorkflow();
          component['updateEdges']();
          const visibleMap = component.loopEndingVisibleStepMap();
          expect(visibleMap['gen_image']).toBeTrue();
          expect(visibleMap['loop_1']).toBeUndefined();
        });

        it('hides the port for steps outside any loop body', () => {
          addLoopWorkflow();
          addOutsideImageStep({prompt: 'static prompt'});
          component['updateEdges']();
          expect(
            component.loopEndingVisibleStepMap()['outside_image'],
          ).toBeUndefined();
        });

        it('shows the port for an outside step whose loop_ending is wired', () => {
          addLoopWorkflow();
          addOutsideImageStep({prompt: 'static prompt'});
          const loopCtrl = component.stepsArray.controls.find(
            c => c.get('stepId')?.value === 'loop_1',
          );
          loopCtrl
            ?.get('inputs.loop_ending')
            ?.setValue({step: 'outside_image', output: 'loop_ending'});
          component['updateEdges']();
          expect(
            component.loopEndingVisibleStepMap()['outside_image'],
          ).toBeTrue();
        });

        it('hides the port for every step when there is no loop', () => {
          addOutsideImageStep({prompt: 'static prompt'});
          component['updateEdges']();
          expect(component.loopEndingVisibleStepMap()).toEqual({});
        });
      });
    });
  });
});
