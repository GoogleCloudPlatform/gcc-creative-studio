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

import { Component, EventEmitter, Input, OnChanges, OnInit, Output, SimpleChanges } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { Subscription } from 'rxjs';
import { ASPECT_RATIO_LABELS, MODEL_CONFIGS } from '../../../../common/config/model-config';
import { StepConfig } from './step.model';

@Component({
  selector: 'app-generic-step',
  templateUrl: './generic-step.component.html',
  styleUrls: ['./generic-step.component.scss'],
})
export class GenericStepComponent implements OnInit, OnChanges {
  isStepOutputReference(item: any): boolean {
    return item && typeof item === 'object' && !Array.isArray(item) && 'step' in item && 'output' in item;
  }
  getLinkedOutputLabel(item: any): string {
    const matchingOutput = this.availableOutputs.find(out =>
      out.value && out.value.step === item.step && out.value.output === item.output
    );
    return matchingOutput ? matchingOutput.label : 'Linked Output';
  }
  clearReferenceImage(inputName: string, index: number): void {
    const images = this.referenceImages[inputName];
    if (images && Array.isArray(images) && index >= 0 && index < images.length) {
      const updatedImages = [...images];
      updatedImages.splice(index, 1);
      this.stepForm.get('inputs')?.get(inputName)?.setValue(updatedImages);
    }
  }
openImageSelectorForReference(inputName: string, type: string): void {
    // TODO: Implement image selector logic, possibly by emitting an event
  }

addLinkedOutput(inputName: string, output: any): void {
    const current = this.referenceImages[inputName] || [];
    const updated = [...current, output.value];
    this.stepForm.get('inputs')?.get(inputName)?.setValue(updated);
  }

onReferenceImageDrop(event: DragEvent, inputName: string): void {
    // TODO: Implement drag-and-drop logic
  }
  @Input() stepForm!: FormGroup;
  @Input() stepIndex!: number;
  @Input() availableOutputs: any[] = [];
  @Input() mode: 'create' | 'edit' | 'run' = 'create';
  @Input() config!: StepConfig;
  @Input() showValidationErrors = false;
  @Output() delete = new EventEmitter<void>();

  localConfig!: StepConfig;
  private settingsSubscription?: Subscription;
  private inputModeSubscription?: Subscription;
  currentMaxReferenceImages = 1;

  isCollapsed = true;
  inputModes: { [key: string]: 'fixed' | 'linked' | 'mixed' } = {};
  compatibleOutputs: { [key: string]: any[] } = {};
  get referenceImages(): { [key: string]: any[] } {
    const inputs = this.stepForm.get('inputs');
    return inputs ? inputs.value : {};
  }
  compareFn!: (o1: any, o2: any) => boolean;

  constructor(
    private fb: FormBuilder,
  ) { }

  ngOnInit(): void {
    this.initializeStepState();
  }

  ngOnDestroy(): void {
    if (this.settingsSubscription) {
      this.settingsSubscription.unsubscribe();
    }
    if (this.inputModeSubscription) {
      this.inputModeSubscription.unsubscribe();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['stepForm']) {
      this.initializeStepState();
    }
    if (changes['availableOutputs']) {
      this.updateCompatibleOutputs();
    }
  }

  private initializeStepState(): void {
    if (!this.stepForm) return;

    // Deep copy config to localConfig to allow per-instance modifications
    this.localConfig = JSON.parse(JSON.stringify(this.config));

    this.inputModes = {};

    const inputs = this.stepForm.get('inputs') as FormGroup;
    if (!inputs) return;

    this.localConfig.inputs.forEach(input => {
      const validators = input.required ? [Validators.required] : [];

      if (!inputs.contains(input.name)) {
        inputs.addControl(input.name, this.fb.control(null, validators));
      } else {
        const control = inputs.get(input.name);
        control?.setValidators(validators);
        control?.updateValueAndValidity();
      }

      const value = inputs.get(input.name)?.value;

      // Determine if the input is linked (StepOutputReference)
      // It must be an object, not an array, and have 'step' and 'output' properties
      const isLinked = value && typeof value === 'object' && !Array.isArray(value) && 'step' in value && 'output' in value;

      if (isLinked) {
        this.inputModes[input.name] = 'linked';
      } else if (Array.isArray(value)) {
        this.inputModes[input.name] = 'mixed';
      } else {
        this.inputModes[input.name] = 'fixed';
      }
    });

    const settings = this.stepForm.get('settings') as FormGroup;
    if (settings) {
      this.config.settings.forEach(setting => {
        if (!settings.contains(setting.name)) {
          settings.addControl(setting.name, this.fb.control(setting.defaultValue));
        }
      });

      // Subscribe to model changes
      if (settings.contains('model')) {
        const modelControl = settings.get('model');
        if (this.settingsSubscription) {
          this.settingsSubscription.unsubscribe();
        }
        this.settingsSubscription = modelControl?.valueChanges.subscribe(value => {
          this.updateDynamicConfig(value);
        });

        // Initial update
        this.updateDynamicConfig(modelControl?.value);
      }

      // Subscribe to input_mode changes
      if (settings.contains('input_mode')) {
        const modeControl = settings.get('input_mode');
        if (this.inputModeSubscription) {
          this.inputModeSubscription.unsubscribe();
        }
        this.inputModeSubscription = modeControl?.valueChanges.subscribe(() => {
          this.updateInputVisibility();
        });
      }
    }

    const outputs = this.stepForm.get('outputs') as FormGroup;
    if (outputs) {
      this.localConfig.outputs.forEach(output => {
        if (!outputs.contains(output.name)) {
          outputs.addControl(output.name, this.fb.control({ type: output.type }));
        }
      });
    }

    this.updateCompatibleOutputs();
  }

  private updateDynamicConfig(modelValue: string | null): void {
    if (!modelValue) return;

    // Find config in MODEL_CONFIGS
    const modelConfig = MODEL_CONFIGS.find(c => c.value === modelValue);

    if (!modelConfig) return;

    // Use capabilities
    const modelMeta = modelConfig.capabilities;

    // 1. Update Aspect Ratio options
    if (modelMeta.supportedAspectRatios) {
      const aspectRatioSetting = this.localConfig.settings.find(s => s.name === 'aspect_ratio');
      if (aspectRatioSetting) {
        // Generate options dynamically using ASPECT_RATIO_LABELS
        aspectRatioSetting.options = modelMeta.supportedAspectRatios.map(ratio => ({
          value: ratio,
          label: ASPECT_RATIO_LABELS[ratio] || ratio
        }));

        // Reset value if current value is invalid
        const currentAspectRatio = this.stepForm.get('settings.aspect_ratio')?.value;
        if (currentAspectRatio && !modelMeta.supportedAspectRatios.includes(currentAspectRatio)) {
          // Set to first available option
          const firstOption = aspectRatioSetting.options?.[0]?.value;
          if (firstOption) {
            this.stepForm.get('settings.aspect_ratio')?.setValue(firstOption);
          }
        }
      }
    }

    // 2. Update Generation Mode (input_mode)
    if (modelMeta.supportedModes) {
      const modeSetting = this.localConfig.settings.find(s => s.name === 'input_mode');
      if (modeSetting) {
        modeSetting.options = modelMeta.supportedModes.map(mode => ({
          value: mode,
          label: mode
        }));

        // Default to first mode if current is invalid
        const currentMode = this.stepForm.get('settings.input_mode')?.value;
        if (!currentMode || !modelMeta.supportedModes.includes(currentMode)) {
          // Prefer 'Text to Video' if available, else first
          const defaultMode = modelMeta.supportedModes.includes('Text to Video') ? 'Text to Video' : modelMeta.supportedModes[0];
          this.stepForm.get('settings.input_mode')?.setValue(defaultMode);
        }
      }
    }

    // 3. Update Audio Settings Visibility
    this.localConfig.settings.forEach(setting => {
      if (setting.name === 'voice_name') {
        setting.hidden = !modelMeta.supportsVoice;
      }
      if (setting.name === 'language_code') {
        setting.hidden = !modelMeta.supportsLanguage;
      }
      if (setting.name === 'seed') {
        setting.hidden = !modelMeta.supportsSeed;
      }
      if (setting.name === 'negative_prompt') {
        setting.hidden = !modelMeta.supportsNegativePrompt;
      }
    });

    // 4. Update Inputs based on Mode and Max Refs
    const maxRefs = modelMeta.maxReferenceImages; // 0, 1, or more
    this.currentMaxReferenceImages = maxRefs;

    this.updateInputVisibility();
  }

  private updateInputVisibility(): void {
    const currentMode = this.stepForm.get('settings.input_mode')?.value;
    const maxRefs = this.currentMaxReferenceImages;

    this.localConfig.inputs.forEach(input => {
      // Logic for specific inputs
      if (this.localConfig.type === 'generate-video' && (input.name === 'input_images' || input.name === 'reference_images')) {
        const showIngredients = currentMode === 'Ingredients to Video';

        if (showIngredients && maxRefs > 0) {
          input.hidden = false;
          this.stepForm.get('inputs')?.get(input.name)?.enable();
          // Force mixed mode for list inputs if they are enabled
          if (input.type === 'image' || input.type === 'video') {
            this.inputModes[input.name] = 'mixed';
          }
        } else {
          input.hidden = true;
          this.stepForm.get('inputs')?.get(input.name)?.disable();
        }
      } else if (input.name === 'start_frame' || input.name === 'end_frame') {
        if (currentMode === 'Frames to Video') {
          input.hidden = false;
          this.stepForm.get('inputs')?.get(input.name)?.enable();
          if (input.type === 'image' || input.type === 'video') {
            this.inputModes[input.name] = 'mixed';
          }
        } else {
          input.hidden = true;
          this.stepForm.get('inputs')?.get(input.name)?.disable();
        }
      } else {
        // Default for other inputs: if it allows multiple, set to mixed
        if ((input.type === 'image' || input.type === 'video') && maxRefs > 1) {
          this.inputModes[input.name] = 'mixed';
        }
      }
    });
  }

  private updateCompatibleOutputs(): void {
    if (!this.localConfig || !this.availableOutputs) {
      return;
    }
    this.localConfig.inputs.forEach(input => {
      this.compatibleOutputs[input.name] = this.availableOutputs.filter(
        output => (output.type === input.type) || (output.type === "text" && input.type === "textarea") || (output.type === 'image' && input.type === 'image')
      );
    });
  }

  toggleInputMode(inputName: string, mode: 'fixed' | 'linked' | 'mixed') {
    this.inputModes[inputName] = mode;
    this.stepForm
      .get('inputs')
      ?.get(inputName)
      ?.setValue(null);
  }
}
