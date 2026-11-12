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

import {Component, Inject, computed, inject, signal} from '@angular/core';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import * as Papa from 'papaparse';
import {Subscription} from 'rxjs';
import {take} from 'rxjs/operators';
import {
  ConfirmationDialogComponent,
  ConfirmationDialogData,
} from '../../../common/components/confirmation-dialog/confirmation-dialog.component';
import {
  FolderSelectionResult,
  FolderTreeNode,
} from '../../../common/models/folder.model';
import {FolderService} from '../../../common/services/folder.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {RunFolderService} from '../../shared/run-folder.service';
import {
  FolderChildLookup,
  buildFolderChildLookup,
  getFolderInputNames,
  resolveFolderPathInTree,
} from '../../utils/folder-path.util';
import {workflowHasLoopStep} from '../../utils/workflow-loop.util';
import {
  FolderIndex,
  buildFolderIndex,
} from '../../workflow-editor/step-components/step-configs/folder-setting.util';
import {
  BatchItemResult,
  BatchItemStatus,
  NodeTypes,
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

/** Number of leading CSV rows always shown in the preview. */
export const BATCH_PREVIEW_ROW_LIMIT = 5;

export type FolderTreeLoadStatus = 'idle' | 'loading' | 'loaded' | 'error';

export type BatchFolderCellStatus = 'valid' | 'invalid' | 'pending';

/** A CSV cell mapped to a Folder parameter, resolved to a folder id. */
export interface BatchFolderCellViewModel {
  key: string;
  rowIndex: number;
  header: string;
  inputName: string;
  rawValue: string;
  folderId: number | null;
  status: BatchFolderCellStatus;
  label: string;
  statusIcon: string;
  statusClass: string;
  tooltip: string;
  buttonId: string;
}

export interface BatchPreviewCellViewModel {
  header: string;
  text: string;
  isMapped: boolean;
  /** Folder state when the column is mapped to a Folder parameter. */
  folder: BatchFolderCellViewModel | null;
}

export interface BatchPreviewRowViewModel {
  rowIndex: number;
  rowNumber: number;
  cells: BatchPreviewCellViewModel[];
}

/** Key of a folder cell in {@link BatchExecutionModalComponent.folderCells}. */
export function toBatchFolderCellKey(rowIndex: number, header: string): string {
  return `${rowIndex}::${header}`;
}

interface BatchFolderColumn {
  header: string;
  inputName: string;
}

type BatchFolderCellMap = ReadonlyMap<string, BatchFolderCellViewModel>;

type BatchFolderCellResolution = Pick<
  BatchFolderCellViewModel,
  'folderId' | 'status' | 'label' | 'tooltip'
>;

interface BatchFolderResolutionContext {
  overrides: ReadonlyMap<string, FolderSelectionResult>;
  treeStatus: FolderTreeLoadStatus;
  lookup: FolderChildLookup | null;
  index: FolderIndex | null;
}

const FOLDER_CELL_STATUS_ICONS: Readonly<
  Record<BatchFolderCellStatus, string>
> = {
  valid: '✅',
  invalid: '⚠️',
  pending: '…',
};

const EMPTY_FOLDER_PATH_LABEL = 'Empty folder path';

function toCellText(value: unknown): string {
  return value === null || value === undefined ? '' : String(value);
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
  readonly headersSignal = signal<string[]>([]);
  isProcessing = false;
  validationErrors: string[] = [];

  expectedInputs: string[] = [];
  readonly columnMappingSignal = signal<Record<string, string | null>>({});
  isValid = false;

  get headers(): string[] {
    return this.headersSignal();
  }
  set headers(value: string[]) {
    this.headersSignal.set(value);
  }

  /** Assign a new object to update it (in-place mutations are not tracked). */
  get columnMapping(): Record<string, string | null> {
    return this.columnMappingSignal();
  }
  set columnMapping(value: Record<string, string | null>) {
    this.columnMappingSignal.set(value);
  }

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

  /** Folder parameters of the workflow's user input step. */
  readonly folderInputNames: ReadonlySet<string>;
  /** Active workspace folder tree; kept when a refresh fails. */
  readonly folderTree = signal<FolderTreeNode[] | null>(null);
  readonly folderTreeStatus = signal<FolderTreeLoadStatus>('idle');
  /** Folders picked per cell; they win over the CSV path. */
  readonly folderOverrides = signal<ReadonlyMap<string, FolderSelectionResult>>(
    new Map(),
  );

  private readonly folderService = inject(FolderService);
  private readonly runFolderService = inject(RunFolderService);
  private folderTreeSubscription: Subscription | null = null;

  private readonly folderLookup = computed<FolderChildLookup | null>(() => {
    const tree = this.folderTree();
    return tree ? buildFolderChildLookup(tree) : null;
  });

  private readonly folderIndex = computed<FolderIndex | null>(() => {
    const tree = this.folderTree();
    return tree ? buildFolderIndex(tree) : null;
  });

  /** CSV columns mapped to a folder parameter. */
  readonly folderColumns = computed<readonly BatchFolderColumn[]>(() => {
    const mapping = this.columnMappingSignal();
    return this.headersSignal().flatMap(header => {
      const inputName = mapping[header];
      return inputName && this.folderInputNames.has(inputName)
        ? [{header, inputName}]
        : [];
    });
  });

  /** One resolved folder cell per row × folder column, over all rows. */
  readonly folderCells = computed<BatchFolderCellMap>(() => {
    const columns = this.folderColumns();
    const cells = new Map<string, BatchFolderCellViewModel>();
    if (columns.length === 0) return cells;
    const context: BatchFolderResolutionContext = {
      overrides: this.folderOverrides(),
      treeStatus: this.folderTreeStatus(),
      lookup: this.folderLookup(),
      index: this.folderIndex(),
    };
    this.parsedItemsSignal().forEach((row, rowIndex) => {
      columns.forEach(column => {
        const cell = this.buildFolderCell(
          rowIndex,
          column,
          toCellText(row[column.header]),
          context,
        );
        cells.set(cell.key, cell);
      });
    });
    return cells;
  });

  /** Folder cells that are not resolved yet (pending also blocks Run). */
  readonly unresolvedFolderCellCount = computed<number>(() => {
    let count = 0;
    this.folderCells().forEach(cell => {
      if (cell.status !== 'valid') count++;
    });
    return count;
  });

  readonly hasUnresolvedFolderCells = computed<boolean>(
    () => this.unresolvedFolderCellCount() > 0,
  );

  readonly showFolderTreeError = computed<boolean>(
    () =>
      this.folderColumns().length > 0 && this.folderTreeStatus() === 'error',
  );

  readonly folderIssuesText = computed<string | null>(() => {
    if (this.folderColumns().length === 0) return null;
    if (this.folderTreeStatus() === 'loading') return 'Checking folder paths…';
    const count = this.unresolvedFolderCellCount();
    if (count === 0) return null;
    const noun = count === 1 ? 'folder cell needs' : 'folder cells need';
    return `${count} ${noun} a folder. Click a ⚠️ cell to choose one.`;
  });

  /** First rows plus any later row with a folder cell that is not resolved. */
  readonly previewRows = computed<BatchPreviewRowViewModel[]>(() => {
    const headers = this.headersSignal();
    const mapping = this.columnMappingSignal();
    const cells = this.folderCells();
    const columns = this.folderColumns();
    const rows: BatchPreviewRowViewModel[] = [];
    this.parsedItemsSignal().forEach((row, rowIndex) => {
      const hasFolderIssue = columns.some(
        column =>
          cells.get(toBatchFolderCellKey(rowIndex, column.header))?.status !==
          'valid',
      );
      if (rowIndex >= BATCH_PREVIEW_ROW_LIMIT && !hasFolderIssue) return;
      rows.push({
        rowIndex,
        rowNumber: rowIndex + 1,
        cells: headers.map(header => ({
          header,
          text: toCellText(row[header]),
          isMapped: !!mapping[header],
          folder: cells.get(toBatchFolderCellKey(rowIndex, header)) ?? null,
        })),
      });
    });
    return rows;
  });

  readonly previewFooterText = computed<string | null>(() => {
    const total = this.parsedItemsSignal().length;
    const shown = this.previewRows().length;
    if (shown >= total) return null;
    return shown > BATCH_PREVIEW_ROW_LIMIT
      ? `Showing ${shown} of ${total} rows (first ${BATCH_PREVIEW_ROW_LIMIT} and rows needing a folder)`
      : `Showing first ${BATCH_PREVIEW_ROW_LIMIT} of ${total} rows`;
  });

  readonly trackPreviewRow = (
    _index: number,
    row: BatchPreviewRowViewModel,
  ): number => row.rowIndex;

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
    this.folderInputNames = getFolderInputNames(
      this.workflow?.steps?.find(s => s.type === NodeTypes.USER_INPUT),
    );
    this.extractExpectedInputs();
  }

  extractExpectedInputs(): void {
    const userInputStep = this.workflow?.steps?.find(
      s => s.type === NodeTypes.USER_INPUT,
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
      if (target) {
        target.value = '';
      }
    }
  }

  parseCsv(file: File): void {
    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      complete: (result: Papa.ParseResult<Record<string, unknown>>) => {
        this.headers = result.meta.fields || [];
        this.parsedItems = result.data || [];
        this.folderOverrides.set(new Map());
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
    const mapping: Record<string, string | null> = {};

    this.headers.forEach(header => {
      const normalized = this.normalizeHeader(header);
      if (this.expectedInputs.includes(normalized)) {
        mapping[header] = normalized;
        usedInputs.add(normalized);
      } else if (this.expectedInputs.includes(header)) {
        mapping[header] = header;
        usedInputs.add(header);
      } else {
        mapping[header] = null;
      }
    });
    // A new object so the signal-backed mapping notifies its readers.
    this.columnMapping = mapping;

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

    if (this.folderColumns().length > 0) {
      this.loadFolderTree();
    }
  }

  normalizeHeader(header: string): string {
    return header.trim().toLowerCase().replace(/\s+/g, '_');
  }

  /**
   * Loads the active workspace's folder tree used to resolve folder paths.
   * A failed refresh keeps the previous tree; the error state is only shown
   * when there is no tree at all.
   */
  loadFolderTree(): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    this.folderTreeSubscription?.unsubscribe();
    if (workspaceId === null) {
      if (!this.folderTree()) this.folderTreeStatus.set('error');
      return;
    }
    if (!this.folderTree()) this.folderTreeStatus.set('loading');
    this.folderTreeSubscription = this.folderService
      .getFolderTree(workspaceId)
      .pipe(take(1))
      .subscribe({
        next: tree => {
          this.folderTree.set(tree ?? []);
          this.folderTreeStatus.set('loaded');
        },
        error: (err: unknown) => {
          console.warn('Failed to load folder tree', err);
          if (!this.folderTree()) this.folderTreeStatus.set('error');
        },
      });
  }

  /**
   * Opens the folder picker for one folder cell. The tree is refreshed after
   * close (folders may change in the picker); a selection overrides the cell.
   */
  openFolderPickerForCell(cell: BatchFolderCellViewModel): void {
    this.runFolderService.pickFolder(cell.folderId).subscribe(selection => {
      this.loadFolderTree();
      if (!selection) return;
      this.folderOverrides.update(overrides =>
        new Map(overrides).set(cell.key, selection),
      );
    });
  }

  /** Display state of one folder cell, following the resolution rules in order. */
  private buildFolderCell(
    rowIndex: number,
    column: BatchFolderColumn,
    rawValue: string,
    context: BatchFolderResolutionContext,
  ): BatchFolderCellViewModel {
    const key = toBatchFolderCellKey(rowIndex, column.header);
    const resolution = this.resolveFolderCell(key, rawValue, context);
    return {
      key,
      rowIndex,
      header: column.header,
      inputName: column.inputName,
      rawValue,
      ...resolution,
      statusIcon: FOLDER_CELL_STATUS_ICONS[resolution.status],
      statusClass: `batch-folder-cell--${resolution.status}`,
      buttonId: `batch-folder-cell-${rowIndex}-${column.inputName}`,
    };
  }

  private resolveFolderCell(
    key: string,
    rawValue: string,
    context: BatchFolderResolutionContext,
  ): BatchFolderCellResolution {
    const override = context.overrides.get(key);
    if (override) {
      return {
        folderId: override.folderId,
        status: 'valid',
        label: override.path,
        tooltip: `${override.path}. Click to choose another folder.`,
      };
    }
    if (context.treeStatus === 'error') {
      return {
        folderId: null,
        status: 'invalid',
        label: rawValue || EMPTY_FOLDER_PATH_LABEL,
        tooltip: 'Folders could not be loaded. Click to choose a folder.',
      };
    }
    if (!context.lookup) {
      return {
        folderId: null,
        status: 'pending',
        label: rawValue || EMPTY_FOLDER_PATH_LABEL,
        tooltip: 'Checking folder path…',
      };
    }
    if (!rawValue.trim()) {
      return {
        folderId: null,
        status: 'invalid',
        label: EMPTY_FOLDER_PATH_LABEL,
        tooltip: `${EMPTY_FOLDER_PATH_LABEL}. Click to choose a folder.`,
      };
    }
    const folderId = resolveFolderPathInTree(context.lookup, rawValue);
    if (folderId !== null) {
      const path = context.index?.get(folderId)?.path ?? rawValue;
      return {
        folderId,
        status: 'valid',
        label: path,
        tooltip: `${path}. Click to choose another folder.`,
      };
    }
    return {
      folderId: null,
      status: 'invalid',
      label: rawValue,
      tooltip: `"${rawValue}" not found. Click to choose a folder.`,
    };
  }

  /**
   * Starts the batch. When the saved workflow contains a Loop, a confirmation
   * dialog warns about the cost first and the batch is only submitted on
   * Continue.
   */
  runBatch(): void {
    if (!this.isValid || this.parsedItems.length === 0) return;
    if (this.isProcessing || this.isConfirmingBatch()) return;
    if (this.hasUnresolvedFolderCells()) return;

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
    if (this.hasUnresolvedFolderCells()) return;
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

        const columnMapping = this.columnMapping;
        const folderCells = this.folderCells();
        const items = this.parsedItems.map((row, index) => {
          const args: Record<string, unknown> = {
            workspace_id: workspaceId,
          };

          Object.keys(row).forEach(header => {
            const mappedInput = columnMapping[header];
            if (mappedInput) {
              // Folder cells hold paths in the CSV; the run receives the id.
              const folderCell = folderCells.get(
                toBatchFolderCellKey(index, header),
              );
              args[mappedInput] = folderCell
                ? folderCell.folderId
                : row[header];
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
