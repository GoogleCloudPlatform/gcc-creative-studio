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
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {ActivatedRoute, convertToParamMap} from '@angular/router';
import {of, throwError} from 'rxjs';
import {AuthService} from '../../common/services/auth.service';
import {WorkflowRunStatusEnum, WorkflowRunSummary} from '../workflow.models';
import {WorkflowStatusPipe} from '../workflow-status.pipe';
import {WorkflowService} from '../workflow.service';
import {ExecutionHistoryComponent} from './execution-history.component';
import {ExecutionDetailsModalComponent} from './execution-details-modal/execution-details-modal.component';
import {WorkflowExecutionPollingService} from './workflow-execution-polling.service';

describe('ExecutionHistoryComponent', () => {
  let component: ExecutionHistoryComponent;
  let fixture: ComponentFixture<ExecutionHistoryComponent>;
  let workflowServiceSpy: jasmine.SpyObj<WorkflowService>;
  let pollingServiceSpy: jasmine.SpyObj<WorkflowExecutionPollingService>;
  let dialogSpy: jasmine.SpyObj<MatDialog>;
  let snackBarSpy: jasmine.SpyObj<MatSnackBar>;
  let authServiceSpy: jasmine.SpyObj<AuthService>;

  const mockRuns: WorkflowRunSummary[] = [
    {
      id: 'run-queued-1',
      workflow_id: 'wf-123',
      status: WorkflowRunStatusEnum.QUEUED,
      queue_reason: 'concurrency_capped',
      queue_position: 2,
      attempt_count: 0,
      started_at: '2026-04-19T12:00:00Z',
    },
    {
      id: 'run-attention-1',
      workflow_id: 'wf-123',
      status: WorkflowRunStatusEnum.NEEDS_ATTENTION,
      attempt_count: 3,
      last_error_category: 'SAFETY_BLOCK',
      last_error_detail: 'Blocked by safety filter',
      started_at: '2026-04-19T11:50:00Z',
    },
    {
      id: 'run-completed-1',
      workflow_id: 'wf-123',
      status: WorkflowRunStatusEnum.COMPLETED,
      attempt_count: 1,
      started_at: '2026-04-19T11:00:00Z',
      completed_at: '2026-04-19T11:00:15Z',
    },
  ];

  beforeEach(async () => {
    workflowServiceSpy = jasmine.createSpyObj<WorkflowService>(
      'WorkflowService',
      [
        'getWorkflowById',
        'getRuns',
        'resumeRun',
        'cancelRun',
        'executeWorkflow',
      ],
    );
    pollingServiceSpy = jasmine.createSpyObj<WorkflowExecutionPollingService>(
      'WorkflowExecutionPollingService',
      ['pollRuns', 'pollExecutions'],
    );
    dialogSpy = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    snackBarSpy = jasmine.createSpyObj<MatSnackBar>('MatSnackBar', ['open']);
    authServiceSpy = jasmine.createSpyObj<AuthService>('AuthService', [
      'isUserAdmin',
      'isUserWorkflows',
    ]);

    authServiceSpy.isUserAdmin.and.returnValue(true);
    authServiceSpy.isUserWorkflows.and.returnValue(true);

    workflowServiceSpy.getWorkflowById.and.returnValue(
      of({
        id: 'wf-123',
        name: 'Test Workflow',
        description: 'Desc',
        createdAt: '2026-04-19T00:00:00Z',
        updatedAt: '2026-04-19T00:00:00Z',
        userId: '1',
        steps: [],
      }),
    );
    workflowServiceSpy.getRuns.and.returnValue(
      of({runs: mockRuns, next_page_token: null}),
    );
    pollingServiceSpy.pollRuns.and.returnValue(of(mockRuns));

    await TestBed.configureTestingModule({
      declarations: [ExecutionHistoryComponent],
      imports: [WorkflowStatusPipe],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: of(convertToParamMap({id: 'wf-123'})),
          },
        },
        {provide: WorkflowService, useValue: workflowServiceSpy},
        {
          provide: WorkflowExecutionPollingService,
          useValue: pollingServiceSpy,
        },
        {provide: MatDialog, useValue: dialogSpy},
        {provide: MatSnackBar, useValue: snackBarSpy},
        {provide: AuthService, useValue: authServiceSpy},
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(ExecutionHistoryComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create and load runs via getRuns', () => {
    expect(component).toBeTruthy();
    expect(workflowServiceSpy.getRuns).toHaveBeenCalledWith(
      'wf-123',
      20,
      0,
      'ALL',
    );
    expect(component.runRows().length).toBe(3);
  });

  it('should compute queue position, queue reason label, attempt count, and action eligibility', () => {
    const rows = component.runRows();
    const queuedRow = rows[0];
    expect(queuedRow.queuePositionLabel).toBe('#2 in queue');
    expect(queuedRow.queueReasonLabel).toBe('Waiting on workflow slot');
    expect(queuedRow.canCancel).toBeTrue();
    expect(queuedRow.canResume).toBeFalse();

    const attentionRow = rows[1];
    expect(attentionRow.attemptCount).toBe(3);
    expect(attentionRow.lastErrorCategory).toBe('SAFETY_BLOCK');
    expect(attentionRow.canResume).toBeTrue();
    expect(attentionRow.canCancel).toBeTrue();

    const completedRow = rows[2];
    expect(completedRow.durationSeconds).toBe(15);
    expect(completedRow.canResume).toBeFalse();
    expect(completedRow.canCancel).toBeFalse();
  });

  it('should filter runs when status changes', () => {
    workflowServiceSpy.getRuns.calls.reset();
    component.onStatusChange(WorkflowRunStatusEnum.NEEDS_ATTENTION);

    expect(component.selectedStatus()).toBe(
      WorkflowRunStatusEnum.NEEDS_ATTENTION,
    );
    expect(workflowServiceSpy.getRuns).toHaveBeenCalledWith(
      'wf-123',
      20,
      0,
      WorkflowRunStatusEnum.NEEDS_ATTENTION,
    );
  });

  it('should call workflowService.resumeRun when resumeRun is invoked', () => {
    workflowServiceSpy.resumeRun.and.returnValue(
      of({
        run_id: 'run-attention-1',
        status: WorkflowRunStatusEnum.RUNNING,
        execution_id: 'exec-new',
        queue_reason: null,
        queue_position: null,
      }),
    );

    const mockEvent = jasmine.createSpyObj<Event>('Event', ['stopPropagation']);
    component.resumeRun('run-attention-1', mockEvent);

    expect(mockEvent.stopPropagation).toHaveBeenCalled();
    expect(workflowServiceSpy.resumeRun).toHaveBeenCalledWith(
      'wf-123',
      'run-attention-1',
    );
  });

  it('should open ExecutionDetailsModalComponent with openResumeForm=true on HTTP 422 from resumeRun', () => {
    workflowServiceSpy.resumeRun.and.returnValue(
      throwError(() => ({
        status: 422,
        error: {missing_inputs: ['prompt']},
      })),
    );
    dialogSpy.open.and.returnValue({
      afterClosed: () => of({updated: true}),
    } as never);

    component.resumeRun('run-attention-1');

    expect(dialogSpy.open).toHaveBeenCalledWith(
      ExecutionDetailsModalComponent,
      jasmine.objectContaining({
        data: {
          workflowId: 'wf-123',
          runId: 'run-attention-1',
          executionId: 'run-attention-1',
          openResumeForm: true,
        },
      }),
    );
  });

  it('should call workflowService.cancelRun when cancelRun is invoked', () => {
    workflowServiceSpy.cancelRun.and.returnValue(
      of({
        run_id: 'run-queued-1',
        status: WorkflowRunStatusEnum.CANCELED,
      }),
    );

    const mockEvent = jasmine.createSpyObj<Event>('Event', ['stopPropagation']);
    component.cancelRun('run-queued-1', mockEvent);

    expect(mockEvent.stopPropagation).toHaveBeenCalled();
    expect(workflowServiceSpy.cancelRun).toHaveBeenCalledWith(
      'wf-123',
      'run-queued-1',
    );
  });
});
