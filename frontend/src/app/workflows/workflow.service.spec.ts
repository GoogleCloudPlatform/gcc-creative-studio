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

import {TestBed, fakeAsync, tick} from '@angular/core/testing';
import {provideHttpClient} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';

import {environment} from '../../environments/environment';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {WorkflowService} from './workflow.service';
import {
  BatchExecutionResponse,
  CancelRunResponse,
  ExecutionResponse,
  ResumeRunResponse,
  WorkflowRunDetail,
  WorkflowRunListResponse,
  WorkflowRunStatusEnum,
  WorkflowTemplate,
  WorkflowTemplateCreateDto,
} from './workflow.models';

describe('WorkflowService', () => {
  let service: WorkflowService;
  let httpMock: HttpTestingController;
  let workspaceStateService: WorkspaceStateService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        WorkflowService,
      ],
    });
    service = TestBed.inject(WorkflowService);
    httpMock = TestBed.inject(HttpTestingController);
    workspaceStateService = TestBed.inject(WorkspaceStateService);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created and not expose removed getExecutions or getExecutionDetails', () => {
    expect(service).toBeTruthy();
    expect(
      (service as unknown as Record<string, unknown>)['getExecutions'],
    ).toBeUndefined();
    expect(
      (service as unknown as Record<string, unknown>)['getExecutionDetails'],
    ).toBeUndefined();
  });

  it('should fetch user templates via GET /api/workflows/templates', () => {
    const mockTemplates: WorkflowTemplate[] = [
      {id: 'tpl-1', name: 'T1', description: 'D1', steps: []},
    ];

    service.getUserTemplates().subscribe(templates => {
      expect(templates).toEqual(mockTemplates);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/templates`,
    );
    expect(req.request.method).toBe('GET');
    req.flush(mockTemplates);
  });

  it('should create template via POST /api/workflows/templates', () => {
    const createDto: WorkflowTemplateCreateDto = {
      name: 'New Template',
      description: 'Desc',
      steps: [],
    };
    const createdResult: WorkflowTemplate = {
      id: 'tpl-2',
      ...createDto,
    };

    service.createTemplate(createDto).subscribe(template => {
      expect(template).toEqual(createdResult);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/templates`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(createDto);
    req.flush(createdResult);
  });

  it('should delete template via DELETE /api/workflows/templates/:id', () => {
    service.deleteTemplate('tpl-3').subscribe(res => {
      expect(res).toBeNull();
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/templates/tpl-3`,
    );
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('should return predefined templates from constant', () => {
    const predefined = service.getPredefinedTemplates();
    expect(predefined).toBeDefined();
    expect(predefined.length).toBe(3);
    expect(predefined[0].name).toBe('Fashion Stylist');
    expect(predefined[0].isPredefined).toBeTrue();
    expect(predefined[1].name).toBe('Social Media Post');
    expect(predefined[1].isPredefined).toBeTrue();
    expect(predefined[2].name).toBe('Product Video Ad');
    expect(predefined[2].isPredefined).toBeTrue();
  });

  it('should validate workflow structure via POST /api/workflows/validate', () => {
    const validateDto = {
      name: 'Test Workflow',
      description: 'Validation test',
      steps: [],
    };
    const mockResponse = {
      valid: true,
      message: 'Workflow structure is valid.',
    };

    service.validateWorkflow(validateDto).subscribe(res => {
      expect(res).toEqual(mockResponse);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/validate`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(validateDto);
    req.flush(mockResponse);
  });

  it('should fetch workflow runs via GET /workflows/:id/runs with limit, offset, and status filter', () => {
    const mockListResponse: WorkflowRunListResponse = {
      count: 1,
      data: [
        {
          id: 'run-1',
          workflow_id: 'wf-1',
          status: WorkflowRunStatusEnum.QUEUED,
          queue_reason: 'WAITING_FOR_SLOT',
          queue_position: 1,
          attempt_count: 0,
        },
      ],
      page: 1,
      page_size: 20,
      total_pages: 1,
    };

    service
      .getRuns('wf-1', 20, 0, WorkflowRunStatusEnum.QUEUED)
      .subscribe(res => {
        expect(res).toEqual(mockListResponse);
      });

    const req = httpMock.expectOne(
      r =>
        r.url === `${environment.backendURL}/workflows/wf-1/runs` &&
        r.params.get('limit') === '20' &&
        r.params.get('offset') === '0' &&
        r.params.get('status') === 'queued',
    );
    expect(req.request.method).toBe('GET');
    req.flush(mockListResponse);
  });

  it('should omit status query param when status is ALL in getRuns', () => {
    const mockListResponse: WorkflowRunListResponse = {
      count: 0,
      data: [],
    };

    service.getRuns('wf-1', 10, 20, 'ALL').subscribe(res => {
      expect(res).toEqual(mockListResponse);
    });

    const req = httpMock.expectOne(
      r =>
        r.url === `${environment.backendURL}/workflows/wf-1/runs` &&
        r.params.get('limit') === '10' &&
        r.params.get('offset') === '20' &&
        !r.params.has('status'),
    );
    expect(req.request.method).toBe('GET');
    req.flush(mockListResponse);
  });

  it('should fetch run details via GET /workflows/:workflowId/runs/:runId', () => {
    const mockDetail: WorkflowRunDetail = {
      id: 'run-123',
      workflow_id: 'wf-1',
      status: WorkflowRunStatusEnum.NEEDS_ATTENTION,
      last_error_category: 'SAFETY_BLOCK',
      last_error_detail: 'Blocked by RAI',
      step_states: {
        StepA: {
          status: 'completed',
          outputs: {generated_text: 'ok'},
          attempts: 1,
        },
      },
      input_args: {prompt: 'test'},
    };

    service.getRunDetails('wf-1', 'run-123').subscribe(res => {
      expect(res).toEqual(mockDetail);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/wf-1/runs/run-123`,
    );
    expect(req.request.method).toBe('GET');
    req.flush(mockDetail);
  });

  it('should resume a run via POST /workflows/:workflowId/runs/:runId/resume with args_override', () => {
    const mockResumeResponse: ResumeRunResponse = {
      id: 'run-123',
      run_id: 'run-123',
      status: WorkflowRunStatusEnum.QUEUED,
      queue_reason: 'RESUME_REQUESTED',
    };

    service
      .resumeRun('wf-1', 'run-123', {prompt: 'updated safe prompt'})
      .subscribe(res => {
        expect(res).toEqual(mockResumeResponse);
      });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/wf-1/runs/run-123/resume`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      args_override: {prompt: 'updated safe prompt'},
    });
    req.flush(mockResumeResponse);
  });

  it('should cancel a run via POST /workflows/:workflowId/runs/:runId/cancel', () => {
    const mockCancelResponse: CancelRunResponse = {
      id: 'run-123',
      run_id: 'run-123',
      status: WorkflowRunStatusEnum.CANCELED,
      canceled_by_user: true,
    };

    service.cancelRun('wf-1', 'run-123').subscribe(res => {
      expect(res).toEqual(mockCancelResponse);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/wf-1/runs/run-123/cancel`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush(mockCancelResponse);
  });

  it('should execute workflow and return run_id and queue status', () => {
    spyOn(workspaceStateService, 'getActiveWorkspaceId').and.returnValue(1);
    const mockResponse: ExecutionResponse = {
      run_id: 'run-999',
      execution_id: 'run-999',
      status: WorkflowRunStatusEnum.QUEUED,
      queue_reason: 'WAITING_FOR_SLOT',
    };

    service.executeWorkflow('wf-1', {prompt: 'hello'}).subscribe(res => {
      expect(res).toEqual(mockResponse);
    });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/wf-1/workflow-execute`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      args: {prompt: 'hello', workspace_id: 1},
    });
    req.flush(mockResponse);
  });

  it('should batch execute workflow and return run_id and queue_reason per item', () => {
    spyOn(workspaceStateService, 'getActiveWorkspaceId').and.returnValue(1);
    const mockBatchResponse: BatchExecutionResponse = {
      results: [
        {
          row_index: 0,
          run_id: 'run-b1',
          execution_id: 'run-b1',
          status: 'SUCCESS',
          run_status: WorkflowRunStatusEnum.QUEUED,
          queue_reason: 'WAITING_FOR_SLOT',
        },
      ],
    };

    service
      .batchExecuteWorkflow('wf-1', [{row_index: 0, args: {prompt: 'row 0'}}])
      .subscribe(res => {
        expect(res).toEqual(mockBatchResponse);
      });

    const req = httpMock.expectOne(
      `${environment.backendURL}/workflows/wf-1/batch-execute`,
    );
    expect(req.request.method).toBe('POST');
    req.flush(mockBatchResponse);
  });

  it('should share an in-flight getRuns request for identical parameters and issue a new request after completion', () => {
    const mockListResponse: WorkflowRunListResponse = {
      count: 1,
      data: [
        {
          id: 'run-1',
          workflow_id: 'wf-1',
          status: WorkflowRunStatusEnum.RUNNING,
          attempt_count: 1,
        },
      ],
    };

    const results: WorkflowRunListResponse[] = [];
    service.getRuns('wf-1', 20, 0, 'ALL').subscribe(res => results.push(res));
    service.getRuns('wf-1', 20, 0, 'ALL').subscribe(res => results.push(res));

    const req = httpMock.expectOne(
      r =>
        r.url === `${environment.backendURL}/workflows/wf-1/runs` &&
        r.params.get('limit') === '20' &&
        r.params.get('offset') === '0',
    );
    expect(req.cancelled).toBeFalse();
    req.flush(mockListResponse);
    expect(results.length).toBe(2);

    // Subsequent call after completion triggers a fresh HTTP request
    service.getRuns('wf-1', 20, 0, 'ALL').subscribe(res => results.push(res));
    const req2 = httpMock.expectOne(
      r =>
        r.url === `${environment.backendURL}/workflows/wf-1/runs` &&
        r.params.get('limit') === '20' &&
        r.params.get('offset') === '0',
    );
    req2.flush(mockListResponse);
    expect(results.length).toBe(3);
  });

  it('should keep in-flight getRunDetails request in pollRunDetails and ignore new timer ticks on slow network', fakeAsync(() => {
    const runningDetail: WorkflowRunDetail = {
      id: 'run-123',
      workflow_id: 'wf-1',
      status: WorkflowRunStatusEnum.RUNNING,
      step_states: {},
      input_args: {},
    };
    const completedDetail: WorkflowRunDetail = {
      id: 'run-123',
      workflow_id: 'wf-1',
      status: WorkflowRunStatusEnum.COMPLETED,
      step_states: {},
      input_args: {},
    };

    const emitted: WorkflowRunDetail[] = [];
    const sub = service
      .pollRunDetails('wf-1', 'run-123', 3000)
      .subscribe(detail => emitted.push(detail));

    // t = 0ms: first request issued
    tick(0);
    const req1 = httpMock.expectOne(
      `${environment.backendURL}/workflows/wf-1/runs/run-123`,
    );
    expect(req1.cancelled).toBeFalse();

    // t = 3000ms: timer ticks while req1 is still in-flight; req1 must NOT be cancelled and no new request is made
    tick(3000);
    expect(req1.cancelled).toBeFalse();
    httpMock.expectNone(
      r =>
        r.url === `${environment.backendURL}/workflows/wf-1/runs/run-123` &&
        r !== req1.request,
    );

    // t = 5000ms: req1 finishes with RUNNING status
    tick(2000);
    req1.flush(runningDetail);
    expect(emitted.length).toBe(1);
    expect(emitted[0].status).toBe(WorkflowRunStatusEnum.RUNNING);

    // t = 6000ms: next timer tick issues second request, which completes
    tick(1000);
    const req2 = httpMock.expectOne(
      `${environment.backendURL}/workflows/wf-1/runs/run-123`,
    );
    req2.flush(completedDetail);
    expect(emitted.length).toBe(2);
    expect(emitted[1].status).toBe(WorkflowRunStatusEnum.COMPLETED);

    sub.unsubscribe();
  }));
});
