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
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {BehaviorSubject, Subject, of} from 'rxjs';
import {ConfirmationDialogComponent} from '../../../common/components/confirmation-dialog/confirmation-dialog.component';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {
  BatchExecutionResponse,
  NodeTypes,
  WorkflowModel,
  WorkflowStep,
} from '../../workflow.models';
import {WorkflowService} from '../../workflow.service';
import {
  BatchExecutionModalComponent,
  LOOP_BATCH_WARNING,
} from './batch-execution-modal.component';

describe('BatchExecutionModalComponent', () => {
  let component: BatchExecutionModalComponent;
  let fixture: ComponentFixture<BatchExecutionModalComponent>;
  let workflowServiceSpy: jasmine.SpyObj<WorkflowService>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<BatchExecutionModalComponent>>;
  let dialogSpy: jasmine.SpyObj<MatDialog>;
  let confirmationClosed: Subject<boolean | undefined>;
  let activeWorkspaceIdSubject: BehaviorSubject<number | null>;

  const userInputStep: WorkflowStep = {
    stepId: 'user_input_1',
    type: NodeTypes.USER_INPUT,
    status: 'IDLE',
    position: {x: 100, y: 100},
    collapsed: false,
    inputs: {},
    outputs: {prompt: {type: 'text'}, aspect_ratio: {type: 'text'}},
    settings: {},
  };

  const loopStep: WorkflowStep = {
    stepId: 'loop_1',
    type: NodeTypes.LOOP,
    status: 'IDLE',
    position: {x: 300, y: 100},
    collapsed: false,
    inputs: {},
    outputs: {},
    settings: {mode: 'folder', folder_id: 3, item_type: 'image'},
  };

  const buildWorkflow = (steps: WorkflowStep[]): WorkflowModel => ({
    id: 'wf-batch-1',
    name: 'Batch Workflow',
    description: 'Desc',
    createdAt: '2026-04-19T00:00:00Z',
    updatedAt: '2026-04-19T00:00:00Z',
    userId: '1',
    steps,
  });

  const mockWorkflow = buildWorkflow([userInputStep]);
  const loopWorkflow = buildWorkflow([userInputStep, loopStep]);

  const batchResponse: BatchExecutionResponse = {
    total_items: 3,
    submitted_count: 2,
    failed_count: 1,
    message: 'Processed',
    results: [
      {
        row_index: 0,
        status: 'SUCCESS',
        run_id: 'run-batch-1',
        execution_id: 'exec-1',
        queue_reason: null,
      },
      {
        row_index: 1,
        status: 'QUEUED',
        run_id: 'run-batch-2',
        execution_id: null,
        queue_reason: 'concurrency_capped',
      },
      {
        row_index: 2,
        status: 'FAILED',
        run_id: null,
        execution_id: null,
        error: 'Invalid row data',
      },
    ],
  };

  const expectedItems = [
    {
      row_index: 0,
      args: {workspace_id: 42, prompt: 'First item', aspect_ratio: '16:9'},
    },
    {
      row_index: 1,
      args: {workspace_id: 42, prompt: 'Second item', aspect_ratio: '1:1'},
    },
    {
      row_index: 2,
      args: {workspace_id: 42, prompt: 'Third item', aspect_ratio: '9:16'},
    },
  ];

  async function setup(workflow: WorkflowModel): Promise<void> {
    workflowServiceSpy = jasmine.createSpyObj<WorkflowService>(
      'WorkflowService',
      ['batchExecuteWorkflow'],
    );
    workflowServiceSpy.batchExecuteWorkflow.and.returnValue(of(batchResponse));
    dialogRefSpy = jasmine.createSpyObj<
      MatDialogRef<BatchExecutionModalComponent>
    >('MatDialogRef', ['close']);
    confirmationClosed = new Subject<boolean | undefined>();
    dialogSpy = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    dialogSpy.open.and.returnValue({
      afterClosed: () => confirmationClosed.asObservable(),
    } as MatDialogRef<ConfirmationDialogComponent, boolean>);
    activeWorkspaceIdSubject = new BehaviorSubject<number | null>(42);

    await TestBed.configureTestingModule({
      declarations: [BatchExecutionModalComponent],
      providers: [
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {provide: MAT_DIALOG_DATA, useValue: {workflow}},
        {provide: MatDialog, useValue: dialogSpy},
        {provide: WorkflowService, useValue: workflowServiceSpy},
        {
          provide: WorkspaceStateService,
          useValue: {
            activeWorkspaceId$: activeWorkspaceIdSubject.asObservable(),
          },
        },
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(BatchExecutionModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  function loadValidCsv(): void {
    component.headers = ['Prompt', 'Aspect Ratio'];
    component.parsedItems = [
      {Prompt: 'First item', 'Aspect Ratio': '16:9'},
      {Prompt: 'Second item', 'Aspect Ratio': '1:1'},
      {Prompt: 'Third item', 'Aspect Ratio': '9:16'},
    ];
    component.validateHeaders();
  }

  describe('without a Loop step', () => {
    beforeEach(async () => {
      await setup(mockWorkflow);
    });

    it('should create and extract expected inputs from user_input step', () => {
      expect(component).toBeTruthy();
      expect(component.expectedInputs).toEqual(['prompt', 'aspect_ratio']);
      expect(component.hasLoopStep).toBeFalse();
    });

    it('should submit batch and compute successCount, queuedCount, failureCount, and resultRows with run_id', () => {
      loadValidCsv();
      expect(component.isValid).toBeTrue();

      component.runBatch();
      fixture.detectChanges();

      expect(dialogSpy.open).not.toHaveBeenCalled();
      expect(workflowServiceSpy.batchExecuteWorkflow).toHaveBeenCalledWith(
        'wf-batch-1',
        expectedItems,
      );

      expect(component.successCount).toBe(1);
      expect(component.queuedCount).toBe(1);
      expect(component.failureCount).toBe(1);

      const rows = component.resultRows();
      expect(rows.length).toBe(3);
      expect(rows[0].statusLabel).toBe('SUBMITTED');
      expect(rows[0].runId).toBe('run-batch-1');
      expect(rows[1].statusLabel).toBe('QUEUED');
      expect(rows[1].runId).toBe('run-batch-2');
      expect(rows[1].queueReasonLabel).toBe('Waiting on workflow slot');
      expect(rows[2].statusLabel).toBe('FAILED');
      expect(rows[2].error).toBe('Invalid row data');
    });
  });

  describe('with a Loop step', () => {
    beforeEach(async () => {
      await setup(loopWorkflow);
    });

    it('detects the Loop step in the saved workflow', () => {
      expect(component.hasLoopStep).toBeTrue();
    });

    it('opens the Loop warning instead of submitting directly', () => {
      loadValidCsv();

      component.runBatch();

      expect(dialogSpy.open).toHaveBeenCalledOnceWith(
        ConfirmationDialogComponent,
        {data: LOOP_BATCH_WARNING},
      );
      expect(LOOP_BATCH_WARNING.title).toBe('Run batch with a Loop?');
      expect(LOOP_BATCH_WARNING.message).toBe(
        'This workflow contains a Loop. Each batch row runs every loop iteration, which can trigger many generations and incur significant cost. Continue?',
      );
      expect(LOOP_BATCH_WARNING.confirmLabel).toBe('Continue');
      expect(LOOP_BATCH_WARNING.confirmColor).toBe('primary');
      expect(component.isConfirmingBatch()).toBeTrue();
      expect(workflowServiceSpy.batchExecuteWorkflow).not.toHaveBeenCalled();
    });

    it('submits the batch once when the user continues', () => {
      loadValidCsv();

      component.runBatch();
      confirmationClosed.next(true);

      expect(component.isConfirmingBatch()).toBeFalse();
      expect(workflowServiceSpy.batchExecuteWorkflow).toHaveBeenCalledOnceWith(
        'wf-batch-1',
        expectedItems,
      );
    });

    [false, undefined].forEach(result => {
      it(`submits nothing when the warning closes with ${result}`, () => {
        loadValidCsv();

        component.runBatch();
        confirmationClosed.next(result);

        expect(workflowServiceSpy.batchExecuteWorkflow).not.toHaveBeenCalled();
        expect(component.isProcessing).toBeFalse();
        expect(component.isConfirmingBatch()).toBeFalse();
        expect(component.results).toEqual([]);
        expect(component.isValid).toBeTrue();
      });
    });

    it('opens only one warning when Run Batch is clicked twice', () => {
      loadValidCsv();

      component.runBatch();
      component.runBatch();

      expect(dialogSpy.open).toHaveBeenCalledTimes(1);
    });

    it('opens neither the warning nor a submission for an empty CSV', () => {
      component.headers = ['Prompt', 'Aspect Ratio'];
      component.parsedItems = [];
      component.validateHeaders();

      component.runBatch();

      expect(dialogSpy.open).not.toHaveBeenCalled();
      expect(workflowServiceSpy.batchExecuteWorkflow).not.toHaveBeenCalled();
    });

    it('opens neither the warning nor a submission for invalid columns', () => {
      component.headers = ['Unknown'];
      component.parsedItems = [{Unknown: 'x'}];
      component.validateHeaders();

      component.runBatch();

      expect(component.isValid).toBeFalse();
      expect(dialogSpy.open).not.toHaveBeenCalled();
      expect(workflowServiceSpy.batchExecuteWorkflow).not.toHaveBeenCalled();
    });
  });
});
