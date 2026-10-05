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
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {BehaviorSubject, of} from 'rxjs';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {NodeTypes, WorkflowModel} from '../../workflow.models';
import {WorkflowService} from '../../workflow.service';
import {BatchExecutionModalComponent} from './batch-execution-modal.component';

describe('BatchExecutionModalComponent', () => {
  let component: BatchExecutionModalComponent;
  let fixture: ComponentFixture<BatchExecutionModalComponent>;
  let workflowServiceSpy: jasmine.SpyObj<WorkflowService>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<BatchExecutionModalComponent>>;
  let activeWorkspaceIdSubject: BehaviorSubject<number | null>;

  const mockWorkflow: WorkflowModel = {
    id: 'wf-batch-1',
    name: 'Batch Workflow',
    description: 'Desc',
    createdAt: '2026-04-19T00:00:00Z',
    updatedAt: '2026-04-19T00:00:00Z',
    userId: '1',
    steps: [
      {
        stepId: 'user_input_1',
        type: NodeTypes.USER_INPUT,
        status: 'IDLE',
        position: {x: 100, y: 100},
        collapsed: false,
        inputs: {},
        outputs: {prompt: {type: 'text'}, aspect_ratio: {type: 'text'}},
        settings: {},
      },
    ],
  };

  beforeEach(async () => {
    workflowServiceSpy = jasmine.createSpyObj<WorkflowService>(
      'WorkflowService',
      ['batchExecuteWorkflow'],
    );
    dialogRefSpy = jasmine.createSpyObj<
      MatDialogRef<BatchExecutionModalComponent>
    >('MatDialogRef', ['close']);
    activeWorkspaceIdSubject = new BehaviorSubject<number | null>(42);

    await TestBed.configureTestingModule({
      declarations: [BatchExecutionModalComponent],
      providers: [
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {provide: MAT_DIALOG_DATA, useValue: {workflow: mockWorkflow}},
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
  });

  it('should create and extract expected inputs from user_input step', () => {
    expect(component).toBeTruthy();
    expect(component.expectedInputs).toEqual(['prompt', 'aspect_ratio']);
  });

  it('should submit batch and compute successCount, queuedCount, failureCount, and resultRows with run_id', () => {
    component.headers = ['Prompt', 'Aspect Ratio'];
    component.parsedItems = [
      {Prompt: 'First item', 'Aspect Ratio': '16:9'},
      {Prompt: 'Second item', 'Aspect Ratio': '1:1'},
      {Prompt: 'Third item', 'Aspect Ratio': '9:16'},
    ];
    component.validateHeaders();
    expect(component.isValid).toBeTrue();

    workflowServiceSpy.batchExecuteWorkflow.and.returnValue(
      of({
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
      }),
    );

    component.runBatch();
    fixture.detectChanges();

    expect(workflowServiceSpy.batchExecuteWorkflow).toHaveBeenCalledWith(
      'wf-batch-1',
      [
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
      ],
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
