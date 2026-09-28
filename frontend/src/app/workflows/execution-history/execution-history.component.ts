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

import {Component, OnDestroy, OnInit, computed, signal} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {ActivatedRoute} from '@angular/router';
import {Subscription} from 'rxjs';
import {AuthService} from '../../common/services/auth.service';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../utils/handleMessageSnackbar';
import {RunWorkflowModalComponent} from '../workflow-editor/run-workflow-modal/run-workflow-modal.component';
import {
  isNonTerminalRunStatus,
  NodeTypes,
  QUEUE_REASON_LABELS,
  QueueReason,
  WorkflowModel,
  WorkflowRunStatus,
  WorkflowRunStatusEnum,
  WorkflowRunSummary,
  WorkflowStep,
} from '../workflow.models';
import {WorkflowService} from '../workflow.service';
import {BatchExecutionModalComponent} from './batch-execution-modal/batch-execution-modal.component';
import {ExecutionDetailsModalComponent} from './execution-details-modal/execution-details-modal.component';
import {WorkflowExecutionPollingService} from './workflow-execution-polling.service';

export interface ExecutionRunRowViewModel {
  id: string;
  status: WorkflowRunStatus;
  statusLabel: string;
  queuePositionLabel: string | null;
  queueReasonLabel: string | null;
  attemptCount: number;
  startedAt: string | null;
  durationSeconds: number | null;
  lastErrorCategory: string | null;
  lastErrorDetail: string | null;
  canResume: boolean;
  canCancel: boolean;
  snapshotQueryParams: Record<string, string>;
  raw: WorkflowRunSummary;
}

const RUN_STATUS_LABELS: Record<string, string> = {
  [WorkflowRunStatusEnum.QUEUED]: 'Queued',
  [WorkflowRunStatusEnum.RUNNING]: 'Running',
  [WorkflowRunStatusEnum.STEP_FAILED]: 'Retrying Step',
  [WorkflowRunStatusEnum.NEEDS_ATTENTION]: 'Needs Attention',
  [WorkflowRunStatusEnum.COMPLETED]: 'Completed',
  [WorkflowRunStatusEnum.CANCELED]: 'Canceled',
};

@Component({
  selector: 'app-execution-history',
  templateUrl: './execution-history.component.html',
  styleUrls: ['./execution-history.component.scss'],
})
export class ExecutionHistoryComponent implements OnInit, OnDestroy {
  private readonly pageSize = 20;
  private pollingSubscription: Subscription | null = null;

  readonly workflowId = signal<string | null>(null);
  readonly workflow = signal<WorkflowModel | null>(null);
  readonly runs = signal<WorkflowRunSummary[]>([]);
  /** Alias for `runs` to keep backwards compatibility with existing specs/callers. */
  readonly executions = this.runs;
  readonly isLoading = signal<boolean>(false);
  readonly nextPageToken = signal<string | null>(null);
  readonly currentOffset = signal<number>(0);
  readonly selectedStatus = signal<string>('ALL');
  readonly canRunBatch = signal<boolean>(false);

  readonly returnUrl = computed<string>(() => {
    const id = this.workflowId();
    return id ? `/workflows/${id}/executions` : '/workflows';
  });

  readonly editorQueryParams = computed<Record<string, string>>(() => ({
    returnUrl: this.returnUrl(),
  }));

  readonly runRows = computed<ExecutionRunRowViewModel[]>(() => {
    const retUrl = this.returnUrl();
    return this.runs().map(run => this.toRunRowViewModel(run, retUrl));
  });

  displayedColumns: string[] = [
    'status',
    'id',
    'startTime',
    'duration',
    'actions',
  ];

  constructor(
    private route: ActivatedRoute,
    private workflowService: WorkflowService,
    private pollingService: WorkflowExecutionPollingService,
    private dialog: MatDialog,
    private snackBar: MatSnackBar,
    public authService: AuthService,
  ) {
    this.canRunBatch.set(
      Boolean(
        this.authService?.isUserAdmin?.() ||
          this.authService?.isUserWorkflows?.(),
      ),
    );
  }

  ngOnInit(): void {
    this.route.paramMap.subscribe(params => {
      const id = params.get('id');
      this.workflowId.set(id);
      if (id) {
        this.loadWorkflow();
        this.loadRuns(true);
      }
    });
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }

  loadWorkflow(): void {
    const id = this.workflowId();
    if (!id) return;
    this.workflowService.getWorkflowById(id).subscribe({
      next: workflow => {
        this.workflow.set(workflow as WorkflowModel);
      },
      error: err => {
        console.error('Failed to load workflow details', err);
        handleErrorSnackbar(this.snackBar, err, 'Load workflow details');
      },
    });
  }

  loadRuns(reset = false): void {
    const id = this.workflowId();
    if (!id || this.isLoading()) return;

    this.isLoading.set(true);
    const offset = reset ? 0 : this.currentOffset();

    this.workflowService
      .getRuns(id, this.pageSize, offset, this.selectedStatus())
      .subscribe({
        next: response => {
          const incomingRuns = response?.data ?? response?.runs ?? [];
          if (reset) {
            this.runs.set(incomingRuns);
          } else {
            this.runs.set([...this.runs(), ...incomingRuns]);
          }
          const nextOffset = offset + incomingRuns.length;
          this.currentOffset.set(nextOffset);
          const totalCount = response?.count ?? null;
          const explicitToken =
            response?.next_page_token ??
            response?.nextPageToken ??
            response?.nextPageCursor ??
            null;
          const hasMoreByCount =
            totalCount !== null &&
            nextOffset < totalCount &&
            incomingRuns.length > 0;
          this.nextPageToken.set(
            explicitToken ?? (hasMoreByCount ? String(nextOffset) : null),
          );
          this.isLoading.set(false);

          this.checkAndStartPolling(this.runs());
        },
        error: err => {
          console.error('Failed to load workflow runs', err);
          this.isLoading.set(false);
        },
      });
  }

  /** Alias for `loadRuns` for backwards compatibility. */
  loadExecutions(reset = false): void {
    this.loadRuns(reset);
  }

  loadMore(): void {
    if (this.nextPageToken()) {
      this.loadRuns(false);
    }
  }

  onStatusChange(newStatus?: string): void {
    if (newStatus !== undefined) {
      this.selectedStatus.set(newStatus);
    }
    this.loadRuns(true);
  }

  openDetails(runId: string, openResumeForm = false): void {
    const id = this.workflowId();
    if (!id) return;

    const dialogRef = this.dialog.open(ExecutionDetailsModalComponent, {
      width: '840px',
      maxWidth: '92vw',
      maxHeight: '90vh',
      data: {
        workflowId: id,
        runId,
        executionId: runId,
        openResumeForm,
      },
      panelClass: 'execution-details-modal',
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result?.updated) {
        this.loadRuns(true);
      }
    });
  }

  resumeRun(runId: string, event?: Event): void {
    event?.stopPropagation();
    const id = this.workflowId();
    if (!id) return;

    this.workflowService.resumeRun(id, runId).subscribe({
      next: () => {
        handleSuccessSnackbar(this.snackBar, 'Workflow run resumed!');
        this.loadRuns(true);
      },
      error: err => {
        if (err?.status === 422) {
          this.openDetails(runId, true);
          return;
        }
        handleErrorSnackbar(this.snackBar, err, 'Resume workflow run');
      },
    });
  }

  cancelRun(runId: string, event?: Event): void {
    event?.stopPropagation();
    const id = this.workflowId();
    if (!id) return;

    this.workflowService.cancelRun(id, runId).subscribe({
      next: () => {
        handleSuccessSnackbar(this.snackBar, 'Workflow run canceled.');
        this.loadRuns(true);
      },
      error: err => {
        handleErrorSnackbar(this.snackBar, err, 'Cancel workflow run');
      },
    });
  }

  openBatchExecution(): void {
    const id = this.workflowId();
    if (!id) return;

    const currentWorkflow = this.workflow();
    if (!currentWorkflow) {
      this.workflowService.getWorkflowById(id).subscribe(wf => {
        const workflowModel = wf as WorkflowModel;
        this.workflow.set(workflowModel);
        this.openBatchDialog(workflowModel);
      });
    } else {
      this.openBatchDialog(currentWorkflow);
    }
  }

  private openBatchDialog(workflow: WorkflowModel): void {
    const dialogRef = this.dialog.open(BatchExecutionModalComponent, {
      width: '900px',
      maxWidth: '95vw',
      maxHeight: '90vh',
      data: {
        workflow,
      },
      panelClass: 'batch-execution-modal',
    });

    dialogRef.afterClosed().subscribe(() => {
      this.loadRuns(true);
    });
  }

  runWorkflow(): void {
    const id = this.workflowId();
    if (!id || this.isLoading()) return;

    const currentWorkflow = this.workflow();
    if (currentWorkflow) {
      this.openRunDialog(currentWorkflow);
    } else {
      this.isLoading.set(true);
      this.workflowService.getWorkflowById(id).subscribe({
        next: workflow => {
          const workflowModel = workflow as WorkflowModel;
          this.isLoading.set(false);
          this.workflow.set(workflowModel);
          this.openRunDialog(workflowModel);
        },
        error: err => {
          this.isLoading.set(false);
          handleErrorSnackbar(this.snackBar, err, 'Load workflow');
        },
      });
    }
  }

  private openRunDialog(workflow: WorkflowModel): void {
    const id = this.workflowId();
    if (!id) return;

    const userInputStep = workflow.steps?.find(
      (s: WorkflowStep) => s.type === NodeTypes.USER_INPUT,
    );

    const dialogRef = this.dialog.open(RunWorkflowModalComponent, {
      width: '600px',
      data: {userInputStep},
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.isLoading.set(true);
        this.workflowService.executeWorkflow(id, result).subscribe({
          next: res => {
            this.isLoading.set(false);
            const isQueued = res.status === WorkflowRunStatusEnum.QUEUED;
            handleSuccessSnackbar(
              this.snackBar,
              isQueued ? 'Workflow run queued!' : 'Workflow execution started!',
            );
            this.loadRuns(true);
          },
          error: err => {
            this.isLoading.set(false);
            handleErrorSnackbar(this.snackBar, err, 'Workflow execution');
          },
        });
      }
    });
  }

  private startPolling(): void {
    const id = this.workflowId();
    if ((this.pollingSubscription && !this.pollingSubscription.closed) || !id) {
      return;
    }

    const sub = new Subscription();
    this.pollingSubscription = sub;
    sub.add(
      this.pollingService
        .pollRuns(id, this.pageSize, this.selectedStatus())
        .subscribe({
          next: updatedRuns => this.handlePollingUpdate(updatedRuns),
          error: err => console.error('Polling error', err),
          complete: () => {
            this.pollingSubscription = null;
          },
        }),
    );
  }

  private stopPolling(): void {
    if (this.pollingSubscription) {
      this.pollingSubscription.unsubscribe();
      this.pollingSubscription = null;
    }
  }

  private checkAndStartPolling(runs: WorkflowRunSummary[]): void {
    const hasActive = runs.some(r => isNonTerminalRunStatus(r.status));
    if (hasActive) {
      this.startPolling();
    } else {
      this.stopPolling();
    }
  }

  private handlePollingUpdate(updatedRuns: WorkflowRunSummary[]): void {
    if (!updatedRuns || updatedRuns.length === 0) return;

    const existing = this.runs();
    const currentIds = new Set(existing.map(r => r.id));
    const newRuns = updatedRuns.filter(r => !currentIds.has(r.id));

    const merged = existing.map(run => {
      const updated = updatedRuns.find(u => u.id === run.id);
      return updated ? updated : run;
    });

    this.runs.set(newRuns.length > 0 ? [...newRuns, ...merged] : merged);
    const hasActive = updatedRuns.some(r => isNonTerminalRunStatus(r.status));
    if (!hasActive) {
      this.stopPolling();
    }
  }

  private toRunRowViewModel(
    run: WorkflowRunSummary,
    returnUrl: string,
  ): ExecutionRunRowViewModel {
    const status = run.status;
    const statusLabel = RUN_STATUS_LABELS[status] ?? status;

    const queuePosition = run.queue_position ?? run.queuePosition ?? null;
    const queuePositionLabel =
      status === WorkflowRunStatusEnum.QUEUED &&
      queuePosition !== null &&
      queuePosition > 0
        ? `#${queuePosition} in queue`
        : null;

    const queueReason = (run.queue_reason ??
      run.queueReason ??
      null) as QueueReason | null;
    const queueReasonLabel =
      status === WorkflowRunStatusEnum.QUEUED && queueReason
        ? (QUEUE_REASON_LABELS[queueReason] ?? queueReason)
        : null;

    const attemptCount = run.attempt_count ?? run.attemptCount ?? 0;
    const startedAt =
      run.started_at ??
      run.startedAt ??
      run.created_at ??
      run.createdAt ??
      null;

    let durationSeconds: number | null = run.duration ?? null;
    const completedAt = run.completed_at ?? run.completedAt ?? null;
    if (durationSeconds === null && startedAt && completedAt) {
      const startMs = Date.parse(startedAt);
      const endMs = Date.parse(completedAt);
      if (!Number.isNaN(startMs) && !Number.isNaN(endMs) && endMs >= startMs) {
        durationSeconds = Math.round((endMs - startMs) / 1000);
      }
    }

    const lastErrorCategory =
      run.last_error_category ?? run.lastErrorCategory ?? null;
    const lastErrorDetail =
      run.last_error_detail ?? run.lastErrorDetail ?? null;

    const canResume = status === WorkflowRunStatusEnum.NEEDS_ATTENTION;
    const canCancel =
      status === WorkflowRunStatusEnum.QUEUED ||
      status === WorkflowRunStatusEnum.RUNNING ||
      status === WorkflowRunStatusEnum.STEP_FAILED ||
      status === WorkflowRunStatusEnum.NEEDS_ATTENTION;

    return {
      id: run.id,
      status,
      statusLabel,
      queuePositionLabel,
      queueReasonLabel,
      attemptCount,
      startedAt,
      durationSeconds,
      lastErrorCategory,
      lastErrorDetail,
      canResume,
      canCancel,
      snapshotQueryParams: {
        runId: run.id,
        executionId: run.id,
        returnUrl,
      },
      raw: run,
    };
  }
}
