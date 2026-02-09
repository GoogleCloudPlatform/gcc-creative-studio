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

import {
  HttpClientTestingModule,
  HttpTestingController,
} from '@angular/common/http/testing';
import {TestBed, fakeAsync, tick} from '@angular/core/testing';
import {BehaviorSubject} from 'rxjs';
import {environment} from '../../environments/environment';
import {PaginationResponseDto} from '../common/services/source-asset.service';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {
  BatchExecutionResponse,
  ExecutionDetails,
  ExecutionResponse,
  WorkflowCreateDto,
  WorkflowModel,
  WorkflowUpdateDto,
} from './workflow.models';
import {WorkflowService} from './workflow.service';

describe('WorkflowService', () => {
  let service: WorkflowService;
  let httpMock: HttpTestingController;
  let workspaceStateServiceMock: {
    activeWorkspaceId$: BehaviorSubject<number | null>;
    getActiveWorkspaceId: () => number | null;
  };

  const API_BASE_URL = environment.backendURL;
  const now = new Date().toISOString();
  const mockWorkflowModel: WorkflowModel = {
    id: '1',
    name: 'Workflow 1',
    description: 'Description 1',
    createdAt: now,
    updatedAt: now,
    userId: 'user-1',
    steps: [],
  };

  beforeEach(() => {
    workspaceStateServiceMock = {
      activeWorkspaceId$: new BehaviorSubject<number | null>(null),
      getActiveWorkspaceId: () =>
        workspaceStateServiceMock.activeWorkspaceId$.getValue(),
    };

    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [
        WorkflowService,
        {
          provide: WorkspaceStateService,
          useValue: workspaceStateServiceMock,
        },
      ],
    });
    service = TestBed.inject(WorkflowService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should load workflows when workspace changes', () => {
    workspaceStateServiceMock.activeWorkspaceId$.next(123);
    const req = httpMock.expectOne(`${API_BASE_URL}/workflows/search`);
    expect(req.request.method).toBe('POST');
    req.flush({
      data: [mockWorkflowModel],
      count: 1,
      page: 0,
      pageSize: 12,
      totalPages: 1,
    });
  });

  it('should set and get current workflow id', () => {
    const testId = 'workflow-123';
    service.setCurrentWorkflowId(testId);
    service.currentWorkflowId$.subscribe(id => {
      expect(id).toBe(testId);
    });
  });

  it('should return workflows observable', () => {
    service.workflows$.subscribe(workflows => {
      expect(workflows).toEqual([]); // Initially empty
    });
  });

  it('should get a workflow by ID', () => {
    const workflowId = '1';

    service.getWorkflowById(workflowId).subscribe(workflow => {
      expect(workflow).toEqual(mockWorkflowModel);
    });

    const req = httpMock.expectOne(`${API_BASE_URL}/workflows/${workflowId}`);
    expect(req.request.method).toBe('GET');
    req.flush(mockWorkflowModel);
  });

  it('should search workflows', () => {
    const mockResponse: PaginationResponseDto<WorkflowModel> = {
      data: [mockWorkflowModel],
      count: 1,
      page: 0,
      pageSize: 1,
      totalPages: 1,
    };
    const searchDto = {name: 'Workflow'};

    service.searchWorkflows(searchDto).subscribe(response => {
      expect(response).toEqual(mockResponse);
    });

    const req = httpMock.expectOne(`${API_BASE_URL}/workflows/search`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(searchDto);
    req.flush(mockResponse);
  });

  it('should load workflows and update observables', fakeAsync(() => {
    const mockResponse: PaginationResponseDto<WorkflowModel> = {
      data: [mockWorkflowModel],
      count: 1,
      page: 0,
      pageSize: 12,
      totalPages: 1,
    };

    let isLoading: boolean | undefined;
    service.isLoading$.subscribe(val => (isLoading = val));

    service.loadWorkflows();
    expect(isLoading).toBe(true);

    const req = httpMock.expectOne(`${API_BASE_URL}/workflows/search`);
    expect(req.request.method).toBe('POST');
    req.flush(mockResponse);

    tick();

    service.workflows$.subscribe(workflows => {
      expect(workflows.length).toBe(1);
      expect(workflows[0].id).toBe('1');
    });

    service.allWorkflowsLoaded$.subscribe(loaded => {
      expect(loaded).toBe(true);
    });

    expect(isLoading).toBe(false);
  }));

  it('should handle error on loadWorkflows', fakeAsync(() => {
    let errorMsg: string | null | undefined;
    service.errorMessage$.subscribe(msg => (errorMsg = msg));

    service.loadWorkflows();

    const req = httpMock.expectOne(`${API_BASE_URL}/workflows/search`);
    req.error(new ErrorEvent('network error'));

    tick();

    expect(errorMsg).toBe('Failed to load workflows.');
    service.isLoading$.subscribe(loading => expect(loading).toBe(false));
  }));

  it('should set filter and reload workflows', () => {
    const filter = 'test';
    const mockResponse: PaginationResponseDto<WorkflowModel> = {
      data: [],
      count: 0,
      page: 0,
      pageSize: 12,
      totalPages: 0,
    };

    service.setFilter(filter);

    const req = httpMock.expectOne(`${API_BASE_URL}/workflows/search`);
    expect(req.request.method).toBe('POST');
    req.flush(mockResponse);

    expect(service['currentFilter']).toBe(filter);
  });

  it('should create a workflow and reload', () => {
    const newWorkflow: WorkflowCreateDto = {
      name: 'New Workflow',
      description: 'New',
      steps: [],
    };
    const mockWorkflow: WorkflowModel = {
      id: '2',
      ...newWorkflow,
      createdAt: now,
      updatedAt: now,
      userId: 'user-1',
    };

    service.createWorkflow(newWorkflow).subscribe(workflow => {
      expect(workflow).toEqual(mockWorkflow);
    });

    const req = httpMock.expectOne(`${API_BASE_URL}/workflows`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(newWorkflow);
    req.flush(mockWorkflow);

    const searchReq = httpMock.expectOne(`${API_BASE_URL}/workflows/search`);
    searchReq.flush({data: [], count: 0, page: 0, pageSize: 12, totalPages: 0});
  });

  it('should update a workflow and reload', () => {
    const updatedWorkflow: WorkflowUpdateDto = {
      name: 'Updated Workflow',
      description: 'Updated',
      steps: [],
    };
    const workflowId = '1';
    const mockResponse = {message: 'Workflow updated'};

    service.updateWorkflow(workflowId, updatedWorkflow).subscribe(response => {
      expect(response).toEqual(mockResponse);
    });

    const req = httpMock.expectOne(`${API_BASE_URL}/workflows/${workflowId}`);
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual(updatedWorkflow);
    req.flush(mockResponse);

    const searchReq = httpMock.expectOne(`${API_BASE_URL}/workflows/search`);
    searchReq.flush({data: [], count: 0, page: 0, pageSize: 12, totalPages: 0});
  });

  it('should delete a workflow and update list', () => {
    const workflowId = '1';
    const initialWorkflows: WorkflowModel[] = [
      mockWorkflowModel,
      {...mockWorkflowModel, id: '2'},
    ];
    service['_workflows'].next(initialWorkflows);

    service.deleteWorkflow(workflowId).subscribe();

    const req = httpMock.expectOne(`${API_BASE_URL}/workflows/${workflowId}`);
    expect(req.request.method).toBe('DELETE');
    req.flush({});

    service.workflows$.subscribe(workflows => {
      expect(workflows.length).toBe(1);
      expect(workflows.find(w => w.id === workflowId)).toBeUndefined();
    });
  });

  it('should execute a workflow', () => {
    workspaceStateServiceMock.activeWorkspaceId$.next(123);
    const searchReq = httpMock.expectOne(`${API_BASE_URL}/workflows/search`);
    searchReq.flush({data: [], count: 0, page: 0, pageSize: 12, totalPages: 0});

    const workflowId = '1';
    const args = {data: 'test'};
    const mockResponse: ExecutionResponse = {execution_id: 'exec-123'};

    service.executeWorkflow(workflowId, args).subscribe(response => {
      expect(response).toEqual(mockResponse);
    });

    const req = httpMock.expectOne(
      `${API_BASE_URL}/workflows/${workflowId}/workflow-execute`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body.args).toEqual({
      ...args,
      workspace_id: 123,
    });
    req.flush(mockResponse);
  });

  it('should throw error if no workspace id for executeWorkflow', () => {
    service.executeWorkflow('1', {}).subscribe({
      error: err => {
        expect(err.message).toBe('No active workspace ID found.');
      },
    });
  });

  it('should batch execute a workflow', () => {
    workspaceStateServiceMock.activeWorkspaceId$.next(123);
    const searchReq = httpMock.expectOne(`${API_BASE_URL}/workflows/search`);
    searchReq.flush({data: [], count: 0, page: 0, pageSize: 12, totalPages: 0});

    const workflowId = '1';
    const items = [{row_index: 0, args: {data: 'test'}}];
    const mockResponse: BatchExecutionResponse = {
      results: [{row_index: 0, execution_id: 'exec-123', status: 'SUCCESS'}],
    };

    service.batchExecuteWorkflow(workflowId, items).subscribe(response => {
      expect(response).toEqual(mockResponse);
    });

    const req = httpMock.expectOne(
      `${API_BASE_URL}/workflows/${workflowId}/batch-execute`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body.items[0].args).toEqual({
      ...items[0].args,
      workspace_id: 123,
    });
    req.flush(mockResponse);
  });

  it('should throw error if no workspace id for batchExecuteWorkflow', () => {
    service.batchExecuteWorkflow('1', []).subscribe({
      error: err => {
        expect(err.message).toBe('No active workspace ID found.');
      },
    });
  });

  it('should get execution details', () => {
    const workflowId = '1';
    const executionId = 'exec-123';
    const mockDetails: ExecutionDetails = {
      id: executionId,
      state: 'SUCCEEDED',
      duration: 100,
      step_entries: [],
    };

    service.getExecutionDetails(workflowId, executionId).subscribe(details => {
      expect(details).toEqual(mockDetails);
    });

    const req = httpMock.expectOne(
      `${API_BASE_URL}/workflows/${workflowId}/executions/${encodeURIComponent(
        executionId,
      )}`,
    );
    expect(req.request.method).toBe('GET');
    req.flush(mockDetails);
  });

  it('should poll execution details until completion', fakeAsync(() => {
    const workflowId = '1';
    const executionId = 'exec-123';
    const activeDetails: ExecutionDetails = {
      id: executionId,
      state: 'ACTIVE',
      duration: 50,
      step_entries: [],
    };
    const finalDetails: ExecutionDetails = {
      id: executionId,
      state: 'SUCCEEDED',
      duration: 100,
      step_entries: [],
    };

    let finalState: ExecutionDetails | undefined;
    service
      .pollExecutionDetails(workflowId, executionId, 1000)
      .subscribe(details => {
        finalState = details;
      });

    // First poll
    tick(0);
    let req = httpMock.expectOne(
      `${API_BASE_URL}/workflows/${workflowId}/executions/${encodeURIComponent(
        executionId,
      )}`,
    );
    expect(req.request.method).toBe('GET');
    req.flush(activeDetails);

    expect(finalState).toEqual(activeDetails);

    // Second poll
    tick(1000);
    req = httpMock.expectOne(
      `${API_BASE_URL}/workflows/${workflowId}/executions/${encodeURIComponent(
        executionId,
      )}`,
    );
    expect(req.request.method).toBe('GET');
    req.flush(finalDetails);

    expect(finalState).toEqual(finalDetails);

    // No more polls
    tick(1000);
    httpMock.expectNone(
      `${API_BASE_URL}/workflows/${workflowId}/executions/${encodeURIComponent(
        executionId,
      )}`,
    );
  }));

  it('should get executions with params', () => {
    const workflowId = '1';
    const limit = 5;
    const pageToken = 'token123';
    const status = 'SUCCEEDED';
    const mockResponse = {executions: [], next_page_token: 'next-token'};

    service
      .getExecutions(workflowId, limit, pageToken, status)
      .subscribe(response => {
        expect(response).toEqual(mockResponse);
      });

    const req = httpMock.expectOne(
      `${API_BASE_URL}/workflows/${workflowId}/executions?limit=${limit}&page_token=${pageToken}&status=${status}`,
    );
    expect(req.request.method).toBe('GET');
    req.flush(mockResponse);
  });

  it('should unsubscribe on destroy', () => {
    workspaceStateServiceMock.activeWorkspaceId$.next(123);
    const req = httpMock.expectOne(`${API_BASE_URL}/workflows/search`);
    req.flush({data: [], count: 0, page: 0, pageSize: 12, totalPages: 0});

    const subscription = service['dataLoadingSubscription'];
    spyOn(subscription, 'unsubscribe');
    service.ngOnDestroy();
    expect(subscription.unsubscribe).toHaveBeenCalled();
  });
});
