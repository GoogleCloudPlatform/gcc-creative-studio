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
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {By} from '@angular/platform-browser';
import {BehaviorSubject, Subject, of, throwError} from 'rxjs';
import {ConfirmationDialogComponent} from '../../../common/components/confirmation-dialog/confirmation-dialog.component';
import {
  FolderSelectionResult,
  FolderTreeNode,
} from '../../../common/models/folder.model';
import {FolderService} from '../../../common/services/folder.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {RunFolderService} from '../../shared/run-folder.service';
import {
  BatchExecutionResponse,
  NodeTypes,
  WorkflowModel,
  WorkflowStep,
} from '../../workflow.models';
import {WorkflowService} from '../../workflow.service';
import {
  BATCH_PREVIEW_ROW_LIMIT,
  BatchExecutionModalComponent,
  BatchFolderCellViewModel,
  LOOP_BATCH_WARNING,
  toBatchFolderCellKey,
} from './batch-execution-modal.component';

describe('BatchExecutionModalComponent', () => {
  let component: BatchExecutionModalComponent;
  let fixture: ComponentFixture<BatchExecutionModalComponent>;
  let workflowServiceSpy: jasmine.SpyObj<WorkflowService>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<BatchExecutionModalComponent>>;
  let dialogSpy: jasmine.SpyObj<MatDialog>;
  let confirmationClosed: Subject<boolean | undefined>;
  let activeWorkspaceIdSubject: BehaviorSubject<number | null>;
  let folderServiceSpy: jasmine.SpyObj<FolderService>;
  let runFolderServiceSpy: jasmine.SpyObj<RunFolderService>;

  const userInputStep: WorkflowStep = {
    stepId: 'user_input_1',
    type: NodeTypes.USER_INPUT,
    status: 'IDLE',
    position: {x: 100, y: 100},
    collapsed: false,
    inputs: {},
    outputs: {prompt: {type: 'text'}, aspect_ratio: {type: 'text'}},
    settings: {},
  };

  const loopStep: WorkflowStep = {
    stepId: 'loop_1',
    type: NodeTypes.LOOP,
    status: 'IDLE',
    position: {x: 300, y: 100},
    collapsed: false,
    inputs: {folder: 3},
    outputs: {},
    settings: {mode: 'folder', item_type: 'image'},
  };

  const buildWorkflow = (steps: WorkflowStep[]): WorkflowModel => ({
    id: 'wf-batch-1',
    name: 'Batch Workflow',
    description: 'Desc',
    createdAt: '2026-04-19T00:00:00Z',
    updatedAt: '2026-04-19T00:00:00Z',
    userId: '1',
    steps,
  });

  const folderUserInputStep: WorkflowStep = {
    ...userInputStep,
    outputs: {prompt: {type: 'text'}, target: {type: 'folder'}},
  };

  const FOLDER_TREE: FolderTreeNode[] = [
    {
      id: 10,
      name: 'Campaign',
      children: [{id: 42, name: 'Shoes', children: []}],
    },
    {id: 11, name: 'Archive', children: []},
  ];

  const ARCHIVE_PICK: FolderSelectionResult = {
    folderId: 11,
    folderName: 'Archive',
    path: 'Archive',
  };

  const mockWorkflow = buildWorkflow([userInputStep]);
  const folderWorkflow = buildWorkflow([folderUserInputStep]);
  const loopWorkflow = buildWorkflow([userInputStep, loopStep]);

  const batchResponse: BatchExecutionResponse = {
    total_items: 3,
    submitted_count: 2,
    failed_count: 1,
    message: 'Processed',
    results: [
      {
        row_index: 0,
        status: 'SUCCESS',
        run_id: 'run-batch-1',
        execution_id: 'exec-1',
        queue_reason: null,
      },
      {
        row_index: 1,
        status: 'QUEUED',
        run_id: 'run-batch-2',
        execution_id: null,
        queue_reason: 'concurrency_capped',
      },
      {
        row_index: 2,
        status: 'FAILED',
        run_id: null,
        execution_id: null,
        error: 'Invalid row data',
      },
    ],
  };

  const expectedItems = [
    {
      row_index: 0,
      args: {workspace_id: 42, prompt: 'First item', aspect_ratio: '16:9'},
    },
    {
      row_index: 1,
      args: {workspace_id: 42, prompt: 'Second item', aspect_ratio: '1:1'},
    },
    {
      row_index: 2,
      args: {workspace_id: 42, prompt: 'Third item', aspect_ratio: '9:16'},
    },
  ];

  async function setup(workflow: WorkflowModel): Promise<void> {
    workflowServiceSpy = jasmine.createSpyObj<WorkflowService>(
      'WorkflowService',
      ['batchExecuteWorkflow'],
    );
    workflowServiceSpy.batchExecuteWorkflow.and.returnValue(of(batchResponse));
    dialogRefSpy = jasmine.createSpyObj<
      MatDialogRef<BatchExecutionModalComponent>
    >('MatDialogRef', ['close']);
    confirmationClosed = new Subject<boolean | undefined>();
    dialogSpy = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    dialogSpy.open.and.returnValue({
      afterClosed: () => confirmationClosed.asObservable(),
    } as MatDialogRef<ConfirmationDialogComponent, boolean>);
    activeWorkspaceIdSubject = new BehaviorSubject<number | null>(42);
    folderServiceSpy = jasmine.createSpyObj<FolderService>('FolderService', [
      'getFolderTree',
    ]);
    folderServiceSpy.getFolderTree.and.returnValue(of(FOLDER_TREE));
    runFolderServiceSpy = jasmine.createSpyObj<RunFolderService>(
      'RunFolderService',
      ['pickFolder'],
    );
    runFolderServiceSpy.pickFolder.and.returnValue(of(null));

    await TestBed.configureTestingModule({
      declarations: [BatchExecutionModalComponent],
      providers: [
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {provide: MAT_DIALOG_DATA, useValue: {workflow}},
        {provide: MatDialog, useValue: dialogSpy},
        {provide: WorkflowService, useValue: workflowServiceSpy},
        {provide: FolderService, useValue: folderServiceSpy},
        {provide: RunFolderService, useValue: runFolderServiceSpy},
        {
          provide: WorkspaceStateService,
          useValue: {
            activeWorkspaceId$: activeWorkspaceIdSubject.asObservable(),
            getActiveWorkspaceId: () => activeWorkspaceIdSubject.value,
          },
        },
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(BatchExecutionModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  function loadValidCsv(): void {
    component.headers = ['Prompt', 'Aspect Ratio'];
    component.parsedItems = [
      {Prompt: 'First item', 'Aspect Ratio': '16:9'},
      {Prompt: 'Second item', 'Aspect Ratio': '1:1'},
      {Prompt: 'Third item', 'Aspect Ratio': '9:16'},
    ];
    component.validateHeaders();
  }

  describe('without a Loop step', () => {
    beforeEach(async () => {
      await setup(mockWorkflow);
    });

    it('should create and extract expected inputs from user_input step', () => {
      expect(component).toBeTruthy();
      expect(component.expectedInputs).toEqual(['prompt', 'aspect_ratio']);
      expect(component.hasLoopStep).toBeFalse();
    });

    it('should submit batch and compute successCount, queuedCount, failureCount, and resultRows with run_id', () => {
      loadValidCsv();
      expect(component.isValid).toBeTrue();

      component.runBatch();
      fixture.detectChanges();

      expect(dialogSpy.open).not.toHaveBeenCalled();
      expect(workflowServiceSpy.batchExecuteWorkflow).toHaveBeenCalledWith(
        'wf-batch-1',
        expectedItems,
      );

      expect(component.successCount).toBe(1);
      expect(component.queuedCount).toBe(1);
      expect(component.failureCount).toBe(1);

      const rows = component.resultRows();
      expect(rows.length).toBe(3);
      expect(rows[0].statusLabel).toBe('SUBMITTED');
      expect(rows[0].runId).toBe('run-batch-1');
      expect(rows[1].statusLabel).toBe('QUEUED');
      expect(rows[1].runId).toBe('run-batch-2');
      expect(rows[1].queueReasonLabel).toBe('Waiting on workflow slot');
      expect(rows[2].statusLabel).toBe('FAILED');
      expect(rows[2].error).toBe('Invalid row data');
    });
  });

  describe('with a Loop step', () => {
    beforeEach(async () => {
      await setup(loopWorkflow);
    });

    it('detects the Loop step in the saved workflow', () => {
      expect(component.hasLoopStep).toBeTrue();
    });

    it('opens the Loop warning instead of submitting directly', () => {
      loadValidCsv();

      component.runBatch();

      expect(dialogSpy.open).toHaveBeenCalledOnceWith(
        ConfirmationDialogComponent,
        {data: LOOP_BATCH_WARNING},
      );
      expect(LOOP_BATCH_WARNING.title).toBe('Run batch with a Loop?');
      expect(LOOP_BATCH_WARNING.message).toBe(
        'This workflow contains a Loop. Each batch row runs every loop iteration, which can trigger many generations and incur significant cost. Continue?',
      );
      expect(LOOP_BATCH_WARNING.confirmLabel).toBe('Continue');
      expect(LOOP_BATCH_WARNING.confirmColor).toBe('primary');
      expect(component.isConfirmingBatch()).toBeTrue();
      expect(workflowServiceSpy.batchExecuteWorkflow).not.toHaveBeenCalled();
    });

    it('submits the batch once when the user continues', () => {
      loadValidCsv();

      component.runBatch();
      confirmationClosed.next(true);

      expect(component.isConfirmingBatch()).toBeFalse();
      expect(workflowServiceSpy.batchExecuteWorkflow).toHaveBeenCalledOnceWith(
        'wf-batch-1',
        expectedItems,
      );
    });

    [false, undefined].forEach(result => {
      it(`submits nothing when the warning closes with ${result}`, () => {
        loadValidCsv();

        component.runBatch();
        confirmationClosed.next(result);

        expect(workflowServiceSpy.batchExecuteWorkflow).not.toHaveBeenCalled();
        expect(component.isProcessing).toBeFalse();
        expect(component.isConfirmingBatch()).toBeFalse();
        expect(component.results).toEqual([]);
        expect(component.isValid).toBeTrue();
      });
    });

    it('opens only one warning when Run Batch is clicked twice', () => {
      loadValidCsv();

      component.runBatch();
      component.runBatch();

      expect(dialogSpy.open).toHaveBeenCalledTimes(1);
    });

    it('opens neither the warning nor a submission for an empty CSV', () => {
      component.headers = ['Prompt', 'Aspect Ratio'];
      component.parsedItems = [];
      component.validateHeaders();

      component.runBatch();

      expect(dialogSpy.open).not.toHaveBeenCalled();
      expect(workflowServiceSpy.batchExecuteWorkflow).not.toHaveBeenCalled();
    });

    it('opens neither the warning nor a submission for invalid columns', () => {
      component.headers = ['Unknown'];
      component.parsedItems = [{Unknown: 'x'}];
      component.validateHeaders();

      component.runBatch();

      expect(component.isValid).toBeFalse();
      expect(dialogSpy.open).not.toHaveBeenCalled();
      expect(workflowServiceSpy.batchExecuteWorkflow).not.toHaveBeenCalled();
    });
  });

  describe('with a Folder parameter', () => {
    const folderCell = (
      rowIndex: number,
    ): BatchFolderCellViewModel | undefined =>
      component.folderCells().get(toBatchFolderCellKey(rowIndex, 'Target'));

    function loadFolderCsv(targets: readonly string[]): void {
      component.csvFile = new File(['csv'], 'batch.csv', {type: 'text/csv'});
      component.headers = ['Prompt', 'Target'];
      component.parsedItems = targets.map((target, index) => ({
        Prompt: `Item ${index + 1}`,
        Target: target,
      }));
      component.validateHeaders();
      fixture.detectChanges();
    }

    const runButton = (): HTMLButtonElement =>
      fixture.debugElement.query(By.css('#batch-modal-run-btn'))
        .nativeElement as HTMLButtonElement;

    beforeEach(async () => {
      await setup(folderWorkflow);
    });

    it('loads the active workspace tree only once a folder column is mapped', () => {
      expect(folderServiceSpy.getFolderTree).not.toHaveBeenCalled();
      loadFolderCsv(['Campaign / Shoes']);
      expect(folderServiceSpy.getFolderTree).toHaveBeenCalledOnceWith(42);
      expect(component.folderTreeStatus()).toBe('loaded');
    });

    it('marks a resolvable path as valid with its full path', () => {
      loadFolderCsv([' campaign / shoes ']);
      const cell = folderCell(0);

      expect(cell?.status).toBe('valid');
      expect(cell?.folderId).toBe(42);
      expect(cell?.label).toBe('Campaign / Shoes');
      expect(cell?.statusIcon).toBe('✅');
      expect(component.hasUnresolvedFolderCells()).toBeFalse();
      expect(component.folderIssuesText()).toBeNull();
    });

    it('renders folder cells as buttons with status classes and stable ids', () => {
      loadFolderCsv(['Campaign/Shoes', 'Nope']);
      const validButton = fixture.debugElement.query(
        By.css('#batch-folder-cell-0-target'),
      ).nativeElement as HTMLButtonElement;
      const invalidButton = fixture.debugElement.query(
        By.css('#batch-folder-cell-1-target'),
      ).nativeElement as HTMLButtonElement;

      expect(validButton.classList).toContain('batch-folder-cell--valid');
      expect(validButton.textContent).toContain('Campaign / Shoes');
      expect(invalidButton.classList).toContain('batch-folder-cell--invalid');
      expect(invalidButton.textContent).toContain('⚠️');
    });

    it('flags an unknown path and disables Run', () => {
      loadFolderCsv(['Campaign / Shoes', 'Nope']);
      const cell = folderCell(1);

      expect(cell?.status).toBe('invalid');
      expect(cell?.folderId).toBeNull();
      expect(cell?.label).toBe('Nope');
      expect(cell?.tooltip).toBe('"Nope" not found. Click to choose a folder.');
      expect(component.unresolvedFolderCellCount()).toBe(1);
      expect(component.folderIssuesText()).toBe(
        '1 folder cell needs a folder. Click a ⚠️ cell to choose one.',
      );
      expect(runButton().disabled).toBeTrue();

      component.runBatch();
      expect(workflowServiceSpy.batchExecuteWorkflow).not.toHaveBeenCalled();
    });

    it('pluralizes the issues text when several folder cells are unresolved', () => {
      loadFolderCsv(['Nope', 'Missing']);

      expect(component.unresolvedFolderCellCount()).toBe(2);
      expect(component.folderIssuesText()).toBe(
        '2 folder cells need a folder. Click a ⚠️ cell to choose one.',
      );
    });

    it('flags an empty path', () => {
      loadFolderCsv(['   ']);
      const cell = folderCell(0);
      expect(cell?.status).toBe('invalid');
      expect(cell?.label).toBe('Empty folder path');
    });

    it('keeps cells pending and Run disabled while the tree loads', () => {
      folderServiceSpy.getFolderTree.and.returnValue(
        new Subject<FolderTreeNode[]>(),
      );
      loadFolderCsv(['Campaign / Shoes']);

      expect(folderCell(0)?.status).toBe('pending');
      expect(component.folderIssuesText()).toBe('Checking folder paths…');
      expect(component.hasUnresolvedFolderCells()).toBeTrue();
      expect(runButton().disabled).toBeTrue();
    });

    it('shows the tree error with a Retry button that reloads the tree', () => {
      const warnSpy = spyOn(console, 'warn');
      folderServiceSpy.getFolderTree.and.returnValue(
        throwError(() => new Error('boom')),
      );
      loadFolderCsv(['Campaign / Shoes']);

      expect(warnSpy).toHaveBeenCalled();
      expect(component.folderTreeStatus()).toBe('error');
      expect(component.showFolderTreeError()).toBeTrue();
      expect(folderCell(0)?.status).toBe('invalid');
      const errorAlert = fixture.debugElement.query(
        By.css('#batch-folder-tree-error'),
      );
      expect(errorAlert.nativeElement.textContent).toContain(
        'Folders could not be loaded.',
      );

      folderServiceSpy.getFolderTree.and.returnValue(of(FOLDER_TREE));
      fixture.debugElement
        .query(By.css('#batch-folder-tree-retry-btn'))
        .nativeElement.click();
      fixture.detectChanges();

      expect(component.folderTreeStatus()).toBe('loaded');
      expect(folderCell(0)?.status).toBe('valid');
      expect(
        fixture.debugElement.query(By.css('#batch-folder-tree-error')),
      ).toBeNull();
    });

    it('keeps the previous tree when a refresh fails', () => {
      spyOn(console, 'warn');
      loadFolderCsv(['Campaign / Shoes']);
      folderServiceSpy.getFolderTree.and.returnValue(
        throwError(() => new Error('boom')),
      );

      component.loadFolderTree();

      expect(component.folderTreeStatus()).toBe('loaded');
      expect(folderCell(0)?.status).toBe('valid');
    });

    it('fixes a cell with the picker and refreshes the tree after close', () => {
      runFolderServiceSpy.pickFolder.and.returnValue(of(ARCHIVE_PICK));
      loadFolderCsv(['Nope']);
      folderServiceSpy.getFolderTree.calls.reset();

      fixture.debugElement
        .query(By.css('#batch-folder-cell-0-target'))
        .nativeElement.click();
      fixture.detectChanges();

      const cell = folderCell(0);
      expect(runFolderServiceSpy.pickFolder).toHaveBeenCalledOnceWith(null);
      expect(folderServiceSpy.getFolderTree).toHaveBeenCalledTimes(1);
      expect(cell?.status).toBe('valid');
      expect(cell?.folderId).toBe(11);
      expect(cell?.label).toBe('Archive');
      expect(runButton().disabled).toBeFalse();
    });

    it('keeps the cell unchanged when the picker is cancelled', () => {
      loadFolderCsv(['Nope']);
      const invalidCell = folderCell(0);
      if (!invalidCell) return fail('missing folder cell');

      component.openFolderPickerForCell(invalidCell);

      expect(folderCell(0)?.status).toBe('invalid');
      expect(folderServiceSpy.getFolderTree).toHaveBeenCalledTimes(2);
    });

    it('opens the picker at the resolved folder', () => {
      loadFolderCsv(['Campaign / Shoes']);
      const validCell = folderCell(0);
      if (!validCell) return fail('missing folder cell');

      component.openFolderPickerForCell(validCell);

      expect(runFolderServiceSpy.pickFolder).toHaveBeenCalledOnceWith(42);
    });

    it('sends folder ids as numbers', () => {
      runFolderServiceSpy.pickFolder.and.returnValue(of(ARCHIVE_PICK));
      loadFolderCsv(['Campaign / Shoes', 'Nope']);
      const invalidCell = folderCell(1);
      if (!invalidCell) return fail('missing folder cell');
      component.openFolderPickerForCell(invalidCell);

      component.runBatch();

      expect(workflowServiceSpy.batchExecuteWorkflow).toHaveBeenCalledOnceWith(
        'wf-batch-1',
        [
          {
            row_index: 0,
            args: {workspace_id: 42, prompt: 'Item 1', target: 42},
          },
          {
            row_index: 1,
            args: {workspace_id: 42, prompt: 'Item 2', target: 11},
          },
        ],
      );
    });

    it('resets the picked folders when a new CSV is parsed', async () => {
      runFolderServiceSpy.pickFolder.and.returnValue(of(ARCHIVE_PICK));
      loadFolderCsv(['Nope']);
      const invalidCell = folderCell(0);
      if (!invalidCell) return fail('missing folder cell');
      component.openFolderPickerForCell(invalidCell);
      expect(component.folderOverrides().size).toBe(1);

      const validated = new Promise<void>(resolve => {
        spyOn(component, 'validateHeaders').and.callFake(() => resolve());
      });
      component.parseCsv(
        new File(['prompt,target\nItem,Nope'], 'next.csv', {type: 'text/csv'}),
      );
      await validated;

      expect(component.folderOverrides().size).toBe(0);
    });

    it('previews the first rows plus later rows needing a folder', () => {
      const targets = Array.from({length: 8}, (_, index) =>
        index === 6 ? 'Nope' : 'Campaign / Shoes',
      );
      loadFolderCsv(targets);

      const rows = component.previewRows();
      expect(rows.map(row => row.rowNumber)).toEqual([1, 2, 3, 4, 5, 7]);
      expect(rows.length).toBe(BATCH_PREVIEW_ROW_LIMIT + 1);
      expect(component.previewFooterText()).toBe(
        'Showing 6 of 8 rows (first 5 and rows needing a folder)',
      );
    });

    it('previews only the first rows when every folder resolves', () => {
      loadFolderCsv(Array.from({length: 7}, () => 'Campaign / Shoes'));
      expect(component.previewRows().length).toBe(BATCH_PREVIEW_ROW_LIMIT);
      expect(component.previewFooterText()).toBe('Showing first 5 of 7 rows');
    });
  });
});
