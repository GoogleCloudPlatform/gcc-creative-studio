
import { Injectable } from '@angular/core';
import { FormArray, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { pairwise, startWith } from 'rxjs/operators';
import { STEP_CONFIGS_MAP } from '../shared/step-configs.map';
import { NodeTypes, StepStatusEnum, WorkflowBase, WorkflowModel } from '../workflow.models';

@Injectable()
export class WorkflowFormService {
  public workflowForm!: FormGroup;

  private _availableOutputsPerStep = new BehaviorSubject<any[][]>([]);
  public availableOutputsPerStep$ = this._availableOutputsPerStep.asObservable();

  constructor(private fb: FormBuilder) { }

  /**
   * Initializes the main workflow form.
   * Call this in the component's ngOnInit.
   */
  initForm(data?: WorkflowModel | WorkflowBase): FormGroup {
    this.workflowForm = this.fb.group({
      id: [data && 'id' in data ? data.id : ''],
      name: [data?.name || 'Untitled Workflow', Validators.required],
      description: [data?.description || ''],
      userId: [data && 'userId' in data ? data.userId : ''],
      // User Input Step is special, so we initialize it specifically
      userInput: this.fb.group({
        stepId: [NodeTypes.USER_INPUT],
        type: [NodeTypes.USER_INPUT],
        status: [StepStatusEnum.IDLE],
        outputs: this.fb.group({}),
        settings: this.fb.group({
          definitions: this.fb.array([]),
        }),
      }),
      steps: this.fb.array([]),
    });

    if (data) {
      this.patchData(data);
    } else {
      // Default initialization for new workflows
      this.addOutputDefinition('User_Text_Input', 'text');
      this.addOutputDefinition('User_Image_Input', 'image');
    }

    // Subscribe to output definition changes for renaming
    this.outputDefinitionsArray.valueChanges
      .pipe(
        startWith(this.outputDefinitionsArray.getRawValue()),
        pairwise()
      )
      .subscribe(([prev, curr]) => {
        this.handleOutputRenames(prev, curr);
        this.syncOutputs(); // Also ensure outputs group is synced
      });

    // Initial sync of outputs and available outputs after form is built
    this.syncOutputs();

    return this.workflowForm;
  }

  // --- Getters for easy access ---
  get stepsArray(): FormArray {
    return this.workflowForm.get('steps') as FormArray;
  }

  get outputDefinitionsArray(): FormArray {
    return this.workflowForm.get('userInput.settings.definitions') as FormArray;
  }

  // --- Step Manipulation ---

  addStep(type: string, existingData?: any): void {
    const stepData = existingData || this.generateDefaultStepData(type);

    // Ensure inputs/outputs/settings are objects
    const safeStepData = {
      ...stepData,
      inputs: stepData.inputs || {},
      outputs: stepData.outputs || {},
      settings: stepData.settings || {}
    };

    const stepGroup = this.fb.group({
      stepId: [safeStepData.stepId],
      type: [safeStepData.type],
      status: [safeStepData.status || StepStatusEnum.IDLE],
      inputs: this.createFormGroupFromData(safeStepData.inputs),
      outputs: this.createFormGroupFromData(safeStepData.outputs),
      settings: this.createFormGroupFromData(safeStepData.settings),
    });

    this.stepsArray.push(stepGroup);
    this.updateAvailableOutputs();
  }

  deleteStep(index: number): string | null {
    const stepControl = this.stepsArray.at(index);
    const stepId = stepControl?.get('stepId')?.value;
    this.stepsArray.removeAt(index);
    return stepId; // Return ID so component can handle dependent cleanup if needed
  }

  /**
   * After a step is deleted, we must also update available outputs.
   * NOTE: Component still handles 'clearDependents' because it traverses inputs.
   * We could move that here too in a future step.
   */
  updateAfterDelete() {
    this.updateAvailableOutputs();
  }

  moveStep(previousIndex: number, currentIndex: number): void {
    const currentControl = this.stepsArray.at(previousIndex);
    this.stepsArray.removeAt(previousIndex);
    this.stepsArray.insert(currentIndex, currentControl);
    this.updateAvailableOutputs();
  }

  // --- User Input Definitions ---

  addOutputDefinition(name: string = '', type: string = 'text', id?: string): void {
    const group = this.fb.group({
      id: [id || this.generateId()],
      name: [name, Validators.required],
      type: [type, Validators.required],
    });
    this.outputDefinitionsArray.push(group);
    // syncOutputs is now handled by the valueChanges subscription
  }

  removeOutputDefinition(index: number): void {
    this.outputDefinitionsArray.removeAt(index);
    // syncOutputs is now handled by the valueChanges subscription
  }

  // --- Logic moved from Component ---

  syncOutputs(): void {
    const outputs = this.workflowForm.get('userInput.outputs') as FormGroup;

    Object.keys(outputs.controls).forEach(key => outputs.removeControl(key));
    this.outputDefinitionsArray.controls.forEach(control => {
      const name = control.get('name')?.value;
      const type = control.get('type')?.value;
      if (name && type) {
        // We use this.fb.control because we inject FormBuilder
        outputs.addControl(name, this.fb.control({ type: type }));
      }
    });
    this.updateAvailableOutputs();
  }

  private handleOutputRenames(prevDefinitions: any[], currentDefinitions: any[]) {
    const prevMap = new Map(prevDefinitions.map(d => [d.id, d]));

    currentDefinitions.forEach(newDef => {
      const oldDef = prevMap.get(newDef.id);
      if (oldDef && oldDef.name && newDef.name && oldDef.name !== newDef.name) {
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
          // Update the output name in the reference
          control?.setValue({ ...value, output: newName });
        }
      });
    });
  }

  private updateAvailableOutputs(): void {
    if (!this.workflowForm) return;

    const userInputOutputs: any[] = [];
    this.outputDefinitionsArray.controls.forEach(control => {
      const val = control.value;
      if (val.name && val.type) {
        userInputOutputs.push({
          label: `User Input: ${val.name} `,
          value: {
            step: "user_input",
            output: val.name,
            _definitionId: val.id
          },
          type: val.type,
        });
      }
    });

    const steps = this.stepsArray.controls;
    const availableOutputsPerStep = steps.map((_, currentStepIndex) => {
      const previousSteps = steps.slice(0, currentStepIndex);
      const availableOutputs: any[] = [...userInputOutputs];

      previousSteps.forEach((stepControl, stepIndex) => {
        const step = stepControl.value;
        // Access static config
        const stepConfig = (STEP_CONFIGS_MAP as any)[step.type];
        if (!stepConfig) return;

        stepConfig.outputs.forEach((output: any) => {
          availableOutputs.push({
            label: `Step ${stepIndex + 1}: ${output.label} `,
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

    this._availableOutputsPerStep.next(availableOutputsPerStep);
  }

  // --- Data Patching ---

  patchData(data: WorkflowModel | WorkflowBase): void {
    const userInputStep = data.steps?.find(s => s.type === NodeTypes.USER_INPUT);
    const otherSteps = data.steps?.filter(s => s.type !== NodeTypes.USER_INPUT) || [];

    // 1. Patch Main Fields
    this.workflowForm.patchValue({
      id: 'id' in data ? data.id : '',
      name: data.name,
      description: data.description,
      userInput: {
        ...(userInputStep || {}),
        status: StepStatusEnum.IDLE
      }
    });

    // 2. Rebuild User Input Definitions & Map IDs
    this.outputDefinitionsArray.clear();
    const outputIdMap = new Map<string, string>();

    if (userInputStep?.outputs) {
      Object.entries(userInputStep.outputs).forEach(([key, value]: [string, any]) => {
        // Reverse engineer the ID and Name from the stored output
        const id = this.generateId();
        outputIdMap.set(key, id);
        this.addOutputDefinition(this.toDisplay(key), value.type, id);
      });
    }

    // 3. Rebuild Steps
    this.stepsArray.clear();
    otherSteps.forEach(step => {
      let stepData = { ...step, status: StepStatusEnum.IDLE };

      // Backfill _definitionId into inputs and transform output names to display names 
      // if they reference user input
      if (stepData.inputs) {
        const newInputs = { ...stepData.inputs };
        let changed = false;
        Object.values(newInputs).forEach((input: any) => {
          // Check if it's a user input reference
          if (input && typeof input === 'object' && input.step === NodeTypes.USER_INPUT && input.output) {
            // If we have a mapped ID for this user output
            if (outputIdMap.has(input.output)) {
              input._definitionId = outputIdMap.get(input.output);
              input.output = this.toDisplay(input.output);
              changed = true;
            }
          }
        });
        if (changed) {
          stepData.inputs = newInputs;
        }
      }

      this.addStep(step.type, stepData);
    });

    // Final sync
    this.syncOutputs();
  }

  // --- Helpers ---

  private generateDefaultStepData(type: string): any {
    const base: any = {
      stepId: `${type}_${Date.now()}`,
      type: type,
      status: StepStatusEnum.IDLE,
      inputs: {},
      outputs: {},
      settings: {},
    };

    // Default settings logic
    if (type === NodeTypes.EDIT_IMAGE) {
      base.settings = { aspectRatio: '1:1', saveOutputToGallery: true };
    }
    return base;
  }

  private createFormGroupFromData(data: any): FormGroup {
    const groupConfig: any = {};
    if (data) {
      Object.keys(data).forEach(key => {
        // Wrap in array for FormBuilder
        groupConfig[key] = [data[key]];
      });
    }
    return this.fb.group(groupConfig);
  }

  private generateId(): string {
    return Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
  }

  private toDisplay(name: string): string {
    return name ? name.replace(/_/g, ' ') : name;
  }
}
