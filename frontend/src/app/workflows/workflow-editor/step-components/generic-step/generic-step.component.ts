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

import {
  Component,
  EventEmitter,
  Input,
  OnChanges,
  OnInit,
  Output,
  SimpleChanges,
} from '@angular/core';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {Subscription} from 'rxjs';
import {
  ASPECT_RATIO_LABELS,
  MODEL_CONFIGS,
} from '../../../../common/config/model-config';
import {StepConfig, StepInput, StepSetting} from './step.model';
import {
  StepInputValue,
  StepOutputReference,
  StepStatusEnum,
} from '../../../workflow.models';
import {
  DragSourcePort,
  getMaxAllowedInputs,
  getPortTypeColor,
  getShortType,
  isInputAlreadyLinked,
  isInputPortFull,
  isPortTypeCompatible,
  PortShortType,
} from '../../../utils/workflow-magnetic.util';

@Component({
  selector: 'app-generic-step',
  templateUrl: './generic-step.component.html',
  styleUrls: ['./generic-step.component.scss'],
})
export class GenericStepComponent implements OnInit, OnChanges {
  @Input() stepForm!: FormGroup;
  @Input() stepIndex!: number;
  @Input() availableOutputs: any[] = [];
  @Input() mode: 'create' | 'edit' | 'run' = 'create';
  @Input() config!: StepConfig;
  @Input() showValidationErrors = false;
  @Input() stepExecution: any = null;
  @Input() mediaUrlMap!: Map<string, string>;
  @Input() isSelected = false;
  @Input() activeMagneticPort: {stepId: string; inputName: string} | null =
    null;
  @Input() dragSourcePort: DragSourcePort | null = null;

  @Output() delete = new EventEmitter<void>();
  @Output() clone = new EventEmitter<void>();
  @Output() portDragStart = new EventEmitter<{
    stepId: string;
    outputName: string;
    mouseEvent: MouseEvent;
  }>();
  @Output() portDrop = new EventEmitter<{stepId: string; inputName: string}>();

  StepStatusEnum = StepStatusEnum;

  localConfig!: StepConfig;
  private settingsSubscription?: Subscription;
  private inputModeSubscription?: Subscription;
  private modeSubscription?: Subscription;
  private inputsSubscription?: Subscription;
  currentMaxReferenceImages = 1;

  isCollapsed = false;
  inputModes: {[key: string]: 'fixed' | 'linked' | 'mixed'} = {};
  compatibleOutputs: {[key: string]: any[]} = {};

  constructor(private fb: FormBuilder) {}

  getShortType(type: string): PortShortType {
    return getShortType(type);
  }

  getTypeColor(type: string): string {
    return getPortTypeColor(type);
  }

  isMagneticTarget(inputName: string): boolean {
    return (
      this.activeMagneticPort?.stepId === this.stepForm?.value?.stepId &&
      this.activeMagneticPort?.inputName === inputName
    );
  }

  isInputFull(inputName: string, inputType?: string): boolean {
    const model = this.stepForm?.get('settings.model')?.value;
    const currentVal = this.stepForm?.get('inputs')?.get(inputName)?.value;
    return isInputPortFull(currentVal, inputName, model, inputType);
  }

  getMaxMediaItems(input: {name: string; type?: string} | StepInput): number {
    const model = this.stepForm?.get('settings.model')?.value;
    return getMaxAllowedInputs(input.name, model, input.type);
  }

  isCompatibleWithActiveDrag(
    input: {name: string; type: string} | StepInput,
  ): boolean {
    if (!this.dragSourcePort?.type || !this.dragSourcePort?.stepId)
      return false;
    // Block same step self-connection
    if (this.stepForm?.value?.stepId === this.dragSourcePort.stepId) {
      return false;
    }
    // Block duplicate connection if already linked to this source output
    if (this.dragSourcePort.outputName) {
      const currentVal = this.stepForm?.get('inputs')?.get(input.name)?.value;
      if (
        isInputAlreadyLinked(
          currentVal,
          this.dragSourcePort.stepId,
          this.dragSourcePort.outputName,
        )
      ) {
        return false;
      }
    }
    // Block connection if input port is already full
    if (this.isInputFull(input.name, input.type)) {
      return false;
    }
    return isPortTypeCompatible(this.dragSourcePort.type, input.type);
  }

  isIncompatibleWithActiveDrag(
    input: {name: string; type: string} | StepInput,
  ): boolean {
    if (!this.dragSourcePort?.type || !this.dragSourcePort?.stepId)
      return false;
    return !this.isCompatibleWithActiveDrag(input);
  }

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
    if (this.modeSubscription) {
      this.modeSubscription.unsubscribe();
    }
    if (this.inputsSubscription) {
      this.inputsSubscription.unsubscribe();
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
      const isLinked =
        value &&
        typeof value === 'object' &&
        !Array.isArray(value) &&
        'step' in value &&
        'output' in value;

      if (isLinked) {
        this.inputModes[input.name] = 'linked';
      } else if (Array.isArray(value)) {
        this.inputModes[input.name] = 'mixed';
      } else {
        this.inputModes[input.name] = 'fixed';
      }
    });

    if (this.inputsSubscription) {
      this.inputsSubscription.unsubscribe();
    }
    this.inputsSubscription = inputs.valueChanges.subscribe(value => {
      if (!value) return;
      Object.keys(value).forEach(key => {
        const val = value[key];
        const isLinked =
          val &&
          typeof val === 'object' &&
          !Array.isArray(val) &&
          'step' in val &&
          'output' in val;
        if (isLinked && this.inputModes[key] !== 'linked') {
          this.inputModes[key] = 'linked';
        }
      });
    });

    const settings = this.stepForm.get('settings') as FormGroup;
    if (settings) {
      this.config.settings.forEach(setting => {
        if (!settings.contains(setting.name)) {
          let defaultValue = setting.defaultValue;
          if (setting.name === 'mode') {
            const stepType = this.stepForm.get('type')?.value;
            if (stepType === 'edit_image') defaultValue = 'edit_image';
            else if (stepType === 'upscale_image')
              defaultValue = 'upscale_image';
            else if (stepType === 'virtual_try_on')
              defaultValue = 'virtual_try_on';
          }
          settings.addControl(setting.name, this.fb.control(defaultValue));
        }
      });

      // Subscribe to model changes
      if (settings.contains('model')) {
        const modelControl = settings.get('model');
        if (this.settingsSubscription) {
          this.settingsSubscription.unsubscribe();
        }
        this.settingsSubscription = modelControl?.valueChanges.subscribe(
          value => {
            this.updateDynamicConfig(value);
          },
        );

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

      // Subscribe to mode changes (for unified image node)
      if (settings.contains('mode')) {
        const modeControl = settings.get('mode');
        if (this.modeSubscription) {
          this.modeSubscription.unsubscribe();
        }
        this.modeSubscription = modeControl?.valueChanges.subscribe(value => {
          this.updateImageModeConfig(value);
        });

        // Initial update
        this.updateImageModeConfig(modeControl?.value);
      }
    }

    const outputs = this.stepForm.get('outputs') as FormGroup;
    if (outputs) {
      this.localConfig.outputs.forEach(output => {
        if (!outputs.contains(output.name)) {
          outputs.addControl(output.name, this.fb.control({type: output.type}));
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
      const aspectRatioSetting = this.localConfig.settings.find(
        s => s.name === 'aspect_ratio',
      );
      if (aspectRatioSetting) {
        // Generate options dynamically using ASPECT_RATIO_LABELS
        aspectRatioSetting.options = modelMeta.supportedAspectRatios.map(
          ratio => ({
            value: ratio,
            label: ASPECT_RATIO_LABELS[ratio] || ratio,
          }),
        );

        // Reset value if current value is invalid
        const currentAspectRatio = this.stepForm.get(
          'settings.aspect_ratio',
        )?.value;
        if (
          currentAspectRatio &&
          !modelMeta.supportedAspectRatios.includes(currentAspectRatio)
        ) {
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
      const modeSetting = this.localConfig.settings.find(
        s => s.name === 'input_mode',
      );
      if (modeSetting) {
        modeSetting.options = modelMeta.supportedModes.map(mode => ({
          value: mode,
          label: mode,
        }));

        // Default to first mode if current is invalid
        const currentMode = this.stepForm.get('settings.input_mode')?.value;
        if (!currentMode || !modelMeta.supportedModes.includes(currentMode)) {
          // Prefer 'Text to Video' if available, else first
          const defaultMode = modelMeta.supportedModes.includes('Text to Video')
            ? 'Text to Video'
            : modelMeta.supportedModes[0];
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
      if (
        this.localConfig.type === 'generate-video' &&
        (input.name === 'input_images' || input.name === 'reference_images')
      ) {
        const showIngredients = currentMode === 'Ingredients to Video';

        if (showIngredients && maxRefs > 0) {
          input.hidden = false;
          this.stepForm.get('inputs')?.get(input.name)?.enable();
          // Force mixed mode for list inputs if they are enabled
          const short = getShortType(input.type);
          if (short === 'IMG' || short === 'VID') {
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
          const short = getShortType(input.type);
          if (short === 'IMG' || short === 'VID') {
            this.inputModes[input.name] = 'mixed';
          }
        } else {
          input.hidden = true;
          this.stepForm.get('inputs')?.get(input.name)?.disable();
        }
      } else {
        // Default for other inputs: if it allows multiple, set to mixed
        const short = getShortType(input.type);
        if ((short === 'IMG' || short === 'VID') && maxRefs > 1) {
          this.inputModes[input.name] = 'mixed';
        }
      }
    });
  }

  private updateCompatibleOutputs(): void {
    this.localConfig.inputs.forEach(input => {
      this.compatibleOutputs[input.name] = this.availableOutputs.filter(
        output => isPortTypeCompatible(output.type, input.type),
      );
    });
  }

  private updateImageModeConfig(mode: string | null): void {
    if (!mode || this.localConfig.type !== 'image') return;

    // Define visibility and requirement maps per mode
    const inputVisibility: Record<
      string,
      {visible: boolean; required: boolean}
    > = {
      prompt: {
        visible: mode === 'generate_image' || mode === 'edit_image',
        required: mode === 'generate_image' || mode === 'edit_image',
      },
      input_images: {
        visible: mode === 'edit_image',
        required: mode === 'edit_image',
      },
      input_image: {
        visible: mode === 'upscale_image',
        required: mode === 'upscale_image',
      },
      model_image: {
        visible: mode === 'virtual_try_on',
        required: mode === 'virtual_try_on',
      },
      top_image: {
        visible: mode === 'virtual_try_on',
        required: false,
      },
      bottom_image: {
        visible: mode === 'virtual_try_on',
        required: false,
      },
      dress_image: {
        visible: mode === 'virtual_try_on',
        required: false,
      },
      shoes_image: {
        visible: mode === 'virtual_try_on',
        required: false,
      },
    };

    const settingVisibility: Record<string, boolean> = {
      mode: true,
      model: mode === 'generate_image' || mode === 'edit_image',
      aspect_ratio: mode === 'generate_image' || mode === 'edit_image',
      brand_guidelines: mode === 'generate_image' || mode === 'edit_image',
      upscale_factor: mode === 'upscale_image',
      enhance_input_image: mode === 'upscale_image',
      image_preservation_factor: mode === 'upscale_image',
    };

    // Update inputs
    const inputsFormGroup = this.stepForm.get('inputs') as FormGroup;
    this.localConfig.inputs.forEach(input => {
      const config = inputVisibility[input.name];
      if (config) {
        input.hidden = !config.visible;
        input.required = config.required;

        const control = inputsFormGroup?.get(input.name);
        if (control) {
          if (config.visible) {
            control.enable();
            if (config.required) {
              control.setValidators([Validators.required]);
            } else {
              control.clearValidators();
            }
          } else {
            control.disable();
            control.clearValidators();
          }
          control.updateValueAndValidity();
        }
      }
    });

    // Update settings
    this.localConfig.settings.forEach(setting => {
      if (setting.name in settingVisibility) {
        setting.hidden = !settingVisibility[setting.name];
      }
    });

    this.updateCompatibleOutputs();
  }

  toggleInputMode(inputName: string, mode: 'fixed' | 'linked' | 'mixed') {
    this.inputModes[inputName] = mode;
    this.stepForm.get('inputs')?.get(inputName)?.setValue(null);
  }

  getModeSetting(): StepSetting | undefined {
    return this.localConfig?.settings?.find(s => s.name === 'mode');
  }
}
