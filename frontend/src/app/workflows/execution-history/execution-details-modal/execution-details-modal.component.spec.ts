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
import {ReactiveFormsModule} from '@angular/forms';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Router} from '@angular/router';
import {of, throwError} from 'rxjs';
import {GalleryService} from '../../../gallery/gallery.service';
import {MediaResolutionService} from '../../shared/media-resolution.service';
import {
  NodeTypes,
  WorkflowRunDetail,
  WorkflowRunStatusEnum,
} from '../../workflow.models';
import {WorkflowStatusPipe} from '../../workflow-status.pipe';
import {WorkflowService} from '../../workflow.service';
import {ExecutionDetailsModalComponent} from './execution-details-modal.component';

describe('ExecutionDetailsModalComponent', () => {
  let component: ExecutionDetailsModalComponent;
  let fixture: ComponentFixture<ExecutionDetailsModalComponent>;
  let workflowServiceSpy: jasmine.SpyObj<WorkflowService>;
  let dialogRefSpy: jasmine.SpyObj<
    MatDialogRef<ExecutionDetailsModalComponent>
  >;
  let mediaResolutionSpy: jasmine.SpyObj<MediaResolutionService>;
  let snackBarSpy: jasmine.SpyObj<MatSnackBar>;

  const mockNeedsAttentionRun: WorkflowRunDetail = {
    id: 'run-attention-1',
    workflow_id: 'wf-1',
    status: WorkflowRunStatusEnum.NEEDS_ATTENTION,
    attempt_count: 3,
    last_error_category: 'SAFETY_BLOCK',
    last_error_detail: 'Prompt blocked by safety filter',
    input_args: {
      prompt: 'Original prompt text',
      style: 'cinematic',
    },
    workflow_snapshot: {
      id: 'wf-1',
      name: 'Test Workflow',
      description: 'Desc',
      createdAt: '2026-04-19T00:00:00Z',
      updatedAt: '2026-04-19T00:00:00Z',
      userId: '1',
      steps: [
        {
          stepId: 'user_input_1',
          type: NodeTypes.USER_INPUT,
          status: 'IDLE',
          inputs: {},
          outputs: {prompt: {type: 'text'}, style: {type: 'text'}},
          settings: {},
        },
        {
          stepId: 'generate_image_1',
          type: NodeTypes.IMAGE,
          status: 'IDLE',
          inputs: {},
          outputs: {},
          settings: {mode: 'generate_image'},
        },
      ],
    },
    step_states: {
      generate_image_1: {
        status: 'FAILED',
        attempts: 3,
        outputs: {},
        last_error: {
          category: 'SAFETY_BLOCK',
          detail: 'Prompt blocked by safety filter',
        },
      },
    },
    execution_ids: [
      {
        execution_id: 'exec-1',
        attempt: 1,
        trigger: 'initial',
        started_at: '2026-04-19T12:00:00Z',
      },
      {
        execution_id: 'exec-2',
        attempt: 2,
        trigger: 'auto_retry',
        started_at: '2026-04-19T12:01:00Z',
      },
    ],
  };

  beforeEach(async () => {
    workflowServiceSpy = jasmine.createSpyObj<WorkflowService>(
      'WorkflowService',
      ['getRunDetails', 'resumeRun', 'cancelRun'],
    );
    dialogRefSpy = jasmine.createSpyObj<
      MatDialogRef<ExecutionDetailsModalComponent>
    >('MatDialogRef', ['close']);
    mediaResolutionSpy = jasmine.createSpyObj<MediaResolutionService>(
      'MediaResolutionService',
      ['resolveMediaUrls'],
    );
    snackBarSpy = jasmine.createSpyObj<MatSnackBar>('MatSnackBar', ['open']);

    workflowServiceSpy.getRunDetails.and.returnValue(of(mockNeedsAttentionRun));

    await TestBed.configureTestingModule({
      declarations: [ExecutionDetailsModalComponent],
      imports: [ReactiveFormsModule, WorkflowStatusPipe],
      providers: [
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {
          provide: MAT_DIALOG_DATA,
          useValue: {workflowId: 'wf-1', runId: 'run-attention-1'},
        },
        {provide: WorkflowService, useValue: workflowServiceSpy},
        {provide: GalleryService, useValue: {}},
        {provide: Router, useValue: {}},
        {provide: MediaResolutionService, useValue: mediaResolutionSpy},
        {provide: MatSnackBar, useValue: snackBarSpy},
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(ExecutionDetailsModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create and load run details via getRunDetails', () => {
    expect(component).toBeTruthy();
    expect(workflowServiceSpy.getRunDetails).toHaveBeenCalledWith(
      'wf-1',
      'run-attention-1',
    );
    expect(component.runStatus()).toBe(WorkflowRunStatusEnum.NEEDS_ATTENTION);
    expect(component.stepViewModels().length).toBe(1);
    expect(component.stepViewModels()[0].stepId).toBe('generate_image_1');
    expect(component.stepViewModels()[0].attempts).toBe(3);
  });

  it('should render NEEDS_ATTENTION banner with category-specific guidance for SAFETY_BLOCK, QUOTA, AUTH_EXPIRED, and CAP_EXCEEDED', () => {
    const banner = component.needsAttentionBanner();
    expect(banner).toBeTruthy();
    expect(banner?.category).toBe('SAFETY_BLOCK');
    expect(banner?.title).toContain('Safety Policy');
    expect(banner?.guidance).toContain('safety filter');
    expect(banner?.detail).toBe('Prompt blocked by safety filter');

    // Verify QUOTA category guidance
    component.runDetails.set({
      ...mockNeedsAttentionRun,
      last_error_category: 'QUOTA',
    });
    expect(component.needsAttentionBanner()?.title).toContain('Quota');

    // Verify AUTH_EXPIRED category guidance
    component.runDetails.set({
      ...mockNeedsAttentionRun,
      last_error_category: 'AUTH_EXPIRED',
    });
    expect(component.needsAttentionBanner()?.title).toContain('Authentication');

    // Verify CAP_EXCEEDED category guidance
    component.runDetails.set({
      ...mockNeedsAttentionRun,
      last_error_category: 'CAP_EXCEEDED',
    });
    expect(component.needsAttentionBanner()?.title).toContain(
      'Retry Attempts Exhausted',
    );
  });

  it('should pre-fill resumeForm from input_args and send updated args_override on submitResume', () => {
    expect(component.resumeForm.get('prompt')?.value).toBe(
      'Original prompt text',
    );
    expect(component.resumeForm.get('style')?.value).toBe('cinematic');

    component.toggleResumeForm();
    expect(component.showResumeForm()).toBeTrue();

    component.resumeForm.get('prompt')?.setValue('Updated safe prompt');
    workflowServiceSpy.resumeRun.and.returnValue(
      of({
        run_id: 'run-attention-1',
        status: WorkflowRunStatusEnum.RUNNING,
        execution_id: 'exec-3',
      }),
    );

    component.submitResume();

    expect(workflowServiceSpy.resumeRun).toHaveBeenCalledWith(
      'wf-1',
      'run-attention-1',
      {
        prompt: 'Updated safe prompt',
        style: 'cinematic',
      },
    );
    expect(dialogRefSpy.close).toHaveBeenCalledWith({updated: true});
  });

  it('should surface missing_inputs field errors when resumeRun fails with HTTP 422', () => {
    workflowServiceSpy.resumeRun.and.returnValue(
      throwError(() => ({
        status: 422,
        error: {
          detail: {
            message: 'Missing required inputs for current workflow definition',
            missing_inputs: ['aspect_ratio', 'negative_prompt'],
          },
          missing_inputs: ['aspect_ratio', 'negative_prompt'],
        },
      })),
    );

    component.submitResume();
    fixture.detectChanges();

    expect(component.showResumeForm()).toBeTrue();
    expect(component.missingInputs()).toEqual([
      'aspect_ratio',
      'negative_prompt',
    ]);
    expect(component.fieldErrors()['aspect_ratio']).toContain(
      'Required input "aspect_ratio" is missing.',
    );
    expect(component.resumeForm.contains('aspect_ratio')).toBeTrue();
    expect(
      component.resumeForm
        .get('aspect_ratio')
        ?.hasError('missingRequiredInput'),
    ).toBeTrue();
  });

  it('should render cleanly without a step list when step_states is empty ({})', () => {
    const emptyStepsRun: WorkflowRunDetail = {
      id: 'run-empty-steps',
      workflow_id: 'wf-1',
      status: WorkflowRunStatusEnum.COMPLETED,
      attempt_count: 1,
      input_args: {prompt: 'Hello world'},
      workflow_snapshot: {
        id: 'wf-1',
        name: 'Snapshot Workflow',
        description: '',
        createdAt: '2026-04-19T00:00:00Z',
        updatedAt: '2026-04-19T00:00:00Z',
        userId: '1',
        steps: [],
      },
      step_states: {},
      execution_ids: ['exec-1'],
    };

    component.runDetails.set(emptyStepsRun);
    component.workflowSignal.set(emptyStepsRun.workflow_snapshot ?? null);
    fixture.detectChanges();

    expect(component.stepViewModels().length).toBe(0);
    expect(component.inputArgsEntries().length).toBe(1);
    expect(component.inputArgsEntries()[0].key).toBe('prompt');

    const textContent = fixture.nativeElement.textContent as string;
    expect(textContent).toContain('Completed');
    expect(textContent).toContain('Hello world');
    expect(textContent).toContain('Snapshot Workflow');
    expect(textContent.toLowerCase()).not.toContain('legacy');
  });
});
