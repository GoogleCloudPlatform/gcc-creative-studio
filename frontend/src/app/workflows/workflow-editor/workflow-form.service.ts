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

import {Injectable, PLATFORM_ID, inject} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {
  AbstractControl,
  FormArray,
  FormBuilder,
  FormGroup,
  Validators,
} from '@angular/forms';
import {BehaviorSubject} from 'rxjs';
import {pairwise, startWith} from 'rxjs/operators';
import {STEP_CONFIGS_MAP} from '../shared/step-configs.map';
import {labelToName, nameToLabel} from '../utils/workflow-step.util';
import {
  NodeTypes,
  StepStatusEnum,
  WorkflowBase,
  WorkflowModel,
} from '../workflow.models';

type NodePort = {
  stepId: string;
  output: string;
  _definitionId: string;
  step: NodeTypes;
};

@Injectable()
export class WorkflowFormService {
  private platformId = inject(PLATFORM_ID);
  public workflowForm!: FormGroup;

  private _availableOutputsPerStep = new BehaviorSubject<any[][]>([]);
  public availableOutputsPerStep$ =
    this._availableOutputsPerStep.asObservable();

  constructor(private fb: FormBuilder) {}

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
      this.addOutputDefinition('User Text Input', 'text');
      this.addOutputDefinition('User Image Input', 'image');
    }

    // Subscribe to output definition changes for renaming
    if (isPlatformBrowser(this.platformId)) {
      this.outputDefinitionsArray.valueChanges
        .pipe(startWith(this.outputDefinitionsArray.getRawValue()), pairwise())
        .subscribe(([prev, curr]) => {
          this.handleOutputRenames(prev, curr);
          this.syncOutputs(); // Also ensure outputs group is synced
        });
    }

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
      settings: stepData.settings || {},
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

  addOutputDefinition(name = '', type = 'text', id?: string): void {
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
        outputs.addControl(name, this.fb.control({type: type}));
      }
    });
    this.updateAvailableOutputs();
  }

  private handleOutputRenames(
    prevDefinitions: any[],
    currentDefinitions: any[],
  ) {
    const prevMap = new Map(prevDefinitions.map(d => [d.id, d]));

    currentDefinitions.forEach(newDef => {
      const oldDef = prevMap.get(newDef.id);
      if (oldDef && oldDef.name && newDef.name && oldDef.name !== newDef.name) {
        this.updateStepReferences(
          this.stepsArray.controls,
          newDef.id,
          newDef.name,
        );
      }
    });
  }

  public updateStepReferences(
    controls: AbstractControl[],
    definitionId: string,
    newName: string,
  ) {
    controls.forEach(stepControl => {
      const inputs = stepControl.get('inputs') as FormGroup;
      if (!inputs) return;

      Object.keys(inputs.controls).forEach(inputKey => {
        const control = inputs.get(inputKey);
        const value = control?.value as NodePort | NodePort[];
        if (Array.isArray(value)) {
          let updated = false;
          const newValue = value.map((item: NodePort) => {
            if (this.isUserInputAndHasDefinitionId(item, definitionId)) {
              updated = true;
              return {...item, output: newName};
            }
            return item;
          });
          if (updated) {
            control?.setValue(newValue);
          }
        } else if (this.isUserInputAndHasDefinitionId(value, definitionId)) {
          control?.setValue({...value, output: newName});
        }
      });
    });
  }

  private isUserInputAndHasDefinitionId(
    item: NodePort,
    definitionId: string,
  ): boolean {
    return this.isUserInput(item) && item._definitionId === definitionId;
  }

  private isUserInput(item: NodePort): boolean {
    return (
      item && typeof item === 'object' && item.step === NodeTypes.USER_INPUT
    );
  }

  private updateAvailableOutputs(): void {
    if (!this.workflowForm) return;

    const userInputOutputs: any[] = [];
    this.outputDefinitionsArray.controls.forEach(control => {
      const val = control.value;
      if (val.name && val.type) {
        userInputOutputs.push({
          label: `User Input: ${nameToLabel(val.name)} `,
          value: {
            step: 'user_input',
            output: val.name,
            _definitionId: val.id,
          },
          type: val.type,
        });
      }
    });

    const steps = this.stepsArray.controls;
    const availableOutputsPerStep = steps.map((_, currentStepIndex) => {
      // Allow connecting to any node except itself to avoid immediate self-loops
      const otherSteps = steps.filter((_, idx) => idx !== currentStepIndex);
      const availableOutputs: any[] = [...userInputOutputs];

      otherSteps.forEach(stepControl => {
        const step = stepControl.value;
        const stepIndex = steps.indexOf(stepControl);

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

  patchData(data: any): void {
    const userInputStep =
      data.userInput ||
      data.steps?.find((s: any) => s.type === NodeTypes.USER_INPUT);
    const otherSteps =
      data.steps?.filter((s: any) => s.type !== NodeTypes.USER_INPUT) || [];

    // 1. Patch Main Fields
    this.workflowForm.patchValue({
      id: 'id' in data ? data.id : '',
      name: data.name,
      description: data.description,
      userInput: {
        ...(userInputStep || {}),
        status: StepStatusEnum.IDLE,
      },
    });

    // 2. Rebuild User Input Definitions & Map IDs
    this.outputDefinitionsArray.clear();
    const outputIdMap = new Map<string, string>();
    const outputNameMap = new Map<string, string>();

    if (
      userInputStep?.settings?.definitions &&
      userInputStep.settings.definitions.length > 0
    ) {
      userInputStep.settings.definitions.forEach((def: any) => {
        const id = def.id || this.generateId();
        const displayName = nameToLabel(def.name);
        const identifier = labelToName(displayName);
        outputIdMap.set(identifier, id);
        outputIdMap.set(displayName, id);
        outputIdMap.set(def.name, id);
        outputNameMap.set(identifier, displayName);
        outputNameMap.set(displayName, displayName);
        outputNameMap.set(def.name, displayName);
        this.addOutputDefinition(displayName, def.type, id);
      });
    } else if (userInputStep?.outputs) {
      Object.entries(userInputStep.outputs).forEach(
        ([key, value]: [string, any]) => {
          // Reverse engineer the ID and Name from the stored output
          const id = this.generateId();
          const displayName = nameToLabel(key);
          const identifier = labelToName(displayName);
          outputIdMap.set(key, id);
          outputIdMap.set(identifier, id);
          outputIdMap.set(displayName, id);
          outputNameMap.set(key, displayName);
          outputNameMap.set(identifier, displayName);
          outputNameMap.set(displayName, displayName);
          this.addOutputDefinition(displayName, value.type, id);
        },
      );
    }

    // 3. Rebuild Steps
    this.stepsArray.clear();
    otherSteps.forEach((step: any) => {
      const stepData = {...step, status: StepStatusEnum.IDLE};

      // Backfill _definitionId into inputs and transform output names to display names
      // if they reference user input
      if (stepData.inputs) {
        const newInputs = {...stepData.inputs};
        let changed = false;

        const transformRef = (item: NodePort) => {
          if (this.isUserInput(item) && item.output) {
            const definitionId = outputIdMap.get(item.output);
            const newName = outputNameMap.get(item.output);
            if (definitionId) item._definitionId = definitionId;
            item.output = newName ? newName : nameToLabel(item.output);
            changed = true;
          }
        };

        Object.keys(newInputs).forEach(key => {
          const val = newInputs[key];
          const values = Array.isArray(val) ? val : [val];
          values.forEach(item => transformRef(item));
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
      base.settings = {aspectRatio: '1:1', saveOutputToGallery: true};
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
    return (
      Math.random().toString(36).substring(2, 15) +
      Math.random().toString(36).substring(2, 15)
    );
  }
}
