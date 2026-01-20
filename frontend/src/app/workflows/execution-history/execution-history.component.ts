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

import { Component, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ActivatedRoute } from '@angular/router';
import { handleErrorSnackbar, handleSuccessSnackbar } from '../../utils/handleMessageSnackbar';
import { RunWorkflowModalComponent } from '../workflow-editor/run-workflow-modal/run-workflow-modal.component';
import { NodeTypes } from '../workflow.models';
import { WorkflowService } from '../workflow.service';
import { ExecutionDetailsModalComponent } from './execution-details-modal/execution-details-modal.component';

@Component({
    selector: 'app-execution-history',
    templateUrl: './execution-history.component.html',
    styleUrls: ['./execution-history.component.scss']
})
export class ExecutionHistoryComponent implements OnInit {
    workflowId: string | null = null;
    workflow: any | null = null;
    executions: any[] = [];
    isLoading = false;
    nextPageToken: string | null = null;
    displayedColumns: string[] = ['status', 'id', 'startTime', 'duration', 'actions'];
    selectedStatus: string = 'ALL';

    constructor(
        private route: ActivatedRoute,
        private workflowService: WorkflowService,
        private dialog: MatDialog,
        private snackBar: MatSnackBar
    ) { }

    ngOnInit(): void {
        this.route.paramMap.subscribe(params => {
            this.workflowId = params.get('id');
            if (this.workflowId) {
                this.loadWorkflow();
                this.loadExecutions(true);
            }
        });
    }

    loadWorkflow(): void {
        if (!this.workflowId) return;
        this.workflowService.getWorkflowById(this.workflowId).subscribe({
            next: (workflow) => {
                this.workflow = workflow;
            },
            error: (err) => {
                console.error('Failed to load workflow details', err);
                handleErrorSnackbar(this.snackBar, err, 'Load workflow details');
            }
        });
    }

    loadExecutions(reset: boolean = false): void {
        if (!this.workflowId || this.isLoading) return;

        this.isLoading = true;
        const pageToken = reset ? undefined : (this.nextPageToken || undefined);

        this.workflowService.getExecutions(this.workflowId, 20, pageToken, this.selectedStatus).subscribe({
            next: (response) => {
                if (reset) {
                    this.executions = response.executions;
                } else {
                    this.executions = [...this.executions, ...response.executions];
                }
                this.nextPageToken = response.next_page_token || null;
                this.isLoading = false;
            },
            error: (err) => {
                console.error('Failed to load executions', err);
                this.isLoading = false;
            }
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
            maxHeight: '90vh',
            data: {
                workflowId: this.workflowId,
                executionId: executionId
            },
            panelClass: 'execution-details-modal'
        });
    }

    getStatusClass(state: string): string {
        switch (state) {
            case 'SUCCEEDED': return '!bg-green-500/20 !text-green-300';
            case 'FAILED': return '!bg-red-500/20 !text-red-300';
            case 'ACTIVE': return '!bg-blue-500/20 !text-blue-300';
            default: return '!bg-gray-500/20 !text-gray-300';
        }
    }

    getStatusIcon(state: string): string {
        switch (state) {
            case 'SUCCEEDED': return 'check_circle';
            case 'FAILED': return 'error';
            case 'ACTIVE': return 'hourglass_top';
            default: return 'help_outline';
        }
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
                error: (err) => {
                    this.isLoading = false;
                    handleErrorSnackbar(this.snackBar, err, 'Load workflow');
                }
            });
        }
    }

    private openRunDialog(workflow: any): void {
        const userInputStep = workflow.steps?.find((s: any) => s.type === NodeTypes.USER_INPUT);

        const dialogRef = this.dialog.open(RunWorkflowModalComponent, {
            width: '600px',
            data: { userInputStep }
        });

        dialogRef.afterClosed().subscribe(result => {
            if (result) {
                this.isLoading = true;
                this.workflowService.executeWorkflow(this.workflowId!, result).subscribe({
                    next: (res) => {
                        this.isLoading = false;
                        handleSuccessSnackbar(this.snackBar, 'Workflow execution started!');
                        this.loadExecutions(true);
                    },
                    error: (err) => {
                        this.isLoading = false;
                        handleErrorSnackbar(this.snackBar, err, 'Workflow execution');
                    }
                });
            }
        });
    }
}
