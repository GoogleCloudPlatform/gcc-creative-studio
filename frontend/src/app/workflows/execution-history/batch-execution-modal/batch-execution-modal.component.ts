import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import * as Papa from 'papaparse';
import { take } from 'rxjs/operators';
import { WorkspaceStateService } from '../../../services/workspace/workspace-state.service';
import { BatchItemResult, WorkflowModel } from '../../workflow.models';
import { WorkflowService } from '../../workflow.service';

@Component({
  selector: 'app-batch-execution-modal',
  templateUrl: './batch-execution-modal.component.html',
  styleUrls: ['./batch-execution-modal.component.scss']
})
export class BatchExecutionModalComponent {
  workflow: WorkflowModel;

  csvFile: File | null = null;
  parsedItems: any[] = [];
  headers: string[] = [];

  isProcessing = false;
  results: BatchItemResult[] = [];

  validationErrors: string[] = [];

  // Validation State
  expectedInputs: string[] = [];
  columnMapping: { [csvHeader: string]: string | null } = {}; // Header -> InputName or null (ignored)
  missingInputs: string[] = [];
  isValid = false;

  constructor(
    public dialogRef: MatDialogRef<BatchExecutionModalComponent>,
    @Inject(MAT_DIALOG_DATA) public data: { workflow: WorkflowModel },
    private workflowService: WorkflowService,
    private workspaceStateService: WorkspaceStateService
  ) {
    this.workflow = data.workflow;
    this.extractExpectedInputs();
  }

  extractExpectedInputs() {
    // Find the first user_input step (or all of them?)
    // Usually there's only one 'user_input' node that acts as the trigger/form.
    const userInputStep = this.workflow.steps.find(s => s.type === 'user_input');
    if (userInputStep && userInputStep.outputs) {
      this.expectedInputs = Object.keys(userInputStep.outputs);
    }
  }

  onFileSelected(event: any) {
    const file = event.target.files[0];
    if (file) {
      this.csvFile = file;
      this.parseCsv(file);
    }
  }

  parseCsv(file: File) {
    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      complete: (result: any) => {
        this.headers = result.meta.fields || [];
        this.parsedItems = result.data;
        this.validateHeaders();
      },
      error: (error: any) => {
        this.validationErrors = [`CSV Parse Error: ${error.message}`];
      }
    });
  }

  validateHeaders() {
    this.validationErrors = [];
    this.missingInputs = [];
    this.columnMapping = {};
    this.isValid = false;

    if (this.parsedItems.length === 0) {
      this.validationErrors.push("CSV is empty");
      return;
    }

    // 1. Map Headers to Inputs
    const usedInputs = new Set<string>();

    this.headers.forEach(header => {
      const normalized = this.normalizeHeader(header);
      // Check if normalized header matches any expected input (exact match)
      if (this.expectedInputs.includes(normalized)) {
        this.columnMapping[header] = normalized;
        usedInputs.add(normalized);
      } else {
        // Try to find if the raw header matches?
        if (this.expectedInputs.includes(header)) {
          this.columnMapping[header] = header;
          usedInputs.add(header);
        } else {
          this.columnMapping[header] = null; // Unmapped/Ignored
        }
      }
    });

    // 2. Check for Missing Inputs
    this.expectedInputs.forEach(input => {
      if (!usedInputs.has(input)) {
        this.missingInputs.push(input);
      }
    });

    if (this.missingInputs.length > 0) {
      this.validationErrors.push(`Missing required columns: ${this.missingInputs.join(', ')}`);
    }

    if (this.validationErrors.length === 0) {
      this.isValid = true;
    }
  }

  normalizeHeader(header: string): string {
    // "Aspect Ratio" -> "aspect_ratio"
    return header.trim().toLowerCase().replace(/\s+/g, '_');
  }

  runBatch() {
    if (!this.isValid || this.parsedItems.length === 0) return;

    this.isProcessing = true;
    this.results = [];

    // Get current workspace ID once
    this.workspaceStateService.activeWorkspaceId$
      .pipe(take(1))
      .subscribe(workspaceId => {
        if (!workspaceId) {
          this.validationErrors.push("No active workspace found.");
          this.isProcessing = false;
          return;
        }

        // Map parsed items to the expected batch format
        // We strictly use the mapping to construct args
        const items = this.parsedItems.map((row, index) => {
          const args: any = {
            workspace_id: workspaceId
          };

          // Only include mapped columns
          Object.keys(row).forEach(header => {
            const mappedInput = this.columnMapping[header];
            if (mappedInput) {
              args[mappedInput] = row[header];
            }
          });

          return {
            row_index: index,
            args: args
          };
        });

        this.workflowService.batchExecuteWorkflow(this.workflow.id, items).subscribe({
          next: (response) => {
            this.results = response.results;
            this.isProcessing = false;
          },
          error: (err) => {
            console.error('Batch execution failed', err);
            // Handle global failure?
            this.validationErrors.push(`Server Error: ${err.message}`);
            this.isProcessing = false;
          }
        });
      });
  }

  close() {
    this.dialogRef.close();
  }

  get successCount() {
    return this.results.filter(r => r.status === 'SUCCESS').length;
  }

  get failureCount() {
    return this.results.filter(r => r.status === 'FAILED').length;
  }
}
