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

import {HttpClient, HttpParams} from '@angular/common/http';
import {Injectable, OnDestroy, PLATFORM_ID, inject} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {
  BehaviorSubject,
  Observable,
  Subscription,
  throwError,
  timer,
} from 'rxjs';
import {
  exhaustMap,
  finalize,
  shareReplay,
  takeWhile,
  tap,
} from 'rxjs/operators';
import {environment} from '../../environments/environment';
import {PaginationResponseDto} from '../common/services/source-asset.service';
import {WorkspaceStateService} from '../services/workspace/workspace-state.service';
import {PREDEFINED_WORKFLOW_TEMPLATES} from './templates/predefined-templates.constant';
import {
  BatchExecutionItemRequest,
  BatchExecutionResponse,
  CancelRunResponse,
  DynamicStepRecord,
  ExecutionResponse,
  ResumeRunResponse,
  WorkflowCreateDto,
  WorkflowModel,
  WorkflowRunDetail,
  WorkflowRunListResponse,
  WorkflowRunModel,
  WorkflowSearchDto,
  WorkflowTemplate,
  WorkflowTemplateCreateDto,
  WorkflowUpdateDto,
  WorkflowValidateDto,
  WorkflowValidateResponse,
  isNonTerminalRunStatus,
} from './workflow.models';

@Injectable({
  providedIn: 'root',
})
export class WorkflowService implements OnDestroy {
  private platformId = inject(PLATFORM_ID);
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
  private readonly inFlightGetRuns = new Map<
    string,
    Observable<WorkflowRunListResponse>
  >();
  private readonly inFlightGetRunDetails = new Map<
    string,
    Observable<WorkflowRunDetail>
  >();

  private readonly API_BASE_URL = environment.backendURL;

  constructor(
    private http: HttpClient,
    private workspaceStateService: WorkspaceStateService,
  ) {
    if (isPlatformBrowser(this.platformId)) {
      this.dataLoadingSubscription =
        this.workspaceStateService.activeWorkspaceId$.subscribe(workspaceId => {
          if (workspaceId) {
            this.loadWorkflows(true);
          }
        });
    }
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

  loadWorkflows(reset = false, clearData = true): void {
    if (this._isLoading.value || (!reset && this._allWorkflowsLoaded.value)) {
      return;
    }

    if (reset) {
      this.currentPage = 0;
      if (clearData) {
        this._workflows.next([]);
      }
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

        if (response.data.length < this.pageSize) {
          this._allWorkflowsLoaded.next(true);
        } else {
          this.currentPage++;
        }

        this._isLoading.next(false);
      },
      () => {
        this._errorMessage.next('Failed to load workflows.');
        this._isLoading.next(false);
      },
    );
  }

  setFilter(filter: string) {
    this.currentFilter = filter;
    this.loadWorkflows(true, false);
  }

  createWorkflow(workflowData: WorkflowCreateDto): Observable<WorkflowModel> {
    return this.http
      .post<WorkflowModel>(`${this.API_BASE_URL}/workflows`, workflowData)
      .pipe(tap(() => this.loadWorkflows(true)));
  }

  updateWorkflow(
    workflow_id: string,
    workflowData: WorkflowUpdateDto,
  ): Observable<{message: string}> {
    return this.http
      .put<{
        message: string;
      }>(`${this.API_BASE_URL}/workflows/${workflow_id}`, workflowData)
      .pipe(tap(() => this.loadWorkflows(true)));
  }

  deleteWorkflow(workflowId: string): Observable<unknown> {
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

  validateWorkflow(
    workflowData: WorkflowValidateDto,
  ): Observable<WorkflowValidateResponse> {
    return this.http.post<WorkflowValidateResponse>(
      `${this.API_BASE_URL}/workflows/validate`,
      workflowData,
    );
  }

  getUserTemplates(): Observable<WorkflowTemplate[]> {
    return this.http.get<WorkflowTemplate[]>(
      `${this.API_BASE_URL}/workflows/templates`,
    );
  }

  createTemplate(
    templateData: WorkflowTemplateCreateDto,
  ): Observable<WorkflowTemplate> {
    return this.http.post<WorkflowTemplate>(
      `${this.API_BASE_URL}/workflows/templates`,
      templateData,
    );
  }

  deleteTemplate(templateId: string): Observable<void> {
    return this.http.delete<void>(
      `${this.API_BASE_URL}/workflows/templates/${templateId}`,
    );
  }

  getPredefinedTemplates(): WorkflowTemplate[] {
    return PREDEFINED_WORKFLOW_TEMPLATES;
  }

  executeWorkflow(
    workflowId: string,
    args: DynamicStepRecord,
  ): Observable<ExecutionResponse> {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (!workspaceId) {
      return throwError(() => new Error('No active workspace ID found.'));
    }
    const payload = {
      args: {
        ...args,
        workspace_id: workspaceId,
      },
    };
    return this.http.post<ExecutionResponse>(
      `${this.API_BASE_URL}/workflows/${workflowId}/workflow-execute`,
      payload,
    );
  }

  batchExecuteWorkflow(
    workflowId: string,
    items: BatchExecutionItemRequest[],
  ): Observable<BatchExecutionResponse> {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (!workspaceId) {
      return throwError(() => new Error('No active workspace ID found.'));
    }

    const enrichedItems = items.map(item => ({
      ...item,
      args: {
        ...item.args,
        workspace_id: workspaceId,
      },
    }));

    return this.http.post<BatchExecutionResponse>(
      `${this.API_BASE_URL}/workflows/${workflowId}/batch-execute`,
      {items: enrichedItems},
    );
  }

  getRuns(
    workflowId: string,
    limit = 20,
    offset = 0,
    status?: string | null,
  ): Observable<WorkflowRunListResponse> {
    const normalizedStatus =
      status && status !== 'ALL' ? status.toLowerCase() : '';
    const requestKey = `${workflowId}:${limit}:${offset}:${normalizedStatus}`;
    const existingRequest = this.inFlightGetRuns.get(requestKey);
    if (existingRequest) {
      return existingRequest;
    }

    let params = new HttpParams()
      .set('limit', String(limit))
      .set('offset', String(offset));
    if (normalizedStatus) {
      params = params.set('status', normalizedStatus);
    }
    const request$ = this.http
      .get<WorkflowRunListResponse>(
        `${this.API_BASE_URL}/workflows/${workflowId}/runs`,
        {params},
      )
      .pipe(
        finalize(() => {
          this.inFlightGetRuns.delete(requestKey);
        }),
        shareReplay({bufferSize: 1, refCount: true}),
      );
    this.inFlightGetRuns.set(requestKey, request$);
    return request$;
  }

  getRunDetails(
    workflowId: string,
    runId: string,
  ): Observable<WorkflowRunDetail> {
    const requestKey = `${workflowId}:${runId}`;
    const existingRequest = this.inFlightGetRunDetails.get(requestKey);
    if (existingRequest) {
      return existingRequest;
    }

    const request$ = this.http
      .get<WorkflowRunDetail>(
        `${this.API_BASE_URL}/workflows/${workflowId}/runs/${encodeURIComponent(runId)}`,
      )
      .pipe(
        finalize(() => {
          this.inFlightGetRunDetails.delete(requestKey);
        }),
        shareReplay({bufferSize: 1, refCount: true}),
      );
    this.inFlightGetRunDetails.set(requestKey, request$);
    return request$;
  }

  /**
   * Polls run details until the run reaches a terminal or paused status
   * (completed, needs_attention, canceled). Uses `exhaustMap` so an in-flight
   * request is kept alive and new timer ticks are ignored until it completes.
   */
  pollRunDetails(
    workflowId: string,
    runId: string,
    intervalMs = 5000,
  ): Observable<WorkflowRunDetail> {
    return timer(0, intervalMs).pipe(
      exhaustMap(() => this.getRunDetails(workflowId, runId)),
      takeWhile(details => isNonTerminalRunStatus(details.status), true),
      shareReplay(1),
    );
  }

  resumeRun(
    workflowId: string,
    runId: string,
    argsOverride?: DynamicStepRecord | null,
  ): Observable<ResumeRunResponse> {
    const body = argsOverride ? {args_override: argsOverride} : {};
    return this.http.post<ResumeRunResponse>(
      `${this.API_BASE_URL}/workflows/${workflowId}/runs/${encodeURIComponent(runId)}/resume`,
      body,
    );
  }

  cancelRun(workflowId: string, runId: string): Observable<CancelRunResponse> {
    return this.http.post<CancelRunResponse>(
      `${this.API_BASE_URL}/workflows/${workflowId}/runs/${encodeURIComponent(runId)}/cancel`,
      {},
    );
  }
}
