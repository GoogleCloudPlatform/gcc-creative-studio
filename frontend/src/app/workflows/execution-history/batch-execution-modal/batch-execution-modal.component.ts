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

import {Component, Inject, computed, signal} from '@angular/core';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import * as Papa from 'papaparse';
import {take} from 'rxjs/operators';
import {
  ConfirmationDialogComponent,
  ConfirmationDialogData,
} from '../../../common/components/confirmation-dialog/confirmation-dialog.component';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {workflowHasLoopStep} from '../../utils/workflow-loop.util';
import {
  BatchItemResult,
  BatchItemStatus,
  QUEUE_REASON_LABELS,
  QueueReason,
  WorkflowModel,
} from '../../workflow.models';
import {WorkflowService} from '../../workflow.service';

/** Confirmation shown before a batch run of a workflow that contains a Loop. */
export const LOOP_BATCH_WARNING: ConfirmationDialogData = {
  title: 'Run batch with a Loop?',
  message:
    'This workflow contains a Loop. Each batch row runs every loop iteration, which can trigger many generations and incur significant cost. Continue?',
  confirmLabel: 'Continue',
  confirmColor: 'primary',
};

export interface BatchResultRowViewModel {
  rowNumber: number;
  status: BatchItemStatus;
  statusLabel: string;
  runId: string | null;
  executionId: string | null;
  queueReasonLabel: string | null;
  error: string | null;
}

@Component({
  selector: 'app-batch-execution-modal',
  templateUrl: './batch-execution-modal.component.html',
  styleUrls: ['./batch-execution-modal.component.scss'],
})
export class BatchExecutionModalComponent {
  workflow: WorkflowModel;
  /** The saved workflow never changes while the modal is open. */
  readonly hasLoopStep: boolean;
  /** True while the Loop batch warning is open (blocks double submissions). */
  readonly isConfirmingBatch = signal<boolean>(false);

  csvFile: File | null = null;
  headers: string[] = [];
  isProcessing = false;
  validationErrors: string[] = [];

  expectedInputs: string[] = [];
  columnMapping: Record<string, string | null> = {};
  isValid = false;

  readonly parsedItemsSignal = signal<Record<string, unknown>[]>([]);
  readonly missingInputsSignal = signal<string[]>([]);
  readonly resultsSignal = signal<BatchItemResult[]>([]);

  get parsedItems(): Record<string, unknown>[] {
    return this.parsedItemsSignal();
  }
  set parsedItems(value: Record<string, unknown>[]) {
    this.parsedItemsSignal.set(value);
  }

  get missingInputs(): string[] {
    return this.missingInputsSignal();
  }
  set missingInputs(value: string[]) {
    this.missingInputsSignal.set(value);
  }

  get results(): BatchItemResult[] {
    return this.resultsSignal();
  }
  set results(value: BatchItemResult[]) {
    this.resultsSignal.set(value);
  }

  readonly previewItems = computed<Record<string, unknown>[]>(() =>
    this.parsedItemsSignal().slice(0, 5),
  );

  readonly missingInputsText = computed<string>(() =>
    this.missingInputsSignal().join(', '),
  );

  readonly successCountSignal = computed<number>(
    () =>
      this.resultsSignal().filter(r => {
        const runSt = (r.run_status ?? r.runStatus ?? '').toLowerCase();
        return r.status === 'SUCCESS' && runSt !== 'queued';
      }).length,
  );

  readonly queuedCountSignal = computed<number>(
    () =>
      this.resultsSignal().filter(r => {
        const runSt = (r.run_status ?? r.runStatus ?? '').toLowerCase();
        return (
          r.status === 'QUEUED' ||
          (r.status === 'SUCCESS' && runSt === 'queued')
        );
      }).length,
  );

  readonly failureCountSignal = computed<number>(
    () => this.resultsSignal().filter(r => r.status === 'FAILED').length,
  );

  get successCount(): number {
    return this.successCountSignal();
  }

  get queuedCount(): number {
    return this.queuedCountSignal();
  }

  get failureCount(): number {
    return this.failureCountSignal();
  }

  readonly resultRows = computed<BatchResultRowViewModel[]>(() =>
    this.resultsSignal().map(res => {
      const runSt = (res.run_status ?? res.runStatus ?? '').toLowerCase();
      const isQueued =
        res.status === 'QUEUED' ||
        (res.status === 'SUCCESS' && runSt === 'queued');
      const status: BatchItemStatus = isQueued
        ? 'QUEUED'
        : res.status === 'SUCCESS'
          ? 'SUCCESS'
          : 'FAILED';
      const statusLabel =
        status === 'SUCCESS'
          ? 'SUBMITTED'
          : status === 'QUEUED'
            ? 'QUEUED'
            : 'FAILED';
      const runId =
        res.run_id ?? res.runId ?? res.execution_id ?? res.executionId ?? null;
      const executionId = res.execution_id ?? res.executionId ?? null;
      const rawQueueReason = (res.queue_reason ??
        res.queueReason ??
        null) as QueueReason | null;
      const queueReasonLabel =
        isQueued && rawQueueReason
          ? (QUEUE_REASON_LABELS[rawQueueReason] ?? rawQueueReason)
          : null;

      return {
        rowNumber: (res.row_index ?? res.rowIndex ?? 0) + 1,
        status,
        statusLabel,
        runId,
        executionId,
        queueReasonLabel,
        error: res.error ?? null,
      };
    }),
  );

  constructor(
    public dialogRef: MatDialogRef<BatchExecutionModalComponent>,
    @Inject(MAT_DIALOG_DATA) public data: {workflow: WorkflowModel},
    private workflowService: WorkflowService,
    private workspaceStateService: WorkspaceStateService,
    private dialog: MatDialog,
  ) {
    this.workflow = data.workflow;
    this.hasLoopStep = workflowHasLoopStep(this.workflow);
    this.extractExpectedInputs();
  }

  extractExpectedInputs(): void {
    const userInputStep = this.workflow?.steps?.find(
      s => s.type === 'user_input',
    );
    if (userInputStep && userInputStep.outputs) {
      this.expectedInputs = Object.keys(userInputStep.outputs);
    }
  }

  onFileSelected(event: Event): void {
    const target = event.target as HTMLInputElement | null;
    const file = target?.files?.[0] ?? null;
    if (file) {
      this.csvFile = file;
      this.parseCsv(file);
    }
  }

  parseCsv(file: File): void {
    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      complete: (result: Papa.ParseResult<Record<string, unknown>>) => {
        this.headers = result.meta.fields || [];
        this.parsedItems = result.data || [];
        this.validateHeaders();
      },
      error: (error: Error) => {
        this.validationErrors = [`CSV Parse Error: ${error.message}`];
      },
    });
  }

  validateHeaders(): void {
    this.validationErrors = [];
    const nextMissing: string[] = [];
    this.columnMapping = {};
    this.isValid = false;

    if (this.parsedItems.length === 0) {
      this.missingInputs = [];
      this.validationErrors.push('CSV is empty');
      return;
    }

    const usedInputs = new Set<string>();

    this.headers.forEach(header => {
      const normalized = this.normalizeHeader(header);
      if (this.expectedInputs.includes(normalized)) {
        this.columnMapping[header] = normalized;
        usedInputs.add(normalized);
      } else if (this.expectedInputs.includes(header)) {
        this.columnMapping[header] = header;
        usedInputs.add(header);
      } else {
        this.columnMapping[header] = null;
      }
    });

    this.expectedInputs.forEach(input => {
      if (!usedInputs.has(input)) {
        nextMissing.push(input);
      }
    });
    this.missingInputs = nextMissing;

    if (nextMissing.length > 0) {
      this.validationErrors.push(
        `Missing required columns: ${nextMissing.join(', ')}`,
      );
    }

    if (this.validationErrors.length === 0) {
      this.isValid = true;
    }
  }

  normalizeHeader(header: string): string {
    return header.trim().toLowerCase().replace(/\s+/g, '_');
  }

  /**
   * Starts the batch. When the saved workflow contains a Loop, a confirmation
   * dialog warns about the cost first and the batch is only submitted on
   * Continue.
   */
  runBatch(): void {
    if (!this.isValid || this.parsedItems.length === 0) return;
    if (this.isProcessing || this.isConfirmingBatch()) return;

    if (!this.hasLoopStep) {
      this.submitBatch();
      return;
    }

    this.isConfirmingBatch.set(true);
    this.dialog
      .open<ConfirmationDialogComponent, ConfirmationDialogData, boolean>(
        ConfirmationDialogComponent,
        {data: LOOP_BATCH_WARNING},
      )
      .afterClosed()
      .pipe(take(1))
      .subscribe(confirmed => {
        this.isConfirmingBatch.set(false);
        if (confirmed === true) {
          this.submitBatch();
        }
      });
  }

  /** Submits every mapped CSV row as one batch execution. */
  submitBatch(): void {
    this.isProcessing = true;
    this.results = [];

    this.workspaceStateService.activeWorkspaceId$
      .pipe(take(1))
      .subscribe(workspaceId => {
        if (!workspaceId) {
          this.validationErrors.push('No active workspace found.');
          this.isProcessing = false;
          return;
        }

        const items = this.parsedItems.map((row, index) => {
          const args: Record<string, unknown> = {
            workspace_id: workspaceId,
          };

          Object.keys(row).forEach(header => {
            const mappedInput = this.columnMapping[header];
            if (mappedInput) {
              args[mappedInput] = row[header];
            }
          });

          return {
            row_index: index,
            args,
          };
        });

        this.workflowService
          .batchExecuteWorkflow(this.workflow.id, items)
          .subscribe({
            next: response => {
              this.results = response?.results ?? [];
              this.isProcessing = false;
            },
            error: err => {
              console.error('Batch execution failed', err);
              this.validationErrors.push(`Server Error: ${err.message}`);
              this.isProcessing = false;
            },
          });
      });
  }

  close(): void {
    this.dialogRef.close();
  }
}
