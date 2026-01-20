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

import { HttpClient } from '@angular/common/http';
import { Injectable, OnDestroy } from '@angular/core';
import { BehaviorSubject, Observable, Subscription, throwError } from 'rxjs';
import {
  tap
} from 'rxjs/operators';
import { environment } from '../../environments/environment';
import { PaginationResponseDto } from '../common/services/source-asset.service';
import { WorkspaceStateService } from '../services/workspace/workspace-state.service';
import {
  ExecutionDetails,
  ExecutionResponse,
  WorkflowCreateDto,
  WorkflowModel,
  WorkflowRunModel,
  WorkflowSearchDto,
  WorkflowUpdateDto,
} from './workflow.models';

@Injectable({
  providedIn: 'root',
})
export class WorkflowService implements OnDestroy {
  private currentWorkflowIdSubject = new BehaviorSubject<string | null>(null);
  currentWorkflowId$: Observable<string | null> =
    this.currentWorkflowIdSubject.asObservable();

  private _workflows = new BehaviorSubject<WorkflowModel[]>([]);
  readonly workflows$: Observable<WorkflowModel[]> =
    this._workflows.asObservable();

  private _isLoading = new BehaviorSubject<boolean>(false);
  readonly isLoading$: Observable<boolean> = this._isLoading.asObservable();

  private _errorMessage = new BehaviorSubject<string | null>(null);
  readonly errorMessage$: Observable<string | null> =
    this._errorMessage.asObservable();

  private _allWorkflowsLoaded = new BehaviorSubject<boolean>(false);
  readonly allWorkflowsLoaded$: Observable<boolean> =
    this._allWorkflowsLoaded.asObservable();

  private currentPage = 0;
  private pageSize = 12;
  private currentFilter = '';
  private dataLoadingSubscription!: Subscription;

  private readonly API_BASE_URL = environment.backendURL;

  constructor(
    private http: HttpClient,
    private workspaceStateService: WorkspaceStateService,
  ) {
    console.log(
      'WorkflowService constructor: Initializing dataLoadingSubscription',
    );

    // Subscribe to the GLOBAL workspace state
    this.dataLoadingSubscription =
      this.workspaceStateService.activeWorkspaceId$.subscribe(workspaceId => {
        if (workspaceId) {
          this.loadWorkflows(true); // Reset and load on workspace change
        }
      });
  }

  ngOnDestroy(): void {
    if (this.dataLoadingSubscription) {
      this.dataLoadingSubscription.unsubscribe();
    }
  }

  setCurrentWorkflowId(workflowId: string | null): void {
    this.currentWorkflowIdSubject.next(workflowId);
  }

  getWorkflows(): Observable<WorkflowModel[]> {
    return this.workflows$;
  }

  // TODO: If we are selecting a workflow run we should query another endpoint
  getWorkflowById(
    workflowId: string,
  ): Observable<WorkflowModel | WorkflowRunModel> {
    return this.http.get<WorkflowModel | WorkflowRunModel>(
      `${this.API_BASE_URL}/workflows/${workflowId}`,
    );
  }

  searchWorkflows(
    searchDto: WorkflowSearchDto,
  ): Observable<PaginationResponseDto<WorkflowModel>> {
    return this.http.post<PaginationResponseDto<WorkflowModel>>(
      `${this.API_BASE_URL}/workflows/search`,
      searchDto,
    );
  }

  loadWorkflows(reset = false): void {
    if (this._isLoading.value || (!reset && this._allWorkflowsLoaded.value)) {
      return;
    }

    if (reset) {
      this.currentPage = 0;
      this._workflows.next([]);
      this._allWorkflowsLoaded.next(false);
    }

    this._isLoading.next(true);
    const offset = this.currentPage * this.pageSize;

    this.searchWorkflows({
      name: this.currentFilter,
      limit: this.pageSize,
      offset: offset,
    }).subscribe(
      response => {
        const currentWorkflows = reset ? [] : this._workflows.getValue();
        this._workflows.next([...currentWorkflows, ...response.data]);

        // Check if we have loaded all workflows
        if (response.data.length < this.pageSize) {
          this._allWorkflowsLoaded.next(true);
        } else {
          this.currentPage++;
        }

        this._isLoading.next(false);
      },
      error => {
        this._errorMessage.next('Failed to load workflows.');
        this._isLoading.next(false);
      },
    );
  }

  setFilter(filter: string) {
    this.currentFilter = filter;
    this.loadWorkflows(true);
  }

  createWorkflow(
    workflowData: WorkflowCreateDto,
  ): Observable<WorkflowModel> {
    return this.http
      .post<WorkflowModel>(`${this.API_BASE_URL}/workflows`, workflowData)
      .pipe(tap(() => this.loadWorkflows(true)));
  }

  updateWorkflow(
    workflow_id: string,
    workflowData: WorkflowUpdateDto,
  ): Observable<{ message: string }> {
    return this.http
      .put<{
        message: string;
      }>(`${this.API_BASE_URL}/workflows/${workflow_id}`, workflowData)
      .pipe(tap(() => this.loadWorkflows(true)));
  }

  deleteWorkflow(workflowId: string): Observable<any> {
    return this.http
      .delete(`${this.API_BASE_URL}/workflows/${workflowId}`)
      .pipe(
        tap(() => {
          const currentWorkflows = this._workflows.getValue();
          const updatedWorkflows = currentWorkflows.filter(
            wf => wf.id !== workflowId,
          );
          this._workflows.next(updatedWorkflows);
        }),
      );
  }

  executeWorkflow(workflowId: string, args: any): Observable<ExecutionResponse> {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (!workspaceId) {
      return throwError(() => new Error('No active workspace ID found.'));
    }
    // Inject workspaceId into the arguments sent to the backend
    const payload = {
      args: {
        ...args,
        workspace_id: workspaceId
      }
    };
    return this.http.post<ExecutionResponse>(
      `${this.API_BASE_URL}/workflows/${workflowId}/workflow-execute`,
      payload
    );
  }

  getExecutionDetails(workflowId: string, executionId: string): Observable<ExecutionDetails> {
    return this.http.get<ExecutionDetails>(
      `${this.API_BASE_URL}/workflows/${workflowId}/executions/${encodeURIComponent(executionId)}`
    );
  }

  getExecutions(
    workflowId: string,
    limit: number = 10,
    pageToken?: string,
    status?: string,
  ): Observable<{ executions: any[]; next_page_token: string }> {
    let params: any = { limit };
    if (pageToken) {
      params['page_token'] = pageToken;
    }
    if (status && status !== 'ALL') {
      params['status'] = status;
    }
    return this.http.get<{ executions: any[]; next_page_token: string }>(
      `${this.API_BASE_URL}/workflows/${workflowId}/executions`,
      { params },
    );
  }
}
