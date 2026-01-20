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
import { MatDialog } from '@angular/material/dialog';
import { Subscription } from 'rxjs';
import { AssetTypeEnum } from '../../../../admin/source-assets-management/source-asset.model';
import { ImageCropperDialogComponent } from '../../../../common/components/image-cropper-dialog/image-cropper-dialog.component';
import { ImageSelectorComponent, MediaItemSelection } from '../../../../common/components/image-selector/image-selector.component';
import { ASPECT_RATIO_LABELS, MODEL_CONFIGS } from '../../../../common/config/model-config';
import { ReferenceImage } from '../../../../common/models/search.model';
import { SourceAssetResponseDto } from '../../../../common/services/source-asset.service';
import { StepOutputReference } from '../../../workflow.models';
import { StepConfig } from './step.model';

type WorkflowInputItem = ReferenceImage | StepOutputReference;

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
  @Output() delete = new EventEmitter<void>();

  localConfig!: StepConfig;
  private settingsSubscription?: Subscription;
  private inputModeSubscription?: Subscription;
  currentMaxReferenceImages = 1;

  isCollapsed = true;
  inputModes: { [key: string]: 'fixed' | 'linked' | 'mixed' } = {};
  referenceImages: { [key: string]: WorkflowInputItem[] } = {};
  compatibleOutputs: { [key: string]: any[] } = {};

  constructor(
    private fb: FormBuilder,
    public dialog: MatDialog,
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
    this.referenceImages = {};

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
        this.referenceImages[input.name] = value;
      } else {
        this.inputModes[input.name] = 'fixed';
      }

      // Initialize reference images array for this input if it doesn't exist
      if (!this.referenceImages[input.name]) {
        this.referenceImages[input.name] = [];
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

  compareFn(o1: any, o2: any): boolean {
    return o1 && o2 ? o1.step === o2.step && o1.output === o2.output : o1 === o2;
  }

  getStatusClass(status: string): string {
    switch (status) {
      case 'pending':
        return '!bg-gray-500/20 !text-gray-300';
      case 'running':
        return '!bg-blue-500/20 !text-blue-300';
      case 'completed':
        return '!bg-green-500/20 !text-green-300';
      case 'failed':
        return '!bg-red-500/20 !text-red-300';
      case 'skipped':
        return '!bg-amber-500/20 !text-amber-300';
      default:
        return '!bg-gray-500/20 !text-gray-300';
    }
  }

  getStatusIcon(status: string): string {
    switch (status) {
      case 'running':
        return 'hourglass_top';
      case 'completed':
        return 'check_circle';
      case 'failed':
        return 'error';
      default:
        return '';
    }
  }

  openImageSelectorForReference(inputName: string, type: 'image' | 'video'): void {
    const maxItems = type === 'image' ? this.currentMaxReferenceImages : 1;
    if ((this.referenceImages[inputName]?.length || 0) >= maxItems) return;

    let mimeType: string = 'image/*';
    if (type === 'video') mimeType = 'video/mp4';

    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: mimeType,
        assetType: type === 'video' ? AssetTypeEnum.GENERIC_VIDEO : AssetTypeEnum.GENERIC_IMAGE,
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef
      .afterClosed()
      .subscribe((result: MediaItemSelection | SourceAssetResponseDto) => {
        if (result && (this.referenceImages[inputName]?.length || 0) < this.currentMaxReferenceImages) {
          if (!this.referenceImages[inputName]) this.referenceImages[inputName] = [];

          let newImage: ReferenceImage | null = null;

          if ('gcsUri' in result) {
            newImage = {
              sourceAssetId: result.id,
              previewUrl: result.presignedUrl || '',
            };
          } else {
            const previewUrl =
              result.mediaItem.presignedUrls?.[result.selectedIndex];
            if (previewUrl) {
              newImage = {
                previewUrl: previewUrl,
                sourceMediaItem: {
                  mediaItemId: result.mediaItem.id,
                  mediaIndex: result.selectedIndex,
                  role: 'image_reference_asset', // Role is now set dynamically in searchTerm
                },
              };
            }
          }

          if (newImage) {
            this.referenceImages[inputName].push(newImage);
            this.updateInputControlWithError(inputName);
          }
        }
      });
  }

  // Called when DROPPING a file on the new drop zone
  onReferenceImageDrop(event: DragEvent, inputName: string) {
    event.preventDefault();
    if ((this.referenceImages[inputName]?.length || 0) >= this.currentMaxReferenceImages) return;
    const file = event.dataTransfer?.files[0];
    if (file && file.type.startsWith('image/')) {
      // For a direct drop, go straight to the cropper
      const dialogRef = this.dialog.open(ImageCropperDialogComponent, {
        data: {
          imageFile: file,
          assetType: AssetTypeEnum.GENERIC_IMAGE,
        },
        width: '600px',
      });

      dialogRef.afterClosed().subscribe((result: SourceAssetResponseDto) => {
        if (result && result.id) {
          if (!this.referenceImages[inputName]) this.referenceImages[inputName] = [];
          this.referenceImages[inputName].push({
            sourceAssetId: result.id,
            previewUrl: result.presignedUrl || '',
          });
          this.updateInputControlWithError(inputName);
        }
      });
    }
  }


  clearReferenceImage(inputName: string, index: number) {
    if (this.referenceImages[inputName]) {
      this.referenceImages[inputName].splice(index, 1);
      this.updateInputControlWithError(inputName);
    }
  }

  addLinkedOutput(inputName: string, outputValue: any) {
    if ((this.referenceImages[inputName]?.length || 0) >= this.currentMaxReferenceImages) return;
    if (!this.referenceImages[inputName]) this.referenceImages[inputName] = [];

    this.referenceImages[inputName].push(outputValue.value); // outputValue.value is the StepOutputReference
    this.updateInputControlWithError(inputName);
  }

  isStepOutputReference(item: any): item is StepOutputReference {
    return item && 'step' in item && 'output' in item;
  }

  getLinkedOutputLabel(item: StepOutputReference): string {
    // Find label from availableOutputs
    // This is expensive O(N) but N is small
    for (const key in this.compatibleOutputs) {
      const found = this.compatibleOutputs[key].find(o => o.value.step === item.step && o.value.output === item.output);
      if (found) return found.label;
    }
    return `${item.step}.${item.output}`;
  }


  private updateInputControlWithError(inputName: string) {
    const images = this.referenceImages[inputName] || [];
    const control = this.stepForm.get('inputs')?.get(inputName);
    if (control) {
      // Create a shallow copy to ensure Angular detects the change
      control.setValue(images.length > 0 ? [...images] : null);
      control.markAsDirty();
      control.updateValueAndValidity();
    }
  }
}
