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

import { CdkDragDrop } from '@angular/cdk/drag-drop';
import { Component, DestroyRef, OnDestroy, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  AbstractControl,
  FormArray,
  FormGroup
} from '@angular/forms';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ActivatedRoute, Router } from '@angular/router';
import { Observable, Subscription, of } from 'rxjs';
import { switchMap, tap } from 'rxjs/operators';
import { handleErrorSnackbar, handleSuccessSnackbar } from '../../utils/handleMessageSnackbar';
import { MediaResolutionService } from '../shared/media-resolution.service';
import {
  NodeTypes,
  StepStatusEnum,
  WorkflowBase,
  WorkflowCreateDto,
  WorkflowModel,
  WorkflowRunModel,
  WorkflowUpdateDto
} from '../workflow.models';
// import { STEP_CONFIGS_MAP } from '../shared/step-configs.map'; // Removed as only used by getStepConfig which is now in service (mostly)
// But wait, template calls getStepConfig.
import { STEP_CONFIGS_MAP } from '../shared/step-configs.map'; // Kept for template
import { WorkflowService } from '../workflow.service';
import { AddStepModalComponent } from './add-step-modal/add-step-modal.component';
import { RunWorkflowModalComponent } from './run-workflow-modal/run-workflow-modal.component';

import { WorkflowFormService } from './workflow-form.service';



@Component({
  selector: 'app-workflow-editor',
  templateUrl: './workflow-editor.component.html',
  styleUrls: ['./workflow-editor.component.scss'],
  providers: [WorkflowFormService],
})
export class WorkflowEditorComponent implements OnInit, OnDestroy {
  // --- Component Mode & State ---
  EditorMode = EditorMode;
  mode: EditorMode = EditorMode.Create;
  NodeTypes = NodeTypes;
  workflowId: string | null = null;
  runId: string | null = null;

  // --- Data ---
  workflow: WorkflowModel | null = null;
  workflowRun: WorkflowRunModel | null = null;
  displayedWorkflow: WorkflowModel | WorkflowBase | null = null;

  // --- UI State ---
  // workflowForm handled by service
  get workflowForm() { return this.formService.workflowForm; }
  isLoading = false;
  submitted = false;
  errorMessage: string | null = null;
  selectedStepIndex: number | null = null;
  get selectedStep(): any | null {
    if (this.selectedStepIndex === null) return null;
    // stepsArray is accessed via getter now
    if (!this.stepsArray || this.selectedStepIndex < 0 || this.selectedStepIndex >= this.stepsArray.length) {
      return null;
    }
    return this.stepsArray.at(this.selectedStepIndex).value;
  }

  get selectedStepExecution(): any | null {
    if (!this.selectedStep || !this.executionStepEntries) return null;
    const entry = this.executionStepEntries.find(e => e.step_id === this.selectedStep.stepId);
    return entry ? entry : null;
  }
  // availableOutputsPerStep is now an observable, but template expects array.
  // We can subscribe to it or usage async pipe.
  // For minimal template change, we'll subscribe.
  availableOutputsPerStep: any[][] = [];
  previousOutputDefinitions: any[] = [];


  private destroyRef = inject(DestroyRef);
  private formService = inject(WorkflowFormService);


  private mainSubscription!: Subscription;
  // private pollingSubscription?: Subscription; // Removed
  currentExecutionId: string | null = null;
  currentExecutionState: string | null = null;
  executionStepEntries: any[] = [];
  mediaUrlMap = new Map<string, string>();
  loadedMedia = new Set<string>();
  returnUrl: string | null = null;


  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private workflowService: WorkflowService,
    private dialog: MatDialog,
    private snackBar: MatSnackBar,
    private mediaResolutionService: MediaResolutionService,


  ) { }

  get stepsArray(): FormArray {
    return this.formService.stepsArray;
  }

  get outputDefinitionsArray(): FormArray {
    return this.formService.outputDefinitionsArray;
  }

  asFormGroup(control: AbstractControl): FormGroup {
    return control as FormGroup;
  }

  ngOnInit(): void {
    // Initialize form immediately with empty/default data
    this.formService.initForm();

    // Subscribe to available outputs from service
    this.formService.availableOutputsPerStep$.subscribe(outputs => {
      this.availableOutputsPerStep = outputs;
    });

    this.route.queryParamMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(params => {
        this.returnUrl = params.get('returnUrl');
      });

    this.mainSubscription = this.route.paramMap
      .pipe(
        tap(() => (this.isLoading = true)),
        switchMap(params => {
          this.runId = params.get('runId');
          this.workflowId = params.get('workflowId');
          console.log(`run id: ${this.runId}`)
          console.log(`workflow id: ${this.workflowId}`)
          if (this.runId) {
            console.log("This mode run")
            this.mode = EditorMode.Run;
            // TODO: Create and use a WorkflowRunService
            // return this.workflowRunService.getWorkflowRun(this.runId);
            return of(null); // Placeholder
          } else if (this.workflowId) {
            console.log("This mode edit")
            this.mode = EditorMode.Edit;
            return this.workflowService.getWorkflowById(this.workflowId);
          } else {
            console.log("This mode create")
            this.mode = EditorMode.Create;
            return of(null);
          }
        }),
      )
      .subscribe({
        next: (data: WorkflowModel | WorkflowRunModel | null) => {
          if (this.mode === EditorMode.Run) {
            this.workflowRun = data ? (data as WorkflowRunModel) : null;
            this.displayedWorkflow = this.workflowRun?.workflowSnapshot ?? null;
            this.workflowId = this.workflowRun?.id ?? null;
            if (this.displayedWorkflow) {
              this.formService.patchData(this.displayedWorkflow);
            }
            this.workflowForm.disable(); // Read-only mode
          } else if (this.mode === EditorMode.Edit) {
            this.workflow = data as WorkflowModel;
            this.displayedWorkflow = this.workflow;
            if (this.displayedWorkflow) {
              this.formService.patchData(this.displayedWorkflow);
            }
          } else {
            // Already initialized in initForm() defaults
          }
          this.isLoading = false;
        },
        error: err => {
          console.error('Failed to load workflow data', err);
          this.errorMessage = 'Failed to load workflow data.';
          this.isLoading = false;
        },
      });

    // Initialize and subscribe to user input changes
    // syncOutputs moved to service
    this.previousOutputDefinitions = this.outputDefinitionsArray.getRawValue();
    this.outputDefinitionsArray.valueChanges.subscribe((currentValues) => {
      this.handleOutputRenames(currentValues);
      this.formService.syncOutputs(); // Trigger sync in service if needed, although service might handle specific adds/removes
      // Actually outputDefinitionsArray.valueChanges might be too aggressive for full sync if service handles it.
      // But service only handles explicit add/remove calls.
      // If user types in name, we might need to sync?
      // existing syncOutputs re-created controls.
      // We might need to expose syncOutputs in service public API if we want to call it here.
      // Or better, let service handle it internally.
      // For now, let's assume service handles its own state for structure, and values just propagate.

      this.previousOutputDefinitions = currentValues;
    });
  }

  resolveMediaUrls(details: any): void {
    if (!details || !details.step_entries) return;

    const stepTypeMap = new Map<string, NodeTypes | string>();
    // In workflow editor, we have the form, so we can get types from there or from the loaded workflow.
    // Ideally we use the current form state to get types, or the workflow definition if available.
    // But details.step_entries has step_id.
    // We can iterate over stepsArray to build the map.
    this.stepsArray.controls.forEach(control => {
      const stepId = control.get('stepId')?.value;
      const type = control.get('type')?.value;
      if (stepId && type) {
        stepTypeMap.set(stepId, type);
      }
    });

    this.mediaResolutionService.resolveMediaUrls(details.step_entries, stepTypeMap, this.mediaUrlMap);
  }

  isImageOutput(stepId: string): boolean {
    const type = this.getStepType(stepId);
    return type === NodeTypes.GENERATE_IMAGE ||
      type === NodeTypes.EDIT_IMAGE ||
      type === NodeTypes.CROP_IMAGE ||
      type === NodeTypes.VIRTUAL_TRY_ON;
  }

  getStepType(stepId: string): NodeTypes | string | undefined {
    // Check if it's the user input step
    if (stepId === NodeTypes.USER_INPUT) return NodeTypes.USER_INPUT;

    // Find in steps array
    const step = this.stepsArray.controls.find(c => c.get('stepId')?.value === stepId);
    return step ? step.get('type')?.value : undefined;
  }

  // ... (rest of the component logic will be updated in subsequent steps)

  getStepConfig(type: string) {
    return (STEP_CONFIGS_MAP as any)[type];
  }

  get isReadOnly(): boolean {
    return this.mode === EditorMode.Run;
  }

  // ... (rest of the component: ngOnDestroy, initForm, addStepToForm, etc. remains the same)
  ngOnDestroy(): void {
    if (this.mainSubscription) {
      this.mainSubscription.unsubscribe();
    }
    if (this.mainSubscription) {
      this.mainSubscription.unsubscribe();
    }
    // pollingSubscription removal not needed, handled by DestroyRef
  }

  addOutput(name = '', type = 'text', id?: string): void {
    this.formService.addOutputDefinition(name, type, id);
  }

  removeOutput(index: number): void {
    this.formService.removeOutputDefinition(index);
  }

  // syncOutputs and updateAvailableOutputs removed, handled by service

  private handleOutputRenames(currentDefinitions: any[]) {
    if (this.isLoading) return;

    const prevMap = new Map(this.previousOutputDefinitions.map(d => [d.id, d]));

    currentDefinitions.forEach(newDef => {
      const oldDef = prevMap.get(newDef.id);
      if (oldDef && oldDef.name !== newDef.name) {
        this.updateStepReferences(newDef.id, newDef.name);
      }
    });
  }

  private updateStepReferences(definitionId: string, newName: string) {
    this.stepsArray.controls.forEach(stepControl => {
      const inputs = stepControl.get('inputs') as FormGroup;
      if (!inputs) return;

      Object.keys(inputs.controls).forEach(inputKey => {
        const control = inputs.get(inputKey);
        const value = control?.value;
        if (value && typeof value === 'object' && value.step === NodeTypes.USER_INPUT && value._definitionId === definitionId) {
          control?.setValue({ ...value, output: newName });
        }
      });
    });
  }

  openAddStepModal() {
    const dialogRef = this.dialog.open(AddStepModalComponent, {
      width: '600px',
      panelClass: 'node-palette-dialog',
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) this.addStepToForm(result);
    });
  }

  addStepToForm(type: string, existingData?: any) {
    this.formService.addStep(type, existingData);
  }

  // createFormGroupFromData removed, handled by service

  deleteStep(index: number) {
    const deletedStepId = this.formService.deleteStep(index);
    this.formService.updateAfterDelete(); // Trigger update in service

    // Update selectedStepIndex
    if (this.selectedStepIndex === index) {
      this.selectedStepIndex = null;
    } else if (this.selectedStepIndex !== null && this.selectedStepIndex > index) {
      this.selectedStepIndex--;
    }

    // Clear dependents
    if (deletedStepId) {
      this.clearDependents(deletedStepId);
    }
  }

  private clearDependents(deletedStepId: string) {
    this.stepsArray.controls.forEach(stepControl => {
      const inputs = stepControl.get('inputs') as FormGroup;
      if (!inputs) return;

      Object.keys(inputs.controls).forEach(inputKey => {
        const control = inputs.get(inputKey);
        const value = control?.value;
        if (value && typeof value === 'object' && value.step === deletedStepId) {
          control?.setValue(null);
          control?.markAsDirty();
          control?.updateValueAndValidity();
        }
      });
    });
  }

  dropStep(event: CdkDragDrop<string[]>) {
    this.formService.moveStep(event.previousIndex, event.currentIndex);

    // Update selectedStepIndex if it was affected
    if (this.selectedStepIndex !== null) {
      if (this.selectedStepIndex === event.previousIndex) {
        this.selectedStepIndex = event.currentIndex;
      } else if (
        event.previousIndex < this.selectedStepIndex &&
        event.currentIndex >= this.selectedStepIndex
      ) {
        this.selectedStepIndex--;
      } else if (
        event.previousIndex > this.selectedStepIndex &&
        event.currentIndex <= this.selectedStepIndex
      ) {
        this.selectedStepIndex++;
      }
    }
  }

  save() {
    this.submitted = true;
    if (this.workflowForm.invalid) {
      return;
    }
    if (this.workflowForm.pristine) return;

    this.isLoading = true;
    this.errorMessage = null;

    const formValue = this.workflowForm.getRawValue();
    const steps = this.prepareSteps(formValue);

    let request$: Observable<any>;

    if (this.mode === EditorMode.Edit) {
      const updateDto: WorkflowUpdateDto = {
        name: formValue.name,
        description: formValue.description || '',
        steps: steps,
      };
      request$ = this.workflowService.updateWorkflow(formValue.id, updateDto);
    } else {
      const createDto: WorkflowCreateDto = {
        name: formValue.name,
        description: formValue.description || '',
        steps: steps,
      };
      request$ = this.workflowService.createWorkflow(createDto);
    }

    request$.subscribe({
      next: (response) => {
        this.isLoading = false;
        this.workflowForm.markAsPristine();

        // If we were in Create mode, switch to Edit mode with the new ID
        if (this.mode === EditorMode.Create && response && response.id) {
          this.mode = EditorMode.Edit;
          this.workflowId = response.id;
          this.workflowForm.patchValue({ id: response.id });
          // Update URL without reloading
          this.router.navigate(['/workflows', 'edit', response.id], { replaceUrl: true });
        }
      },
      error: err => {
        console.error('Failed to save workflow', err);
        this.errorMessage = err.error?.message || 'Failed to save workflow.';
        this.isLoading = false;
      },
    });
  }

  run() {
    this.submitted = true;
    if (this.workflowForm.invalid) {
      return;
    }

    const formValue = this.workflowForm.getRawValue();
    const steps = this.prepareSteps(formValue);
    const userInputStep = steps.find(s => s.type === NodeTypes.USER_INPUT);

    // If form is pristine and we have an ID, just run it
    if (this.workflowForm.pristine && this.workflowId) {
      this.openRunModal(this.workflowId, userInputStep);
      return;
    }

    // Otherwise save first (or create if new)
    this.isLoading = true;
    this.errorMessage = null;

    let saveRequest$: Observable<any>;

    if (this.mode === EditorMode.Edit) {
      const updateDto: WorkflowUpdateDto = {
        name: formValue.name,
        description: formValue.description || '',
        steps: steps,
      };
      saveRequest$ = this.workflowService.updateWorkflow(formValue.id, updateDto);
    } else {
      const createDto: WorkflowCreateDto = {
        name: formValue.name,
        description: formValue.description || '',
        steps: steps,
      };
      saveRequest$ = this.workflowService.createWorkflow(createDto);
    }

    saveRequest$.subscribe({
      next: (response) => {
        this.isLoading = false;
        this.workflowForm.markAsPristine();

        let workflowId = this.workflowId;
        if (this.mode === EditorMode.Create && response && response.id) {
          this.mode = EditorMode.Edit;
          this.workflowId = response.id;
          workflowId = response.id;
          this.workflowForm.patchValue({ id: response.id });
          this.router.navigate(['/workflows', 'edit', response.id], { replaceUrl: true });
        }

        if (workflowId) {
          this.openRunModal(workflowId, userInputStep);
        }
      },
      error: err => {
        console.error('Failed to save before run', err);
        this.errorMessage = 'Failed to save workflow before running.';
        this.isLoading = false;
      }
    });
  }

  goBack(): void {
    if (this.returnUrl) {
      this.router.navigateByUrl(this.returnUrl);
    } else {
      this.router.navigate(['/workflows']);
    }
  }

  private prepareSteps(formValue: any): any[] {
    const steps = formValue.steps.map((step: any) => {
      const newStep = { ...step };
      if (newStep.inputs) {
        const newInputs = { ...newStep.inputs };
        Object.keys(newInputs).forEach(key => {
          let val = newInputs[key];

          if (Array.isArray(val)) {
            // Handle array inputs (e.g. multiple images)
            newInputs[key] = val.map(item => this.cleanInputValue(item));
          } else if (val && typeof val === 'object') {
            // Handle single object inputs
            newInputs[key] = this.cleanInputValue(val);
          }
        });
        newStep.inputs = newInputs;
      }
      return newStep;
    });

    // Transform user input outputs keys from display name to identifier
    const userInputOutputs: any = {};
    if (formValue.userInput && formValue.userInput.outputs) {
      Object.keys(formValue.userInput.outputs).forEach(key => {
        const cleanKey = this.toIdentifier(key);
        userInputOutputs[cleanKey] = formValue.userInput.outputs[key];
      });
    }

    const user_input_step = {
      ...formValue.userInput,
      outputs: userInputOutputs,
      stepId: `${NodeTypes.USER_INPUT}`,
      type: NodeTypes.USER_INPUT,
      status: StepStatusEnum.IDLE,
    }
    return [user_input_step, ...steps];
  }

  private cleanInputValue(val: any): any {
    if (!val || typeof val !== 'object') return val;

    let newVal = { ...val };

    // Handle _definitionId removal
    if (newVal._definitionId) {
      const { _definitionId, ...rest } = newVal;
      newVal = rest;
    }

    // Handle user input name transformation (display -> identifier)
    if (newVal.step === NodeTypes.USER_INPUT && newVal.output) {
      newVal = { ...newVal, output: this.toIdentifier(newVal.output) };
    }

    return newVal;
  }

  openRunModal(workflowId: string, userInputStep: any) {
    const dialogRef = this.dialog.open(RunWorkflowModalComponent, {
      width: '600px',
      data: { userInputStep }
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        // Immediately set status to give user feedback
        this.currentExecutionState = 'ACTIVE';
        // Set all steps to PENDING
        this.stepsArray.controls.forEach(control => {
          control.patchValue({ status: StepStatusEnum.PENDING });
        });

        this.isLoading = true;
        this.workflowService.executeWorkflow(workflowId, result).subscribe({
          next: (res) => {
            console.log('Workflow execution started', res);
            this.currentExecutionId = res.execution_id;
            this.currentExecutionState = 'ACTIVE';
            this.isLoading = false;
            handleSuccessSnackbar(this.snackBar, 'Workflow execution started!');
            // Start polling for execution status
            this.startPollingExecution(workflowId, res.execution_id);
          },
          error: (err) => {
            console.error('Failed to execute workflow', err);
            this.errorMessage = 'Failed to execute workflow';
            this.isLoading = false;
            handleErrorSnackbar(this.snackBar, err, 'Workflow execution');
          }
        });
      }
    });
  }

  onExecutionSelected(executionId: string): void {
    if (!this.workflowId) return;

    // No need to manually stop polling, new subscription will be isolated

    this.currentExecutionId = executionId;
    this.isLoading = true;

    // Fetch once immediately, then start polling (or just start polling, but this keeps UI snappy)
    this.workflowService.getExecutionDetails(this.workflowId, executionId).subscribe({
      next: (details) => {
        this.handleExecutionUpdate(details);
        this.isLoading = false;

        if (details.state === 'ACTIVE') {
          this.startPollingExecution(this.workflowId!, executionId);
        }
      },
      error: (err) => {
        console.error('Failed to load execution details', err);
        handleErrorSnackbar(this.snackBar, err, 'Load execution details');
        this.isLoading = false;
      }
    });
  }

  private startPollingExecution(workflowId: string, executionId: string): void {
    this.workflowService.pollExecutionDetails(workflowId, executionId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (details) => {
          this.handleExecutionUpdate(details);
        },
        error: (err) => {
          console.error('Polling error', err);
        }
      });
  }

  private handleExecutionUpdate(details: any): void {
    console.log('Execution details:', details);
    this.currentExecutionState = details.state;
    this.executionStepEntries = details.step_entries || [];
    this.updateStepStatuses(details);
    this.resolveMediaUrls(details);

    if (details.state !== 'ACTIVE') {
      if (details.state === 'SUCCEEDED') {
        handleSuccessSnackbar(this.snackBar, 'Workflow completed successfully!');
      } else {
        handleErrorSnackbar(
          this.snackBar,
          { message: `Workflow ${details.state.toLowerCase()}` },
          'Workflow Execution'
        );
      }
    }
  }

  private updateStepStatuses(details: any): void {
    if (!details.step_entries || details.step_entries.length === 0) {
      return;
    }

    // Create a map of step names to their latest status
    const stepStatusMap = new Map<string, string>();
    details.step_entries.forEach((entry: any) => {
      stepStatusMap.set(entry.step_id, entry.state);
    });

    // Update form controls
    this.stepsArray.controls.forEach((control) => {
      const stepId = control.get('stepId')?.value;
      if (stepId && stepStatusMap.has(stepId)) {
        const gcpState = stepStatusMap.get(stepId);
        let uiStatus = StepStatusEnum.IDLE;

        // Map GCP state to UI status
        switch (gcpState) {
          case 'STATE_IN_PROGRESS':
            uiStatus = StepStatusEnum.RUNNING;
            break;
          case 'STATE_SUCCEEDED':
            uiStatus = StepStatusEnum.COMPLETED;
            break;
          case 'STATE_FAILED':
            uiStatus = StepStatusEnum.FAILED;
            break;
        }

        control.patchValue({ status: uiStatus });
      }
    });

    // Update outputs from step entries
    details.step_entries.forEach((entry: any) => {
      const control = this.stepsArray.controls.find(c => c.get('stepId')?.value === entry.step_id);
      if (control && entry.step_outputs) {
        // We update the whole outputs object in the form control
        // This ensures the UI sees the new outputs
        control.patchValue({ outputs: entry.step_outputs });
      }
    });
  }

  // populateFormFromData and resetFormForNew removed, handled by service patchData and initForm

  // getStepIcon removed, use StepIconPipe in template

  // toDisplay removed, used in service. kept toIdentifier for prepareSteps

  private toIdentifier(name: string): string {
    return name ? name.trim().replace(/\s+/g, '_') : name;
  }



}

export enum EditorMode {
  Create,
  Edit,
  Run,
}
