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

import { CdkDragDrop, moveItemInArray } from '@angular/cdk/drag-drop';
import { Component, OnDestroy, OnInit } from '@angular/core';
import {
  AbstractControl,
  FormArray,
  FormBuilder,
  FormGroup,
  Validators,
} from '@angular/forms';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ActivatedRoute, Router } from '@angular/router';
import { Observable, Subscription, interval, of } from 'rxjs';
import { finalize, switchMap, takeWhile, tap } from 'rxjs/operators';
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
import { WorkflowService } from '../workflow.service';
import { AddStepModalComponent } from './add-step-modal/add-step-modal.component';
import { RunWorkflowModalComponent } from './run-workflow-modal/run-workflow-modal.component';

import { STEP_CONFIGS_MAP } from '../shared/step-configs.map';



@Component({
  selector: 'app-workflow-editor',
  templateUrl: './workflow-editor.component.html',
  styleUrls: ['./workflow-editor.component.scss'],
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
  workflowForm!: FormGroup;
  isLoading = false;
  submitted = false;
  errorMessage: string | null = null;
  selectedStepIndex: number | null = null;
  get selectedStep(): any | null {
    if (this.selectedStepIndex === null) return null;
    if (this.selectedStepIndex < 0 || this.selectedStepIndex >= this.stepsArray.length) {
      return null;
    }
    return this.stepsArray.at(this.selectedStepIndex).value;
  }

  get selectedStepExecution(): any | null {
    if (!this.selectedStep || !this.executionStepEntries) return null;
    const entry = this.executionStepEntries.find(e => e.step_id === this.selectedStep.stepId);
    return entry ? entry : null;
  }
  availableOutputsPerStep: any[][] = [];
  previousOutputDefinitions: any[] = [];

  private mainSubscription!: Subscription;
  private pollingSubscription?: Subscription;
  currentExecutionId: string | null = null;
  currentExecutionState: string | null = null;
  executionStepEntries: any[] = [];
  mediaUrlMap = new Map<string, string>();
  loadedMedia = new Set<string>();


  constructor(
    private fb: FormBuilder,
    private route: ActivatedRoute,
    private router: Router,
    private workflowService: WorkflowService,
    private dialog: MatDialog,
    private snackBar: MatSnackBar,
    private mediaResolutionService: MediaResolutionService,
  ) {
    this.initForm();
  }

  asFormGroup(control: AbstractControl): FormGroup {
    return control as FormGroup;
  }

  ngOnInit(): void {
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
            this.populateFormFromData(this.displayedWorkflow);
            this.workflowForm.disable(); // Read-only mode
          } else if (this.mode === EditorMode.Edit) {
            this.workflow = data as WorkflowModel;
            this.displayedWorkflow = this.workflow;
            this.populateFormFromData(this.displayedWorkflow);
          } else {
            this.resetFormForNew();
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
    this.syncOutputs();
    this.previousOutputDefinitions = this.outputDefinitionsArray.getRawValue();
    this.outputDefinitionsArray.valueChanges.subscribe((currentValues) => {
      this.handleOutputRenames(currentValues);
      this.syncOutputs();
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
    if (this.pollingSubscription) {
      this.pollingSubscription.unsubscribe();
    }
  }

  initForm() {
    this.workflowForm = this.fb.group({
      id: [''],
      name: ['Untitled Workflow', Validators.required],
      description: [''],
      userId: ['user123'],
      userInput: this.fb.group({
        stepId: ['user_input'],
        type: ['user_input'],
        status: [StepStatusEnum.IDLE],
        outputs: this.fb.group({}),
        settings: this.fb.group({
          definitions: this.fb.array([]),
        }),
      }),
      steps: this.fb.array([]),
    });
  }

  get stepsArray(): FormArray {
    return this.workflowForm.get('steps') as FormArray;
  }

  get outputDefinitionsArray(): FormArray {
    return this.workflowForm.get('userInput.settings.definitions') as FormArray;
  }

  private generateId(): string {
    return Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
  }

  private createOutputDefinition(name: string, type: string, id?: string): FormGroup {
    return this.fb.group({
      id: [id || this.generateId()],
      name: [name, Validators.required],
      type: [type, Validators.required],
    });
  }

  addOutput(name = '', type = 'text', id?: string): void {
    this.outputDefinitionsArray.push(this.createOutputDefinition(name, type, id));
  }

  removeOutput(index: number): void {
    this.outputDefinitionsArray.removeAt(index);
  }

  private syncOutputs(): void {
    const outputs = this.workflowForm.get('userInput.outputs') as FormGroup;

    Object.keys(outputs.controls).forEach(key => outputs.removeControl(key));
    this.outputDefinitionsArray.controls.forEach(control => {
      const name = control.get('name')?.value;
      const type = control.get('type')?.value;
      if (name && type) {
        outputs.addControl(name, this.fb.control({ type: type }));
      }
    });
    this.updateAvailableOutputs();
  }

  updateAvailableOutputs(): void {
    const userInputOutputs: any[] = [];
    this.outputDefinitionsArray.controls.forEach(control => {
      const val = control.value;
      if (val.name && val.type) {
        userInputOutputs.push({
          label: `User Input: ${val.name}`,
          value: {
            step: "user_input",
            output: val.name,
            _definitionId: val.id
          },
          type: val.type,
        });
      }
    });

    this.availableOutputsPerStep = this.stepsArray.controls.map((_, currentStepIndex) => {
      const previousSteps = this.stepsArray.controls.slice(0, currentStepIndex);
      const availableOutputs: any[] = [...userInputOutputs];

      previousSteps.forEach((stepControl, stepIndex) => {
        const step = stepControl.value;
        const stepConfig = this.getStepConfig(step.type);
        if (!stepConfig) return;

        stepConfig.outputs.forEach((output: any) => {
          availableOutputs.push({
            label: `Step ${stepIndex + 1}: ${output.label}`,
            value: {
              step: step.stepId,
              output: output.name,
            },
            type: output.type,
          });
        });
      });
      return availableOutputs;
    });
  }

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
    let stepData = existingData || {
      stepId: `${type}_${Date.now()}`,
      type: type,
      status: StepStatusEnum.IDLE,
      inputs: {},
      outputs: {},
      settings: {},
    };

    // Set default settings for specific step types if not already present
    if (!existingData) {
      switch (type) {
        case NodeTypes.EDIT_IMAGE:
          stepData.settings = {
            ...stepData.settings,
            aspectRatio: '1:1', // Default value
            saveOutputToGallery: true, // Default value
          };
          break;
        // Add other step types with their default settings here if needed
      }
    }

    const stepGroup = this.fb.group({
      stepId: [stepData.stepId],
      type: [stepData.type],
      status: [stepData.status],
      inputs: this.createFormGroupFromData(stepData.inputs),
      outputs: this.createFormGroupFromData(stepData.outputs),
      settings: this.createFormGroupFromData(stepData.settings),
    });

    this.stepsArray.push(stepGroup);
    this.updateAvailableOutputs();
  }

  private createFormGroupFromData(data: any): FormGroup {
    const groupConfig: any = {};
    if (data) {
      Object.keys(data).forEach(key => {
        // Wrap value in array so FormBuilder treats it as [value, validators]
        // This prevents arrays in data from being interpreted as validator configs
        groupConfig[key] = [data[key]];
      });
    }
    return this.fb.group(groupConfig);
  }

  deleteStep(index: number) {
    const deletedStepId = this.stepsArray.at(index).get('stepId')?.value;

    this.stepsArray.removeAt(index);

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

    this.updateAvailableOutputs();
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
    moveItemInArray(
      this.stepsArray.controls,
      event.previousIndex,
      event.currentIndex,
    );

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

    this.updateAvailableOutputs();
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

    // Stop any existing polling
    if (this.pollingSubscription) {
      this.pollingSubscription.unsubscribe();
      this.pollingSubscription = undefined;
    }

    this.currentExecutionId = executionId;
    this.isLoading = true;

    this.workflowService.getExecutionDetails(this.workflowId, executionId).subscribe({
      next: (details) => {
        this.currentExecutionState = details.state;
        this.executionStepEntries = details.step_entries || [];
        this.updateStepStatuses(details);
        this.resolveMediaUrls(details); // Resolve media URLs
        this.isLoading = false;

        // If the selected execution is active, start polling
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
    // Poll every 5 seconds
    this.pollingSubscription = interval(10000)
      .pipe(
        switchMap(() => this.workflowService.getExecutionDetails(workflowId, executionId)),
        takeWhile((details) => {
          // Continue polling while execution is active
          return details.state === 'ACTIVE';
        }, true), // inclusive: emit the final non-ACTIVE state
        finalize(() => {
          console.log('Polling stopped');
          this.pollingSubscription = undefined;
        })
      )
      .subscribe({
        next: (details) => {
          console.log('Execution details:', details);
          this.currentExecutionState = details.state;
          this.executionStepEntries = details.step_entries || [];
          this.updateStepStatuses(details);
          this.resolveMediaUrls(details); // Resolve media URLs

          // If execution completed, show notification
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
        },
        error: (err) => {
          console.error('Failed to get execution details', err);
        }
      });
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

  private populateFormFromData(data: WorkflowModel | WorkflowBase | null) {
    if (!data) {
      this.resetFormForNew();
      return;
    }

    const userInputStep = data.steps?.find(s => s.type === NodeTypes.USER_INPUT);
    const otherSteps = data.steps?.filter(s => s.type !== NodeTypes.USER_INPUT) || [];
    this.workflowForm.get('userInput.outputs') as FormGroup
    // Patch basic form values
    this.workflowForm.patchValue({
      ...data,
      userInput: {
        ...(userInputStep || (this.workflowForm.get('userInput') as FormGroup).value),
        status: StepStatusEnum.IDLE // Force IDLE status
      },
    });

    // Clear and populate the output definitions from the loaded data
    this.outputDefinitionsArray.clear();
    const outputIdMap = new Map<string, string>();

    if (userInputStep && userInputStep.outputs) {
      Object.entries(userInputStep.outputs).forEach(([key, value]: [string, any]) => {
        const id = this.generateId();
        outputIdMap.set(key, id);
        // Transform key (identifier) to display name
        this.addOutput(this.toDisplay(key), value.type, id);
      });
    }

    // Clear and populate the steps
    this.stepsArray.clear();
    otherSteps.forEach(step => {
      // Backfill _definitionId into inputs
      // Backfill _definitionId into inputs
      if (step.inputs) {
        Object.values(step.inputs).forEach((input: any) => {
          if (input && input.step === NodeTypes.USER_INPUT && input.output && outputIdMap.has(input.output)) {
            input._definitionId = outputIdMap.get(input.output);
            // Transform output name to display format to match UI
            input.output = this.toDisplay(input.output);
          }
        });
      }
      // Force status to IDLE
      const stepWithResetStatus = { ...step, status: StepStatusEnum.IDLE };
      this.addStepToForm(step.type, stepWithResetStatus);
    });

    // Sync everything
    this.syncOutputs();
  }

  private resetFormForNew() {
    console.log("Reset form for new")
    this.workflowForm.reset();
    this.workflowForm.patchValue({
      name: 'Untitled Workflow',
      userId: '',
    });
    this.stepsArray.clear();
    this.outputDefinitionsArray.clear();
    this.addOutput('User_Text_Input', 'text');
    this.addOutput('User_Image_Input', 'image');
    this.updateAvailableOutputs();
  }

  getStepIcon(type: string): string {
    switch (type) {
      case NodeTypes.USER_INPUT:
        return 'input';
      case NodeTypes.GENERATE_TEXT:
        return 'text_fields';
      case NodeTypes.GENERATE_IMAGE:
        return 'image';
      case NodeTypes.EDIT_IMAGE:
        return 'edit';
      case NodeTypes.CROP_IMAGE:
        return 'crop';
      case NodeTypes.GENERATE_VIDEO:
        return 'videocam';
      case NodeTypes.VIRTUAL_TRY_ON:
        return 'checkroom';
      default:
        return 'extension';
    }
  }

  private toDisplay(name: string): string {
    return name ? name.replace(/_/g, ' ') : name;
  }

  private toIdentifier(name: string): string {
    return name ? name.trim().replace(/\s+/g, '_') : name;
  }


  getStepStatusChipClass(status: StepStatusEnum): string {
    switch (status) {
      case StepStatusEnum.PENDING:
        return '!bg-gray-500/20 !text-gray-300';
      case StepStatusEnum.RUNNING:
        return '!bg-blue-500/20 !text-blue-300';
      case StepStatusEnum.COMPLETED:
        return '!bg-green-500/20 !text-green-300';
      case StepStatusEnum.FAILED:
        return '!bg-red-500/20 !text-red-300';
      case StepStatusEnum.SKIPPED:
        return '!bg-amber-500/20 !text-amber-300';
      case StepStatusEnum.IDLE:
      default:
        return 'hidden';
    }
  }

  getStepStatusIcon(status: StepStatusEnum): string {
    switch (status) {
      case StepStatusEnum.RUNNING:
        return 'hourglass_top';
      case StepStatusEnum.COMPLETED:
        return 'check_circle';
      case StepStatusEnum.FAILED:
        return 'error';
      default:
        return '';
    }
  }

  getWorkflowStatusClass(state: string | null): string {
    switch (state) {
      case 'ACTIVE':
        return '!bg-blue-500/20 !text-blue-300';
      case 'SUCCEEDED':
        return '!bg-green-500/20 !text-green-300';
      case 'FAILED':
      case 'CANCELLED':
        return '!bg-red-500/20 !text-red-300';
      default:
        return '!bg-gray-500/20 !text-gray-300';
    }
  }

  getWorkflowStatusIcon(state: string | null): string {
    switch (state) {
      case 'ACTIVE':
        return 'hourglass_top';
      case 'SUCCEEDED':
        return 'check_circle';
      case 'FAILED':
      case 'CANCELLED':
        return 'error';
      default:
        return '';
    }
  }
}

export enum EditorMode {
  Create,
  Edit,
  Run,
}
