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
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {FormBuilder, ReactiveFormsModule} from '@angular/forms';
import {MatDialog} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatSelectModule} from '@angular/material/select';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {ActivatedRoute, Router} from '@angular/router';
import {of} from 'rxjs';
import {MediaResolutionService} from '../shared/media-resolution.service';
import {NodeTypes} from '../workflow.models';
import {WorkflowStatusPipe} from '../workflow-status.pipe';
import {WorkflowService} from '../workflow.service';
import {WorkflowEditorComponent} from './workflow-editor.component';
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
      createWorkflow: jasmine
        .createSpy('createWorkflow')
        .and.returnValue(of({})),
      updateWorkflow: jasmine
        .createSpy('updateWorkflow')
        .and.returnValue(of({})),
      executeWorkflow: jasmine
        .createSpy('executeWorkflow')
        .and.returnValue(of({})),
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
});
