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
});
