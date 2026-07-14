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

import {Component, OnInit, OnDestroy} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {ActivatedRoute} from '@angular/router';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../utils/handleMessageSnackbar';
import {RunWorkflowModalComponent} from '../workflow-editor/run-workflow-modal/run-workflow-modal.component';
import {NodeTypes} from '../workflow.models';
import {WorkflowService} from '../workflow.service';
import {WorkflowExecutionPollingService} from './workflow-execution-polling.service';
import {Subscription} from 'rxjs';
import {BatchExecutionModalComponent} from './batch-execution-modal/batch-execution-modal.component';
import {ExecutionDetailsModalComponent} from './execution-details-modal/execution-details-modal.component';
import {AuthService} from '../../common/services/auth.service';

@Component({
  selector: 'app-execution-history',
  templateUrl: './execution-history.component.html',
  styleUrls: ['./execution-history.component.scss'],
})
export class ExecutionHistoryComponent implements OnInit, OnDestroy {
  workflowId: string | null = null;
  workflow: any | null = null;
  executions: any[] = [];
  isLoading = false;
  nextPageToken: string | null = null;
  displayedColumns: string[] = [
    'status',
    'id',
    'startTime',
    'duration',
    'actions',
  ];
  selectedStatus = 'ALL';
  private pollingSubscription: Subscription | null = null;

  constructor(
    private route: ActivatedRoute,
    private workflowService: WorkflowService,
    private pollingService: WorkflowExecutionPollingService,
    private dialog: MatDialog,
    private snackBar: MatSnackBar,
    public authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.route.paramMap.subscribe(params => {
      this.workflowId = params.get('id');
      if (this.workflowId) {
        this.loadWorkflow();
        this.loadExecutions(true);
      }
    });
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }

  loadWorkflow(): void {
    if (!this.workflowId) return;
    this.workflowService.getWorkflowById(this.workflowId).subscribe({
      next: workflow => {
        this.workflow = workflow;
      },
      error: err => {
        console.error('Failed to load workflow details', err);
        handleErrorSnackbar(this.snackBar, err, 'Load workflow details');
      },
    });
  }

  loadExecutions(reset = false): void {
    if (!this.workflowId || this.isLoading) return;

    this.isLoading = true;
    const pageToken = reset ? undefined : this.nextPageToken || undefined;

    this.workflowService
      .getExecutions(this.workflowId, 20, pageToken, this.selectedStatus)
      .subscribe({
        next: response => {
          if (reset) {
            this.executions = response.executions;
          } else {
            this.executions = [...this.executions, ...response.executions];
          }
          this.nextPageToken = response.next_page_token || null;
          this.isLoading = false;

          // Check if we need to start polling
          this.checkAndStartPolling(this.executions);
        },
        error: err => {
          console.error('Failed to load executions', err);
          this.isLoading = false;
        },
      });
  }

  loadMore(): void {
    if (this.nextPageToken) {
      this.loadExecutions(false);
    }
  }

  onStatusChange(): void {
    this.loadExecutions(true);
  }

  openDetails(executionId: string): void {
    if (!this.workflowId) return;

    this.dialog.open(ExecutionDetailsModalComponent, {
      width: '800px',
      maxWidth: '90vw',
      maxHeight: '90vh',
      data: {
        workflowId: this.workflowId,
        executionId: executionId,
      },
      panelClass: 'execution-details-modal',
    });
  }

  openBatchExecution(): void {
    if (!this.workflowId) return;

    // Ensure workflow is loaded
    if (!this.workflow) {
      this.workflowService.getWorkflowById(this.workflowId).subscribe(wf => {
        this.workflow = wf;
        this.openBatchDialog();
      });
    } else {
      this.openBatchDialog();
    }
  }

  private openBatchDialog(): void {
    this.dialog.open(BatchExecutionModalComponent, {
      width: '900px',
      maxWidth: '95vw',
      maxHeight: '90vh',
      data: {
        workflow: this.workflow,
      },
      panelClass: 'batch-execution-modal',
    });
  }

  runWorkflow(): void {
    if (!this.workflowId || this.isLoading) return;

    // Use the already loaded workflow if available, otherwise fetch it (though it should be loaded)
    if (this.workflow) {
      this.openRunDialog(this.workflow);
    } else {
      this.isLoading = true;
      this.workflowService.getWorkflowById(this.workflowId).subscribe({
        next: (workflow: any) => {
          this.isLoading = false;
          this.openRunDialog(workflow);
        },
        error: err => {
          this.isLoading = false;
          handleErrorSnackbar(this.snackBar, err, 'Load workflow');
        },
      });
    }
  }

  private openRunDialog(workflow: any): void {
    const userInputStep = workflow.steps?.find(
      (s: any) => s.type === NodeTypes.USER_INPUT,
    );

    const dialogRef = this.dialog.open(RunWorkflowModalComponent, {
      width: '600px',
      data: {userInputStep},
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.isLoading = true;
        this.workflowService
          .executeWorkflow(this.workflowId!, result)
          .subscribe({
            next: res => {
              this.isLoading = false;
              handleSuccessSnackbar(
                this.snackBar,
                'Workflow execution started!',
              );
              this.loadExecutions(true);
              // Polling will be triggered by loadExecutions if ACTIVE
            },
            error: err => {
              this.isLoading = false;
              handleErrorSnackbar(this.snackBar, err, 'Workflow execution');
            },
          });
      }
    });
  }

  private startPolling(): void {
    if (this.pollingSubscription || !this.workflowId) return;

    this.pollingSubscription = this.pollingService
      .pollExecutions(this.workflowId)
      .subscribe({
        next: executions => this.handlePollingUpdate(executions),
        error: err => console.error('Polling error', err),
      });
  }

  private stopPolling(): void {
    if (this.pollingSubscription) {
      this.pollingSubscription.unsubscribe();
      this.pollingSubscription = null;
    }
  }

  private checkAndStartPolling(executions: any[]): void {
    const hasActive = executions.some(e => e.state === 'ACTIVE');
    if (hasActive) {
      this.startPolling();
    } else {
      this.stopPolling();
    }
  }

  private handlePollingUpdate(updatedExecutions: any[]): void {
    if (!updatedExecutions || updatedExecutions.length === 0) return;

    const currentIds = new Set(this.executions.map(e => e.id));
    const newExecutions = updatedExecutions.filter(e => !currentIds.has(e.id));

    // Update existing
    this.executions = this.executions.map(exec => {
      const updated = updatedExecutions.find(u => u.id === exec.id);
      return updated ? updated : exec;
    });

    // Prepend new
    if (newExecutions.length > 0) {
      this.executions = [...newExecutions, ...this.executions];
    }

    // Check continuously if we should stop
    this.checkAndStartPolling(updatedExecutions);
  }
}
