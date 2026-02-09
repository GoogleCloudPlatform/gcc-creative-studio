import {
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
} from '@angular/core/testing';
import {
  MatDialogModule,
  MAT_DIALOG_DATA,
  MatDialogRef,
} from '@angular/material/dialog';
import {of, throwError, BehaviorSubject} from 'rxjs';
import {delay} from 'rxjs/operators';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {
  BatchItemResult,
  WorkflowModel,
  StepStatusEnum,
  NodeTypes,
} from '../../workflow.models';
import {WorkflowService} from '../../workflow.service';
import {BatchExecutionModalComponent} from './batch-execution-modal.component';
import * as Papa from 'papaparse';
import {MatProgressBarModule} from '@angular/material/progress-bar';
import {MatIconModule} from '@angular/material/icon';
import {MatTooltipModule} from '@angular/material/tooltip';

// Mock data
const mockWorkflow: WorkflowModel = {
  id: 'wf-1',
  name: 'Test Workflow',
  description: '',
  steps: [
    {
      stepId: 'step-1',
      type: NodeTypes.USER_INPUT,
      status: StepStatusEnum.IDLE,
      outputs: {
        prompt: {value_type: 'STRING'},
        aspect_ratio: {value_type: 'STRING'},
      },
      inputs: {},
      settings: {},
    },
    {
      stepId: 'step-2',
      type: NodeTypes.GENERATE_IMAGE,
      status: StepStatusEnum.IDLE,
      inputs: {},
      outputs: {},
      settings: {},
    },
  ],
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  userId: 'test-user',
};

const mockCsvData = `prompt,Aspect Ratio
"A cat sitting on a mat","1:1"
"A dog chasing a ball","16:9"`;

const mockParsedCsv: Papa.ParseResult<any> = {
  data: [
    {prompt: 'A cat sitting on a mat', 'Aspect Ratio': '1:1'},
    {prompt: 'A dog chasing a ball', 'Aspect Ratio': '16:9'},
  ],
  meta: {
    fields: ['prompt', 'Aspect Ratio'],
    aborted: false,
    cursor: 0,
    delimiter: ',',
    linebreak: '\n',
    truncated: false,
  },
  errors: [],
};

// Mock services
const mockDialogRef = {
  close: jasmine.createSpy('close'),
};

const mockWorkflowService = {
  batchExecuteWorkflow: jasmine
    .createSpy('batchExecuteWorkflow')
    .and.returnValue(of({results: []})),
};

const mockWorkspaceStateService = {
  activeWorkspaceId$: new BehaviorSubject<number | null>(123),
};

describe('BatchExecutionModalComponent', () => {
  let component: BatchExecutionModalComponent;
  let fixture: ComponentFixture<BatchExecutionModalComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [BatchExecutionModalComponent],
      imports: [
        MatProgressBarModule,
        MatIconModule,
        MatDialogModule,
        MatTooltipModule,
      ],
      providers: [
        {provide: MatDialogRef, useValue: mockDialogRef},
        {provide: MAT_DIALOG_DATA, useValue: {workflow: mockWorkflow}},
        {provide: WorkflowService, useValue: mockWorkflowService},
        {provide: WorkspaceStateService, useValue: mockWorkspaceStateService},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(BatchExecutionModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    // Reset spies before each test
    mockDialogRef.close.calls.reset();
    mockWorkflowService.batchExecuteWorkflow.calls.reset();
  });

  it('should create and initialize correctly', () => {
    expect(component).toBeTruthy();
    expect(component.workflow).toEqual(mockWorkflow);
    expect(component.expectedInputs).toEqual(['prompt', 'aspect_ratio']);
  });

  describe('onFileSelected', () => {
    it('should parse the selected file', () => {
      const file = new File([mockCsvData], 'test.csv', {type: 'text/csv'});
      const event = {target: {files: [file]}};
      spyOn(component, 'parseCsv');

      component.onFileSelected(event);

      expect(component.csvFile).toBe(file);
      expect(component.parseCsv).toHaveBeenCalledWith(file);
    });

    it('should do nothing if no file is selected', () => {
      const event = {target: {files: []}};
      spyOn(component, 'parseCsv');
      component.onFileSelected(event);
      expect(component.parseCsv).not.toHaveBeenCalled();
    });
  });

  describe('parseCsv', () => {
    it('should correctly parse a valid CSV file and validate headers', () => {
      spyOn(Papa, 'parse').and.callFake((file: any, config: any) => {
        if (config.complete) {
          config.complete(mockParsedCsv, file);
        }
        return undefined as any;
      });

      spyOn(component, 'validateHeaders');

      const file = new File([mockCsvData], 'test.csv');

      component.parseCsv(file);

      expect(Papa.parse).toHaveBeenCalled();
      if (mockParsedCsv.meta.fields) {
        expect(component.headers).toEqual(mockParsedCsv.meta.fields);
      }
      expect(component.parsedItems).toEqual(mockParsedCsv.data);
      expect(component.validateHeaders).toHaveBeenCalled();
    });

    it('should handle CSV parsing errors', () => {
      const errorMessage = 'Test parse error';
      const error: Papa.ParseError = {
        type: 'FieldMismatch',
        code: 'InvalidQuotes',
        message: errorMessage,
        row: 0,
      };
      const mockErrorResult: Papa.ParseResult<any> = {
        data: [{header: 'value'}],
        errors: [error],
        meta: {
          fields: [],
          aborted: false,
          cursor: 0,
          delimiter: ',',
          linebreak: '\n',
          truncated: false,
        },
      };
      spyOn(Papa, 'parse').and.callFake((file: any, config: any) => {
        config.complete(mockErrorResult, file);
        return undefined as any;
      });
      const file = new File([''], 'bad.csv');

      component.parseCsv(file);

      expect(component.validationErrors).toEqual([
        `CSV Parse Error: ${errorMessage}`,
      ]);
    });
  });

  describe('validateHeaders', () => {
    beforeEach(() => {
      component.parsedItems = mockParsedCsv.data;
    });

    it('should set isValid to true when all headers are present and mapped', () => {
      component.headers = ['prompt', 'Aspect Ratio'];

      component.validateHeaders();

      expect(component.isValid).toBeTrue();

      expect(component.validationErrors.length).toBe(0);

      expect(component.missingInputs.length).toBe(0);

      expect(component.columnMapping).toEqual({
        prompt: 'prompt',

        'Aspect Ratio': 'aspect_ratio',
      });
    });

    it('should identify missing required columns', () => {
      component.headers = ['prompt']; // Missing 'Aspect Ratio'

      component.validateHeaders();

      expect(component.isValid).toBeFalse();

      expect(component.missingInputs).toEqual(['aspect_ratio']);

      expect(component.validationErrors).toEqual([
        'Missing required columns: aspect_ratio',
      ]);
    });

    it('should add a validation error if parsedItems is empty', () => {
      component.parsedItems = [];

      component.validateHeaders();

      expect(component.isValid).toBe(false);

      expect(component.validationErrors).toContain('CSV is empty');
    });

    it('should handle extra columns gracefully', () => {
      component.headers = ['prompt', 'Aspect Ratio', 'extra_column'];

      component.validateHeaders();

      expect(component.isValid).toBeTrue();

      expect(component.columnMapping['extra_column']).toBeNull();
    });
  });

  describe('runBatch', () => {
    beforeEach(() => {
      component.isValid = true;

      component.parsedItems = mockParsedCsv.data;

      component.columnMapping = {
        prompt: 'prompt',

        'Aspect Ratio': 'aspect_ratio',
      };

      // Reset the workspace service mock before each 'runBatch' test

      mockWorkspaceStateService.activeWorkspaceId$.next(123);
    });

    it('should not run if isValid is false', () => {
      component.isValid = false;

      component.runBatch();

      expect(mockWorkflowService.batchExecuteWorkflow).not.toHaveBeenCalled();
    });

    it('should set isProcessing to true and call batchExecuteWorkflow', fakeAsync(() => {
      const mockResults: BatchItemResult[] = [
        {row_index: 0, status: 'SUCCESS', execution_id: 'exec-1', error: ''},
        {row_index: 1, status: 'FAILED', error: 'Failed to generate'},
      ];
      mockWorkflowService.batchExecuteWorkflow.and.returnValue(
        of({results: mockResults}).pipe(delay(1)),
      );

      component.runBatch();

      expect(component.isProcessing).toBeTrue();

      tick(1);

      expect(component.isProcessing).toBeFalse(); // It should be false after completion

      expect(mockWorkflowService.batchExecuteWorkflow).toHaveBeenCalled();

      const expectedPayload = mockParsedCsv.data.map((row, index) => ({
        row_index: index,

        args: {
          workspace_id: 123,

          prompt: row.prompt,

          aspect_ratio: row['Aspect Ratio'],
        },
      }));

      expect(mockWorkflowService.batchExecuteWorkflow).toHaveBeenCalledWith(
        mockWorkflow.id,
        expectedPayload,
      );

      expect(component.results).toEqual(mockResults);
    }));

    it('should handle partially successful batch execution', fakeAsync(() => {
      const mockResults: BatchItemResult[] = [
        {row_index: 0, status: 'SUCCESS', execution_id: 'exec-1', error: ''},

        {row_index: 1, status: 'FAILED', error: 'Failed to generate'},
      ];

      mockWorkflowService.batchExecuteWorkflow.and.returnValue(
        of({results: mockResults}),
      );

      component.runBatch();

      tick();

      expect(component.successCount).toBe(1);

      expect(component.failureCount).toBe(1);
    }));

    it('should handle API errors during batch execution', fakeAsync(() => {
      const errorResponse = {message: 'Internal Server Error'};

      mockWorkflowService.batchExecuteWorkflow.and.returnValue(
        throwError(() => errorResponse),
      );

      component.runBatch();

      tick();

      expect(component.isProcessing).toBe(false);

      expect(component.validationErrors).toContain(
        `Server Error: ${errorResponse.message}`,
      );
    }));

    it('should handle missing workspace ID', fakeAsync(() => {
      // Use a version of the service that returns null for the workspace

      mockWorkspaceStateService.activeWorkspaceId$.next(null);

      component.runBatch();

      tick();

      expect(component.isProcessing).toBe(false);

      expect(component.validationErrors).toContain(
        'No active workspace found.',
      );

      expect(mockWorkflowService.batchExecuteWorkflow).not.toHaveBeenCalled();
    }));
  });

  describe('Getters', () => {
    it('should correctly calculate successCount and failureCount', () => {
      component.results = [
        {row_index: 0, status: 'SUCCESS', execution_id: 'exec-1', error: ''},

        {row_index: 1, status: 'FAILED', error: ''},

        {row_index: 2, status: 'SUCCESS', execution_id: 'exec-3', error: ''},
      ];

      expect(component.successCount).toBe(2);

      expect(component.failureCount).toBe(1);
    });
  });

  it('should close the dialog when close() is called', () => {
    component.close();

    expect(mockDialogRef.close).toHaveBeenCalled();
  });

  it('normalizeHeader should correctly format strings', () => {
    expect(component.normalizeHeader('  Aspect Ratio  ')).toBe('aspect_ratio');

    expect(component.normalizeHeader('prompt')).toBe('prompt');

    expect(component.normalizeHeader('A long header with many spaces')).toBe(
      'a_long_header_with_many_spaces',
    );
  });
});
