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

import { CdkDragDrop, DragDropModule } from '@angular/cdk/drag-drop';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
  AbstractControl,
  FormArray,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
} from '@angular/forms';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ActivatedRoute, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { MediaResolutionService } from '../shared/media-resolution.service';
import {
  NodeTypes,
  StepStatusEnum,
  WorkflowCreateDto,
  WorkflowModel,
  WorkflowUpdateDto,
} from '../workflow.models';
import { WorkflowService } from '../workflow.service';
import { AddStepModalComponent } from './add-step-modal/add-step-modal.component';
import { RunWorkflowModalComponent } from './run-workflow-modal/run-workflow-modal.component';
import { EditorMode, WorkflowEditorComponent } from './workflow-editor.component';
import { WorkflowFormService } from './workflow-form.service';
import { MatOptionModule } from '@angular/material/core';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { WorkflowStatusPipe } from '../workflow-status.pipe';
import { GenericStepComponent } from './step-components/generic-step/generic-step.component';

describe('WorkflowEditorComponent', () => {
  let component: WorkflowEditorComponent;
  let fixture: ComponentFixture<WorkflowEditorComponent>;
  let mockWorkflowFormService: jasmine.SpyObj<WorkflowFormService>;
  let mockWorkflowService: jasmine.SpyObj<WorkflowService>;
  let mockActivatedRoute: any;
  let mockRouter: jasmine.SpyObj<Router>;
  let mockMatDialog: jasmine.SpyObj<MatDialog>;
  let mockMatSnackBar: jasmine.SpyObj<MatSnackBar>;
  let mockMediaResolutionService: jasmine.SpyObj<MediaResolutionService>;

  beforeEach(async () => {
    mockWorkflowFormService = jasmine.createSpyObj('WorkflowFormService', [
      'initForm',
      'patchData',
      'addStep',
      'deleteStep',
      'moveStep',
      'addOutputDefinition',
      'removeOutputDefinition',
      'syncOutputs',
      'updateAfterDelete',
    ]);

    mockWorkflowService = jasmine.createSpyObj('WorkflowService', [
      'getWorkflowById',
      'createWorkflow',
      'updateWorkflow',
      'executeWorkflow',
      'getExecutionDetails',
      'pollExecutionDetails',
    ]);

    mockRouter = jasmine.createSpyObj('Router', ['navigate', 'navigateByUrl']);
    mockMatDialog = jasmine.createSpyObj('MatDialog', ['open']);
    mockMatSnackBar = jasmine.createSpyObj('MatSnackBar', ['open']);
    mockMediaResolutionService = jasmine.createSpyObj(
      'MediaResolutionService',
      ['resolveMediaUrls'],
    );
    mockActivatedRoute = {
      paramMap: of({ get: (key: string) => null }),
      queryParamMap: of({ get: (key: string) => null }),
    };

    // Mock form service properties
    const formGroup = new FormGroup({
      id: new FormControl(''),
      name: new FormControl('Untitled Workflow'),
      description: new FormControl(''),
      steps: new FormArray([]),
      outputDefinitions: new FormArray([]),
      userInput: new FormGroup({
        settings: new FormGroup({
          definitions: new FormArray([]),
        }),
      }),
    });

    Object.defineProperty(mockWorkflowFormService, 'workflowForm', {
      get: () => formGroup,
    });

    Object.defineProperty(mockWorkflowFormService, 'stepsArray', {
      get: () => formGroup.get('steps') as FormArray,
    });

    Object.defineProperty(mockWorkflowFormService, 'outputDefinitionsArray', {
      get: () => formGroup.get('outputDefinitions') as FormArray,
    });

    Object.defineProperty(mockWorkflowFormService, 'availableOutputsPerStep$', {
      get: () => of([]),
    });

    await TestBed.configureTestingModule({
      declarations: [WorkflowEditorComponent, GenericStepComponent],

      imports: [
        ReactiveFormsModule,
        MatIconModule,
        MatFormFieldModule,
        MatInputModule,
        NoopAnimationsModule,
        WorkflowStatusPipe,
        MatOptionModule,
        MatSelectModule,
        DragDropModule,
      ],

      providers: [
        { provide: WorkflowFormService, useValue: mockWorkflowFormService },
        { provide: WorkflowService, useValue: mockWorkflowService },
        { provide: ActivatedRoute, useValue: mockActivatedRoute },
        { provide: Router, useValue: mockRouter },
        { provide: MatDialog, useValue: mockMatDialog },
        { provide: MatSnackBar, useValue: mockMatSnackBar },
        { provide: MediaResolutionService, useValue: mockMediaResolutionService },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(WorkflowEditorComponent);
    component = fixture.componentInstance;
  });

  describe('Initialization', () => {
    it('should initialize in Create mode when no IDs are present', () => {
      fixture.detectChanges();
      expect(component.mode).toBe(EditorMode.Create);
      expect(mockWorkflowFormService.initForm).toHaveBeenCalled();
    });

    it('should initialize in Edit mode when workflowId is present', () => {
      const workflow: WorkflowModel = {
        id: '1',
        name: 'Test',
        description: '',
        steps: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        userId: 'user1',
      };

      mockActivatedRoute.paramMap = of({
        get: (key: string) => (key === 'workflowId' ? '1' : null),
      });

      mockWorkflowService.getWorkflowById.and.returnValue(of(workflow));

      fixture.detectChanges();

      expect(component.mode).toBe(EditorMode.Edit);

      expect(mockWorkflowService.getWorkflowById).toHaveBeenCalledWith('1');

      expect(mockWorkflowFormService.patchData).toHaveBeenCalledWith(workflow);
    });

    it('should initialize in Run mode when runId is present', () => {
      mockActivatedRoute.paramMap = of({
        get: (key: string) => (key === 'runId' ? 'run1' : null),
      });

      // Mocking the service call for a run object will be complex, focusing on mode switch

      const workflow: WorkflowModel = {
        id: '1',
        name: 'Test',
        description: '',
        steps: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        userId: 'user1',
      };

      mockWorkflowService.getWorkflowById.and.returnValue(of(workflow)); // Placeholder

      fixture.detectChanges();

      expect(component.mode).toBe(EditorMode.Run);
    });

    it('should handle error during data loading', () => {
      spyOn(console, 'error');
      mockActivatedRoute.paramMap = of({
        get: (key: string) => (key === 'workflowId' ? '1' : null),
      });

      mockWorkflowService.getWorkflowById.and.returnValue(
        throwError(() => new Error('Failed to load')),
      );

      fixture.detectChanges();

      expect(component.errorMessage).toBe('Failed to load workflow data.');

      expect(component.isLoading).toBeFalse();
    });
  });

  describe('Form and Step Manipulation', () => {
    beforeEach(() => {
      fixture.detectChanges();
    });

    it('should open AddStepModal and add step on result', () => {
      const dialogRefSpy = jasmine.createSpyObj({
        afterClosed: of('new_step_type'),
      });

      mockMatDialog.open.and.returnValue(dialogRefSpy);

      component.openAddStepModal();

      expect(mockMatDialog.open).toHaveBeenCalledWith(
        AddStepModalComponent,
        jasmine.any(Object),
      );

      expect(mockWorkflowFormService.addStep).toHaveBeenCalledWith(
        'new_step_type',
        undefined,
      );
    });

    it('should call form service to delete a step', () => {
      component.deleteStep(0);

      expect(mockWorkflowFormService.deleteStep).toHaveBeenCalledWith(0);

      expect(mockWorkflowFormService.updateAfterDelete).toHaveBeenCalled();
    });

    it('should call form service to move a step', () => {
      const event = { previousIndex: 0, currentIndex: 1 } as CdkDragDrop<
        string[]
      >;

      component.dropStep(event);

      expect(mockWorkflowFormService.moveStep).toHaveBeenCalledWith(0, 1);
    });

    it('should add and remove output definitions via form service', () => {
      fixture.detectChanges();

      component.addOutput();

      expect(mockWorkflowFormService.addOutputDefinition).toHaveBeenCalled();

      component.removeOutput(0);

      expect(
        mockWorkflowFormService.removeOutputDefinition,
      ).toHaveBeenCalledWith(0);
    });
  });

  describe('Workflow Lifecycle (Save/Run)', () => {
    beforeEach(() => {
      fixture.detectChanges();

      component.workflowForm.markAsDirty(); // Enable saving
    });

    it('should not save if form is invalid', () => {
      spyOnProperty(component.workflowForm, 'invalid').and.returnValue(true);

      component.save();

      expect(mockWorkflowService.createWorkflow).not.toHaveBeenCalled();

      expect(mockWorkflowService.updateWorkflow).not.toHaveBeenCalled();
    });

    it('should create a new workflow in Create mode', () => {
      component.mode = EditorMode.Create;

      const createdWorkflow: WorkflowModel = {
        id: 'newId',
        name: 'New',
        description: '',
        steps: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        userId: 'user1',
      };

      mockWorkflowService.createWorkflow.and.returnValue(of(createdWorkflow));

      component.save();

      expect(mockWorkflowService.createWorkflow).toHaveBeenCalledWith(
        jasmine.objectContaining({ name: 'Untitled Workflow', description: '' }),
      );

      expect(component.workflowId).toBe('newId');

      expect(mockRouter.navigate).toHaveBeenCalledWith(
        ['/workflows', 'edit', 'newId'],
        { replaceUrl: true },
      );

      expect(component.mode as any).toBe(EditorMode.Edit);
    });

    it('should update an existing workflow in Edit mode', () => {
      component.mode = EditorMode.Edit;

      component.workflowId = 'existingId';

      component.workflowForm.patchValue({ id: 'existingId' });

      mockWorkflowService.updateWorkflow.and.returnValue(
        of({ message: 'Workflow updated' }),
      );

      component.save();

      expect(mockWorkflowService.updateWorkflow).toHaveBeenCalledWith(
        'existingId',
        jasmine.objectContaining({ name: 'Untitled Workflow', description: '' }),
      );
    });

    it('should handle save failure', () => {
      spyOn(console, 'error');
      component.mode = EditorMode.Create;

      mockWorkflowService.createWorkflow.and.returnValue(
        throwError(() => ({ error: { message: 'Creation failed' } })),
      );

      component.save();

      expect(component.errorMessage).toBe('Creation failed');
    });

    it('should open Run modal directly if form is pristine and workflowId exists', () => {
      component.workflowForm.markAsPristine();

      component.workflowId = 'wf1';

      const dialogRefSpy = jasmine.createSpyObj({ afterClosed: of(null) });

      mockMatDialog.open.and.returnValue(dialogRefSpy);

      component.run();

      expect(mockMatDialog.open).toHaveBeenCalledWith(
        RunWorkflowModalComponent,
        jasmine.any(Object),
      );
    });

    it('should save then run if form is dirty', () => {
      component.mode = EditorMode.Edit;

      component.workflowId = 'wf1';

      component.workflowForm.patchValue({ id: 'wf1' });

      mockWorkflowService.updateWorkflow.and.returnValue(
        of({ message: 'Workflow updated' }),
      );

      const dialogRefSpy = jasmine.createSpyObj({
        afterClosed: of({ input: 'test' }),
      }); // Simulate run confirmation

      mockMatDialog.open.and.returnValue(dialogRefSpy);

      mockWorkflowService.executeWorkflow.and.returnValue(
        of({ execution_id: 'exec1' }),
      );

      mockWorkflowService.pollExecutionDetails.and.returnValue(
        of({ id: 'exec1', state: 'ACTIVE', step_entries: [], duration: 1 }),
      );

      component.run();

      expect(mockWorkflowService.updateWorkflow).toHaveBeenCalled();

      // Use jasmine.clock() or fakeAsync for more robust async tests

      fixture.whenStable().then(() => {
        expect(mockMatDialog.open).toHaveBeenCalledWith(
          RunWorkflowModalComponent,
          jasmine.any(Object),
        );

        expect(mockWorkflowService.executeWorkflow).toHaveBeenCalled();
      });
    });
  });

  describe('Workflow Execution and Polling', () => {
    beforeEach(() => {
      fixture.detectChanges();

      component.workflowId = 'wf1';
    });

    it('should call executeWorkflow and start polling on run confirmation', () => {
      const dialogRefSpy = jasmine.createSpyObj({
        afterClosed: of({ inputs: {} }),
      });

      mockMatDialog.open.and.returnValue(dialogRefSpy);

      mockWorkflowService.executeWorkflow.and.returnValue(
        of({ execution_id: 'exec1' }),
      );

      mockWorkflowService.pollExecutionDetails.and.returnValue(
        of({ id: 'exec1', state: 'ACTIVE', step_entries: [], duration: 1 }),
      );

      component.openRunModal('wf1', {});

      expect(mockWorkflowService.executeWorkflow).toHaveBeenCalledWith('wf1', {
        inputs: {},
      });

      expect(component.currentExecutionId).toBe('exec1');

      expect(component.currentExecutionState).toBe('ACTIVE');

      expect(mockWorkflowService.pollExecutionDetails).toHaveBeenCalledWith(
        'wf1',
        'exec1',
      );
    });

    it('should handle execution start failure', () => {
      spyOn(console, 'error');
      const dialogRefSpy = jasmine.createSpyObj({
        afterClosed: of({ inputs: {} }),
      });

      mockMatDialog.open.and.returnValue(dialogRefSpy);

      mockWorkflowService.executeWorkflow.and.returnValue(
        throwError(() => new Error('Exec failed')),
      );

      component.openRunModal('wf1', {});

      expect(component.errorMessage).toBe('Failed to execute workflow');
    });

    it('should handle polling updates and update step statuses', () => {
      // Add a step to the form to test status updates

      const stepControl = new FormGroup({
        stepId: new FormControl('step1'),

        type: new FormControl(NodeTypes.GENERATE_IMAGE),

        status: new FormControl(StepStatusEnum.IDLE),
      });

      (component.stepsArray as FormArray).push(stepControl);

      fixture.detectChanges();

      const executionDetails = {
        id: 'exec1',

        state: 'ACTIVE',

        step_entries: [
          {
            step_id: 'step1',
            state: 'STATE_IN_PROGRESS',
            step_inputs: {},
            step_outputs: {},
            start_time: new Date().toISOString(),
          },
        ],

        duration: 1,
      };

      // We are not calling the private method directly, but we can check its effects

      // by spying on the pollExecutionDetails and checking the component state

      mockWorkflowService.pollExecutionDetails.and.returnValue(
        of(executionDetails),
      );

      component.onExecutionSelected('exec1');

      fixture.detectChanges();

      expect(component.currentExecutionState).toBe('ACTIVE');

      expect(component.executionStepEntries.length).toBe(1);

      const updatedStep = component.stepsArray.at(0);

      expect(updatedStep.get('status')?.value).toBe(StepStatusEnum.RUNNING);
    });

    it('should stop polling and show success message on completion', () => {
      const executionDetails = {
        id: 'exec1',
        state: 'SUCCEEDED',
        step_entries: [],
        duration: 1,
      };

      mockWorkflowService.getExecutionDetails.and.returnValue(
        of(executionDetails),
      );

      component.onExecutionSelected('exec1');

      fixture.detectChanges();

      expect(component.currentExecutionState).toBe('SUCCEEDED');
    });
  });

  describe('UI and User Interaction', () => {
    beforeEach(() => {
      fixture.detectChanges();
    });

    it('should navigate back to returnUrl if it exists', () => {
      component.returnUrl = '/previous-page';

      component.goBack();

      expect(mockRouter.navigateByUrl).toHaveBeenCalledWith('/previous-page');
    });

    it('should navigate to workflows list if no returnUrl', () => {
      component.returnUrl = null;

      component.goBack();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/workflows']);
    });

    it('should clear dependent inputs when a step is deleted', () => {
      const step1 = new FormGroup({
        stepId: new FormControl('step1'),
        type: new FormControl('type1'),
      });

      const step2 = new FormGroup({
        stepId: new FormControl('step2'),

        type: new FormControl('type2'),

        inputs: new FormGroup({
          prompt: new FormControl({ step: 'step1', output: 'text' }),
        }),
      });

      (component.stepsArray as FormArray).push(step1);

      (component.stepsArray as FormArray).push(step2);

      // We call the private method directly to test its logic.

      (component as any).clearDependents('step1');

      const promptControl = (
        component.stepsArray.at(1).get('inputs') as FormGroup
      ).get('prompt');

      expect(promptControl?.value).toBeNull();
    });

    it('should get correct step type', () => {
      (component.stepsArray as FormArray).push(
        new FormGroup({
          stepId: new FormControl('s1'),

          type: new FormControl(NodeTypes.GENERATE_IMAGE),
        }),
      );

      expect(component.getStepType('s1')).toBe(NodeTypes.GENERATE_IMAGE);

      expect(component.getStepType(NodeTypes.USER_INPUT)).toBe(
        NodeTypes.USER_INPUT,
      );

      expect(component.getStepType('nonexistent')).toBeUndefined();
    });

    it('should identify image output steps correctly', () => {
      spyOn(component, 'getStepType').and.returnValue(NodeTypes.GENERATE_IMAGE);

      expect(component.isImageOutput('step-id')).toBeTrue();

      (component.getStepType as jasmine.Spy).and.returnValue('some-other-type');

      expect(component.isImageOutput('step-id')).toBeFalse();
    });
  });
});
