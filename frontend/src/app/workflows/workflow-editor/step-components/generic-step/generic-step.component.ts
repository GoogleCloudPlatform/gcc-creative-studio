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
  OnDestroy,
  OnInit,
  Output,
  SimpleChanges,
  computed,
  inject,
  signal,
} from '@angular/core';
import {FormBuilder, FormGroup, ValidatorFn, Validators} from '@angular/forms';
import {MatDialog} from '@angular/material/dialog';
import {MatSelectChange} from '@angular/material/select';
import {Subscription, take} from 'rxjs';
import {AssetTypeEnum} from '../../../../admin/source-assets-management/source-asset.model';
import {
  ImageSelectorComponent,
  ImageSelectorDialogData,
} from '../../../../common/components/image-selector/image-selector.component';
import {
  ASPECT_RATIO_AUTO,
  ASPECT_RATIO_LABELS,
  ASPECT_RATIO_SQUARE,
  MODEL_CONFIGS,
  isGeminiOmniModel,
} from '../../../../common/config/model-config';
import {
  FolderSelectionResult,
  FolderTreeNode,
} from '../../../../common/models/folder.model';
import {FolderService} from '../../../../common/services/folder.service';
import {WorkspaceStateService} from '../../../../services/workspace/workspace-state.service';
import {StepConfig, StepInput, StepOutput, StepSetting} from './step.model';
import {
  DynamicStepRecord,
  NodeTypes,
  StepEntry,
  StepOutputReference,
  StepStatusEnum,
} from '../../../workflow.models';
import {isStepOutputReference} from '../../../utils/workflow-step.util';
import {
  getLatestStepInputs,
  getLatestStepOutputs,
} from '../../../utils/step-history.util';
import {
  LOOP_CURRENT_ITEM_PORT,
  LOOP_ENDING_PORT,
  LOOP_FOLDER_CHOOSE_VALUE,
  LOOP_FOLDER_MISSING_TOOLTIP,
  LOOP_FOLDER_SETTING,
  LOOP_ITEMS_TEXT_INPUT,
  LOOP_ITEM_TYPE_MIME_MAP,
  LOOP_ITEM_TYPE_SETTING,
  LOOP_LINKED_ITEMS_INPUT,
  LOOP_MODE_FOLDER,
  LOOP_MODE_LINKED_ITEMS,
  LOOP_MODE_SETTING,
  LOOP_MODE_TEXT_INPUT,
  LoopFolderChooseValue,
  MAX_LOOP_ITEMS,
  getLoopCurrentItemType,
  getLoopLinkedItemsInputType,
  loopFolderIdValidator,
  loopItemsTextValidator,
  loopLinkedItemsRequiredValidator,
  toLoopFolderId,
  toLoopItemType,
  toLoopMode,
} from '../step-configs/loop-step.config';
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

/** Name and full path of a Media Gallery folder, indexed by folder id. */
interface LoopFolderEntry {
  name: string;
  path: string;
}

/** View model of the current-folder option in the Loop folder select. */
interface LoopFolderOptionView {
  value: number | null;
  label: string;
  /** Full folder path; empty when unknown. */
  path: string;
  isPlaceholder: boolean;
  isMissing: boolean;
}

const FOLDER_PATH_SEPARATOR = ' / ';
const LOOP_FOLDER_PLACEHOLDER_LABEL = 'No folder selected';

@Component({
  selector: 'app-generic-step',
  templateUrl: './generic-step.component.html',
  styleUrls: ['./generic-step.component.scss'],
})
export class GenericStepComponent implements OnInit, OnChanges, OnDestroy {
  @Input() stepForm!: FormGroup;
  @Input() stepIndex!: number;
  @Input() availableOutputs: any[] = [];
  @Input() mode: 'create' | 'edit' | 'run' = 'create';
  @Input() config!: StepConfig;
  @Input() showValidationErrors = false;
  @Input() mediaUrlMap!: Map<string, string>;
  @Input() isSelected = false;
  @Input() isHighlighted = false;
  @Input() activeMagneticPort: {stepId: string; inputName: string} | null =
    null;
  @Input() dragSourcePort: DragSourcePort | null = null;

  private readonly stepExecutionState = signal<StepEntry | null>(null);
  private readonly outputLinkedState = signal<boolean>(false);
  private readonly loopEndingOutputVisibleState = signal<boolean>(false);
  /** Output definitions of {@link localConfig}, mirrored for reactivity. */
  private readonly configOutputs = signal<StepOutput[]>([]);

  /** Execution entry for this step in the selected run (history-based). */
  @Input() set stepExecution(value: StepEntry | null) {
    this.stepExecutionState.set(value ?? null);
  }
  get stepExecution(): StepEntry | null {
    return this.stepExecutionState();
  }

  /**
   * True when ANY output port of this step (incl. `loop_ending` and Loop
   * `current_item`) is wired to another step. Linked steps hide output previews.
   */
  @Input() set isOutputLinked(value: boolean) {
    this.outputLinkedState.set(!!value);
  }
  get isOutputLinked(): boolean {
    return this.outputLinkedState();
  }

  /**
   * True when the `loop_ending` output port must be rendered: the step is
   * inside a Loop body or its `loop_ending` output is already wired.
   */
  @Input() set showLoopEndingOutput(value: boolean) {
    this.loopEndingOutputVisibleState.set(!!value);
  }
  get showLoopEndingOutput(): boolean {
    return this.loopEndingOutputVisibleState();
  }

  /** Output ports rendered on the card (`loop_ending` only when visible). */
  readonly visibleOutputs = computed<StepOutput[]>(() => {
    const outputs = this.configOutputs();
    if (this.loopEndingOutputVisibleState()) return outputs;
    return outputs.filter(output => output.name !== LOOP_ENDING_PORT);
  });

  @Output() delete = new EventEmitter<void>();
  @Output() clone = new EventEmitter<void>();
  @Output() collapseChange = new EventEmitter<boolean>();
  @Output() portDragStart = new EventEmitter<{
    stepId: string;
    outputName: string;
    mouseEvent: MouseEvent;
  }>();
  @Output() portDrop = new EventEmitter<{stepId: string; inputName: string}>();

  StepStatusEnum = StepStatusEnum;
  NodeTypes = NodeTypes;
  readonly maxLoopItems = MAX_LOOP_ITEMS;

  /** Outputs of the latest (last) history entry, bound to the card preview. */
  readonly latestStepOutputs = computed<DynamicStepRecord>(() =>
    getLatestStepOutputs(this.stepExecutionState()),
  );

  /**
   * Inputs of the latest history entry. Not rendered on the card, but needed
   * so Loop folder-mode items preview as media of the run's `item_type`.
   */
  readonly latestStepInputs = computed<DynamicStepRecord>(() =>
    getLatestStepInputs(this.stepExecutionState()),
  );

  /** Error reported by the run for this step (always surfaced on the card). */
  readonly stepExecutionError = computed(() => {
    const exec = this.stepExecutionState();
    return exec?.last_error ?? exec?.error ?? null;
  });

  /** Output preview is only shown for unlinked (terminal) steps. */
  readonly showOutputPreview = computed(() => !this.outputLinkedState());

  /**
   * Render the Results section for unlinked (terminal) steps, or for linked
   * steps only when an error banner must be surfaced.
   */
  readonly showExecutionResults = computed(() => {
    const exec = this.stepExecutionState();
    if (!exec) return false;
    if (this.stepExecutionError()) return true;
    if (!this.showOutputPreview()) return false;
    const hasOutputs = Object.keys(this.latestStepOutputs()).length > 0;
    return hasOutputs || (exec.attempts ?? 0) > 0;
  });

  localConfig!: StepConfig;
  isLoopStep = false;
  readonly loopFolderSettingName = LOOP_FOLDER_SETTING;
  readonly loopLinkedItemsInputName = LOOP_LINKED_ITEMS_INPUT;
  readonly loopFolderChooseValue: LoopFolderChooseValue =
    LOOP_FOLDER_CHOOSE_VALUE;
  readonly loopFolderMissingTooltip = LOOP_FOLDER_MISSING_TOOLTIP;

  /** Folder id → name/path of the workspace tree; null while loading or on error. */
  readonly loopFolderIndex = signal<ReadonlyMap<
    number,
    LoopFolderEntry
  > | null>(null);
  /** Saved Loop folder id (never the "Choose folder…" value). */
  readonly loopFolderId = signal<number | null>(null);
  /** Current-folder option of the Loop folder select. */
  readonly loopFolderOption = computed<LoopFolderOptionView>(() => {
    const id = this.loopFolderId();
    if (id === null) {
      return {
        value: null,
        label: LOOP_FOLDER_PLACEHOLDER_LABEL,
        path: '',
        isPlaceholder: true,
        isMissing: false,
      };
    }
    const index = this.loopFolderIndex();
    const entry = index?.get(id) ?? null;
    if (entry) {
      return {
        value: id,
        label: entry.name,
        path: entry.path,
        isPlaceholder: false,
        isMissing: false,
      };
    }
    return {
      value: id,
      label: `Folder #${id}`,
      path: '',
      isPlaceholder: false,
      isMissing: index !== null,
    };
  });
  /**
   * Current-folder option as a list tracked by value: a new value re-creates
   * the mat-option, which makes MatSelect re-match the control value (it does
   * not re-sync when an existing option's value binding changes).
   */
  readonly loopFolderOptions = computed<ReadonlyArray<LoopFolderOptionView>>(
    () => [this.loopFolderOption()],
  );
  readonly trackLoopFolderOption = (
    _index: number,
    option: LoopFolderOptionView,
  ): number | null => option.value;
  private loopFolderWasPristine = true;

  private readonly fb = inject(FormBuilder);
  private readonly folderService = inject(FolderService);
  private readonly workspaceStateService = inject(WorkspaceStateService);
  private readonly dialog = inject(MatDialog);
  private settingsSubscription?: Subscription;
  private inputModeSubscription?: Subscription;
  private modeSubscription?: Subscription;
  private inputsSubscription?: Subscription;
  private collapsedSubscription?: Subscription;
  private loopItemTypeSubscription?: Subscription;
  private loopFolderSubscription?: Subscription;
  private foldersSubscription?: Subscription;
  currentMaxReferenceImages = 1;

  isCollapsed = false;
  inputModes: {[key: string]: 'fixed' | 'linked' | 'mixed'} = {};
  compatibleOutputs: {[key: string]: any[]} = {};
  newVariableName = '';

  toggleCollapse(event?: Event): void {
    if (event) {
      event.stopPropagation();
    }
    this.isCollapsed = !this.isCollapsed;
    const collapsedControl = this.stepForm.get('collapsed');
    if (collapsedControl) {
      collapsedControl.setValue(this.isCollapsed);
      collapsedControl.markAsDirty();
    }
    this.stepForm.markAsDirty();
    this.collapseChange.emit(this.isCollapsed);
  }

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

  private isPromptLinkedVariable(inputName: string): boolean {
    return (
      this.localConfig?.type === NodeTypes.GENERATE_TEXT &&
      !this.isBasePortCollision(inputName) &&
      this.inputModes['prompt'] !== 'fixed'
    );
  }

  isInputDisabled(inputName: string): boolean {
    if (this.isPromptLinkedVariable(inputName)) {
      return true;
    }
    return !!this.stepForm?.get('inputs')?.get(inputName)?.disabled;
  }

  isCompatibleWithActiveDrag(
    input: {name: string; type: string} | StepInput,
  ): boolean {
    if (!this.dragSourcePort?.type || !this.dragSourcePort?.stepId)
      return false;
    // Block connection if input port is disabled
    if (this.isInputDisabled(input.name)) {
      return false;
    }
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
    if (this.isInputDisabled(input.name)) {
      return true;
    }
    return !this.isCompatibleWithActiveDrag(input);
  }

  getInputDisabledMessage(inputName: string): string {
    if (this.isPromptLinkedVariable(inputName)) {
      return 'Prompt is linked - variables inactive';
    }
    if (this.localConfig?.type === NodeTypes.GENERATE_VIDEO) {
      const currentModel = this.stepForm?.get('settings.model')?.value;
      if (!isGeminiOmniModel(currentModel)) {
        if (inputName === 'input_audio') {
          return 'This model does not support Audio as reference';
        }
        if (inputName === 'input_video') {
          return 'This model does not support Video as reference';
        }
      }
    }
    return '';
  }

  onInputPortMouseUp(event: MouseEvent, inputName: string): void {
    event.stopPropagation();
    if (this.isInputDisabled(inputName)) {
      return;
    }
    this.portDrop.emit({
      stepId: this.stepForm?.value?.stepId,
      inputName: inputName,
    });
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
    if (this.collapsedSubscription) {
      this.collapsedSubscription.unsubscribe();
    }
    this.loopItemTypeSubscription?.unsubscribe();
    this.loopFolderSubscription?.unsubscribe();
    this.foldersSubscription?.unsubscribe();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['stepForm'] || changes['config']) {
      this.initializeStepState();
    }
    if (changes['availableOutputs']) {
      this.updateCompatibleOutputs();
    }
  }

  private initializeStepState(): void {
    if (!this.stepForm) return;

    this.isCollapsed = !!this.stepForm.get('collapsed')?.value;
    if (this.collapsedSubscription) {
      this.collapsedSubscription.unsubscribe();
    }
    this.collapsedSubscription = this.stepForm
      .get('collapsed')
      ?.valueChanges.subscribe(value => {
        this.isCollapsed = !!value;
      });

    // Deep copy config to localConfig to allow per-instance modifications
    this.localConfig = JSON.parse(JSON.stringify(this.config));
    this.configOutputs.set(this.localConfig.outputs ?? []);
    this.isLoopStep = this.localConfig.type === NodeTypes.LOOP;

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
      const isLinked = isStepOutputReference(value);

      if (isLinked || input.linkedOnly) {
        this.inputModes[input.name] = 'linked';
      } else if (Array.isArray(value)) {
        this.inputModes[input.name] = 'mixed';
      } else {
        this.inputModes[input.name] = 'fixed';
      }
    });

    if (this.localConfig.type === NodeTypes.GENERATE_TEXT) {
      const baseInputNames = new Set(
        this.getBaseInputs().map(i => i.name.toLowerCase()),
      );
      Object.keys(inputs.controls).forEach(controlName => {
        if (!baseInputNames.has(controlName.toLowerCase())) {
          const exists = this.localConfig.inputs.some(
            i => i.name.toLowerCase() === controlName.toLowerCase(),
          );
          if (!exists) {
            this.localConfig.inputs.push({
              name: controlName,
              label: controlName,
              type: 'text',
              required: false,
              isVariable: true,
            });
          }
          if (!this.inputModes[controlName]) {
            this.initializeInputMode(controlName, inputs);
          }
        }
      });
      const promptVal = inputs.get('prompt')?.value;
      this.updatePromptVariables(promptVal);
    }

    if (this.inputsSubscription) {
      this.inputsSubscription.unsubscribe();
    }
    this.inputsSubscription = inputs.valueChanges.subscribe(value => {
      if (!value) return;
      Object.keys(value).forEach(key => {
        const val = value[key];
        const isLinked = isStepOutputReference(val);
        if (isLinked && this.inputModes[key] !== 'linked') {
          this.inputModes[key] = 'linked';
        }
      });
    });

    const settings = this.stepForm.get('settings') as FormGroup;
    if (settings) {
      this.localConfig.settings.forEach(setting => {
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
          this.updateLoopModeConfig();
        });

        // Initial update
        this.updateImageModeConfig(modeControl?.value);
      }

      if (this.isLoopStep) {
        this.initializeLoopStep(settings);
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
        const isImageStep = this.localConfig.type === 'image';
        const currentMode = this.stepForm.get('settings.mode')?.value;
        const isEditImage = currentMode === 'edit_image';

        // Generate options dynamically using ASPECT_RATIO_LABELS
        aspectRatioSetting.options = modelMeta.supportedAspectRatios.map(
          ratio => ({
            value: ratio,
            label: ASPECT_RATIO_LABELS[ratio] || ratio,
            disabled:
              isImageStep && ratio === ASPECT_RATIO_AUTO && !isEditImage,
          }),
        );

        // Reset value if current value is invalid or disabled
        const currentAspectRatio = this.stepForm.get(
          'settings.aspect_ratio',
        )?.value;
        const currentOption = aspectRatioSetting.options.find(
          o => o.value === currentAspectRatio,
        );
        if (
          !currentOption ||
          currentOption.disabled ||
          !modelMeta.supportedAspectRatios.includes(currentAspectRatio)
        ) {
          // Set to 1:1 if available and not disabled, else first available enabled option
          const fallbackOption =
            aspectRatioSetting.options.find(o => !o.disabled)?.value ||
            ASPECT_RATIO_SQUARE;
          if (fallbackOption) {
            this.stepForm
              .get('settings.aspect_ratio')
              ?.setValue(fallbackOption);
          }
        }
      }
    }

    // Update Resolution options
    if (modelMeta.supportedResolutions) {
      const resolutionSetting = this.localConfig.settings.find(
        s => s.name === 'resolution',
      );
      if (resolutionSetting) {
        if (modelMeta.supportedResolutions.length > 0) {
          resolutionSetting.options = modelMeta.supportedResolutions.map(
            res => ({
              value: res,
              label: res,
            }),
          );

          // Reset value if current value is invalid
          const currentResolution = this.stepForm.get(
            'settings.resolution',
          )?.value;
          if (
            currentResolution &&
            !modelMeta.supportedResolutions.includes(currentResolution)
          ) {
            const firstOption = resolutionSetting.options?.[0]?.value;
            if (firstOption) {
              this.stepForm.get('settings.resolution')?.setValue(firstOption);
            }
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

    // 3. Update Duration options
    const durationSetting = this.localConfig.settings.find(
      s => s.name === 'duration_seconds',
    );
    if (durationSetting) {
      if (
        modelMeta.supportedDurations &&
        modelMeta.supportedDurations.length > 0
      ) {
        durationSetting.hidden = false;
        durationSetting.options = modelMeta.supportedDurations.map(
          duration => ({
            value: duration,
            label: `${duration}s`,
          }),
        );

        // Reset value if current value is invalid
        const currentDuration = this.stepForm.get(
          'settings.duration_seconds',
        )?.value;
        if (
          currentDuration &&
          !modelMeta.supportedDurations.includes(Number(currentDuration))
        ) {
          const firstOption = durationSetting.options?.[0]?.value;
          if (firstOption !== undefined) {
            this.stepForm
              .get('settings.duration_seconds')
              ?.setValue(firstOption);
          }
        }
      } else {
        durationSetting.hidden = true;
      }
    }

    // 4. Update Audio Settings Visibility
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
    const currentModel = this.stepForm.get('settings.model')?.value;
    const maxRefs = this.currentMaxReferenceImages;

    this.localConfig.inputs.forEach(input => {
      // Logic for specific inputs
      if (
        this.localConfig.type === NodeTypes.GENERATE_VIDEO &&
        (input.name === 'input_images' ||
          input.name === 'reference_images' ||
          input.name === 'input_video' ||
          input.name === 'input_audio')
      ) {
        const showIngredients = currentMode === 'Ingredients to Video';
        const isImageRef =
          input.name === 'input_images' || input.name === 'reference_images';
        const isAudioRef = input.name === 'input_audio';
        const isVideoRef = input.name === 'input_video';
        const isVisible = isImageRef
          ? showIngredients && maxRefs > 0
          : showIngredients;

        if (isVisible) {
          input.hidden = false;
          if ((isAudioRef || isVideoRef) && !isGeminiOmniModel(currentModel)) {
            this.stepForm.get('inputs')?.get(input.name)?.disable();
          } else {
            this.stepForm.get('inputs')?.get(input.name)?.enable();
            // Force mixed mode for list inputs if they are enabled
            const short = getShortType(input.type);
            if (short === 'IMG' || short === 'VID' || short === 'AUD') {
              this.inputModes[input.name] = 'mixed';
            }
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
          if (short === 'IMG' || short === 'VID' || short === 'AUD') {
            this.inputModes[input.name] = 'mixed';
          }
        } else {
          input.hidden = true;
          this.stepForm.get('inputs')?.get(input.name)?.disable();
        }
      } else {
        // Default for other inputs: if it allows multiple, set to mixed
        const short = getShortType(input.type);
        if (
          (short === 'IMG' || short === 'VID' || short === 'AUD') &&
          maxRefs > 1
        ) {
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
      resolution: mode === 'generate_image' || mode === 'edit_image',
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

    // Update aspect ratio 'auto' option enabled state based on mode
    if (this.localConfig?.type === 'image') {
      const aspectRatioSetting = this.localConfig.settings.find(
        s => s.name === 'aspect_ratio',
      );
      const isEditImage = mode === 'edit_image';
      if (aspectRatioSetting?.options) {
        aspectRatioSetting.options.forEach(opt => {
          if (opt.value === ASPECT_RATIO_AUTO) {
            opt.disabled = !isEditImage;
          }
        });

        // If aspect_ratio was set to 'auto' but current mode is not 'edit_image', reset to '1:1'
        const currentAspectRatio = this.stepForm.get(
          'settings.aspect_ratio',
        )?.value;
        const isCurrentDisabled =
          aspectRatioSetting.options.find(o => o.value === currentAspectRatio)
            ?.disabled === true;
        if (isCurrentDisabled) {
          const fallbackOption =
            aspectRatioSetting.options.find(o => !o.disabled)?.value ||
            ASPECT_RATIO_SQUARE;
          this.stepForm.get('settings.aspect_ratio')?.setValue(fallbackOption);
        }
      }
    }

    this.updateCompatibleOutputs();
  }

  private initializeLoopStep(settings: FormGroup): void {
    const folderControl = settings.get(LOOP_FOLDER_SETTING);
    this.loopFolderId.set(toLoopFolderId(folderControl?.value));
    // Follows external updates (history undo/redo, workflow load, reset). The
    // transient "Choose folder…" value is ignored so the revert target is kept.
    this.loopFolderSubscription?.unsubscribe();
    this.loopFolderSubscription = folderControl?.valueChanges.subscribe(
      value => {
        if (value === LOOP_FOLDER_CHOOSE_VALUE) return;
        this.loopFolderId.set(toLoopFolderId(value));
      },
    );
    this.loopItemTypeSubscription?.unsubscribe();
    this.loopItemTypeSubscription = settings
      .get(LOOP_ITEM_TYPE_SETTING)
      ?.valueChanges.subscribe(() => this.updateLoopModeConfig());
    this.updateLoopModeConfig();
    this.loadLoopFolders();
  }

  /**
   * Toggles Loop settings/inputs for the active source mode and keeps the
   * dynamic port types in sync: `current_item` (`text` or `item_type`) and the
   * `linked_items` input (`item_type`).
   */
  private updateLoopModeConfig(): void {
    if (!this.isLoopStep) return;
    // getRawValue() reads child controls directly: a child control's
    // valueChanges fires before the parent group's `value` is refreshed.
    const settingsGroup = this.stepForm.get('settings') as FormGroup | null;
    const settingsValue: DynamicStepRecord = settingsGroup?.getRawValue() ?? {};
    const mode = toLoopMode(settingsValue[LOOP_MODE_SETTING]);
    const isTextMode = mode === LOOP_MODE_TEXT_INPUT;
    const isFolderMode = mode === LOOP_MODE_FOLDER;
    const isLinkedMode = mode === LOOP_MODE_LINKED_ITEMS;

    this.localConfig.settings.forEach(setting => {
      if (setting.name === LOOP_FOLDER_SETTING) {
        setting.hidden = !isFolderMode;
      } else if (setting.name === LOOP_ITEM_TYPE_SETTING) {
        setting.hidden = isTextMode;
      }
    });

    // A folder is only required when looping over a Media Gallery folder.
    const folderControl = settingsGroup?.get(LOOP_FOLDER_SETTING);
    if (folderControl) {
      if (isFolderMode) {
        folderControl.setValidators([
          Validators.required,
          loopFolderIdValidator,
        ]);
      } else {
        folderControl.clearValidators();
      }
      folderControl.updateValueAndValidity({emitEvent: false});
    }

    this.applyLoopSourceInput(LOOP_ITEMS_TEXT_INPUT, isTextMode, [
      Validators.required,
      loopItemsTextValidator,
    ]);
    this.applyLoopSourceInput(LOOP_LINKED_ITEMS_INPUT, isLinkedMode, [
      loopLinkedItemsRequiredValidator,
    ]);

    const linkedItemsInput = this.localConfig.inputs.find(
      i => i.name === LOOP_LINKED_ITEMS_INPUT,
    );
    if (linkedItemsInput) {
      linkedItemsInput.type = getLoopLinkedItemsInputType(settingsValue);
    }

    const currentItemType = getLoopCurrentItemType(settingsValue);
    const currentItemOutput = this.localConfig.outputs.find(
      o => o.name === LOOP_CURRENT_ITEM_PORT,
    );
    if (currentItemOutput) {
      currentItemOutput.type = currentItemType;
    }
    this.stepForm
      .get('outputs')
      ?.get(LOOP_CURRENT_ITEM_PORT)
      ?.setValue({type: currentItemType}, {emitEvent: false});

    this.updateCompatibleOutputs();
  }

  /**
   * Shows, requires, validates and enables a Loop source input only while its
   * mode is active; otherwise hides, clears and disables it. Disabled controls
   * are also skipped as magnetic wiring candidates.
   */
  private applyLoopSourceInput(
    inputName: string,
    isActive: boolean,
    validators: ValidatorFn[],
  ): void {
    const input = this.localConfig.inputs.find(i => i.name === inputName);
    if (input) {
      input.hidden = !isActive;
      input.required = isActive;
    }
    const control = this.stepForm.get('inputs')?.get(inputName);
    if (!control) return;
    if (isActive) {
      control.setValidators(validators);
      if (!this.stepForm.disabled) {
        control.enable({emitEvent: false});
      }
    } else {
      control.clearValidators();
      control.disable({emitEvent: false});
    }
    control.updateValueAndValidity({emitEvent: false});
  }

  /** Indexes the active workspace's folders to resolve the saved folder name/path. */
  private loadLoopFolders(): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId === null) return;
    this.loopFolderIndex.set(null);
    this.foldersSubscription?.unsubscribe();
    this.foldersSubscription = this.folderService
      .getFolderTree(workspaceId)
      .subscribe({
        next: tree => {
          this.loopFolderIndex.set(new Map(this.flattenFolderTree(tree ?? [])));
        },
        error: err => {
          console.error('Failed to load Media Gallery folders', err);
        },
      });
  }

  private flattenFolderTree(
    nodes: FolderTreeNode[],
    parentPath = '',
  ): Array<[number, LoopFolderEntry]> {
    return nodes.flatMap(node => {
      const path = parentPath
        ? `${parentPath}${FOLDER_PATH_SEPARATOR}${node.name}`
        : node.name;
      const entry: [number, LoopFolderEntry] = [
        node.id,
        {name: node.name, path},
      ];
      return [entry, ...this.flattenFolderTree(node.children ?? [], path)];
    });
  }

  /** Remembers whether the folder control was pristine before the user picks an option. */
  onLoopFolderOpenedChange(opened: boolean): void {
    if (!opened) return;
    const control = this.stepForm.get('settings')?.get(LOOP_FOLDER_SETTING);
    this.loopFolderWasPristine = control?.pristine ?? true;
  }

  /**
   * "Choose folder…" is an action, not a value: the control is reverted
   * synchronously (so it is never saved) and the folder selector is opened.
   */
  onLoopFolderSelectionChange(event: MatSelectChange): void {
    if (event.value !== LOOP_FOLDER_CHOOSE_VALUE) return;
    const control = this.stepForm.get('settings')?.get(LOOP_FOLDER_SETTING);
    if (!control) return;
    control.setValue(this.loopFolderId());
    if (this.loopFolderWasPristine) {
      control.markAsPristine();
    }
    this.openLoopFolderSelector();
  }

  /** Opens the Media Gallery in folder mode and stores the confirmed folder. */
  openLoopFolderSelector(): void {
    const control = this.stepForm.get('settings')?.get(LOOP_FOLDER_SETTING);
    if (!control || control.disabled) return;
    const itemType = toLoopItemType(
      this.stepForm.get('settings')?.get(LOOP_ITEM_TYPE_SETTING)?.value,
    );
    const data: ImageSelectorDialogData = {
      selectionTarget: 'folder',
      initialFolderId: this.loopFolderId(),
      mimeType: LOOP_ITEM_TYPE_MIME_MAP[itemType],
      assetType: AssetTypeEnum.GENERIC_IMAGE,
    };
    this.dialog
      .open<
        ImageSelectorComponent,
        ImageSelectorDialogData,
        FolderSelectionResult | null
      >(ImageSelectorComponent, {
        width: '90vw',
        height: '80vh',
        maxWidth: '90vw',
        panelClass: 'image-selector-dialog',
        data,
      })
      .afterClosed()
      .pipe(take(1))
      .subscribe(result => {
        const folderId = toLoopFolderId(result?.folderId);
        if (!result || folderId === null) return;
        const index = new Map(this.loopFolderIndex() ?? []);
        index.set(folderId, {name: result.folderName, path: result.path});
        this.loopFolderIndex.set(index);
        this.loopFolderId.set(folderId);
        control.setValue(folderId);
        control.markAsDirty();
        control.markAsTouched();
      });
  }

  getBaseInputs(): StepInput[] {
    return (this.localConfig?.inputs ?? []).filter(i => !i.isVariable);
  }

  getVariableInputs(): StepInput[] {
    return (this.localConfig?.inputs ?? []).filter(i => !!i.isVariable);
  }

  isBasePortCollision(varName: string): boolean {
    return this.getBaseInputs().some(
      i => i.name.toLowerCase() === varName.toLowerCase(),
    );
  }

  isVariableUsedInPrompt(varName: string): boolean {
    const promptVal = this.stepForm?.get('inputs.prompt')?.value;
    if (typeof promptVal !== 'string') return false;
    const matches = promptVal.matchAll(/<([a-zA-Z0-9_]+)>/g);
    const targetLower = varName.toLowerCase();
    for (const match of matches) {
      if (match[1].toLowerCase() === targetLower) {
        return true;
      }
    }
    return false;
  }

  appendToPrompt(varName: string): void {
    const promptControl = this.stepForm?.get('inputs.prompt');
    if (!promptControl) return;

    const currentVal = (promptControl.value || '').toString().trim();
    const placeholder = `<${varName}>`;
    const newVal = currentVal ? `${currentVal} ${placeholder}` : placeholder;

    promptControl.setValue(newVal);
    promptControl.markAsDirty();
    this.updatePromptVariables(newVal);
  }

  isValidNewVariableName(): boolean {
    const name = this.newVariableName?.trim();
    if (!name) return false;
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name)) return false;
    if (this.isBasePortCollision(name)) return false;
    if (
      this.localConfig?.inputs?.some(
        i => i.name.toLowerCase() === name.toLowerCase(),
      )
    ) {
      return false;
    }
    return true;
  }

  addCustomVariable(): void {
    const name = this.newVariableName?.trim();
    if (!name || !this.isValidNewVariableName()) return;
    this.addVariable(name);
    this.newVariableName = '';
  }

  addVariable(name?: string): void {
    if (this.localConfig?.type !== NodeTypes.GENERATE_TEXT) return;
    const inputs = this.stepForm?.get('inputs') as FormGroup;
    if (!inputs) return;

    const varName = name?.trim();
    if (
      !varName ||
      !/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(varName) ||
      this.isBasePortCollision(varName)
    ) {
      return;
    }
    if (
      this.localConfig.inputs.some(
        i => i.name.toLowerCase() === varName.toLowerCase(),
      )
    ) {
      return;
    }

    const newInput: StepInput = {
      name: varName,
      label: varName,
      type: 'text',
      required: false,
      isVariable: true,
    };

    this.localConfig.inputs = [...this.localConfig.inputs, newInput];
    if (!inputs.contains(varName)) {
      inputs.addControl(varName, this.fb.control(null));
    }
    this.inputModes[varName] = 'fixed';
    this.updateCompatibleOutputs();
  }

  removeVariable(varName: string): void {
    if (this.isBasePortCollision(varName)) return;
    const inputs = this.stepForm?.get('inputs') as FormGroup;
    const targetVar = this.localConfig.inputs.find(
      i => i.name.toLowerCase() === varName.toLowerCase(),
    );
    const actualName = targetVar ? targetVar.name : varName;
    this.localConfig.inputs = this.localConfig.inputs.filter(
      i => i.name.toLowerCase() !== varName.toLowerCase(),
    );
    if (inputs?.contains(actualName)) {
      inputs.removeControl(actualName);
    }
    delete this.inputModes[actualName];
    delete this.compatibleOutputs[actualName];
    this.updateCompatibleOutputs();
  }

  toggleInputMode(inputName: string, mode: 'fixed' | 'linked' | 'mixed') {
    this.inputModes[inputName] = mode;
    this.stepForm.get('inputs')?.get(inputName)?.setValue(null);
  }

  getModeSetting(): StepSetting | undefined {
    return this.localConfig?.settings?.find(s => s.name === 'mode');
  }

  onInputFieldBlur(inputName: string): void {
    if (
      inputName === 'prompt' &&
      this.localConfig.type === NodeTypes.GENERATE_TEXT
    ) {
      const promptVal = this.stepForm.get('inputs.prompt')?.value;
      this.updatePromptVariables(promptVal);
    }
  }

  updatePromptVariables(
    promptValue: string | StepOutputReference | null | undefined,
  ): void {
    if (this.localConfig.type !== NodeTypes.GENERATE_TEXT) return;
    const inputs = this.stepForm?.get('inputs') as FormGroup;
    if (!inputs) return;

    let uniqueVars: string[] = [];
    if (typeof promptValue === 'string') {
      const matches = Array.from(
        promptValue.matchAll(/<([a-zA-Z0-9_]+)>/g),
        m => m[1],
      );
      const seen = new Set<string>();
      uniqueVars = [];
      for (const m of matches) {
        const lower = m.toLowerCase();
        if (!seen.has(lower)) {
          seen.add(lower);
          uniqueVars.push(m);
        }
      }
    }

    const baseInputs = this.getBaseInputs();
    const baseInputNames = new Set(baseInputs.map(i => i.name.toLowerCase()));

    // Add any newly discovered variable that doesn't collide with base inputs
    uniqueVars.forEach(varName => {
      if (!baseInputNames.has(varName.toLowerCase())) {
        const alreadyExists = this.localConfig.inputs.some(
          i => i.name.toLowerCase() === varName.toLowerCase(),
        );
        if (!alreadyExists) {
          this.localConfig.inputs.push({
            name: varName,
            label: varName,
            type: 'text',
            required: false,
            isVariable: true,
          });
        }
        const matchingControlName = Object.keys(inputs.controls).find(
          c => c.toLowerCase() === varName.toLowerCase(),
        );
        const controlKey = matchingControlName || varName;
        if (!inputs.contains(controlKey)) {
          inputs.addControl(controlKey, this.fb.control(null));
        }
        if (!this.inputModes[controlKey]) {
          this.initializeInputMode(controlKey, inputs);
        }
      }
    });

    this.updateCompatibleOutputs();
  }

  private initializeInputMode(
    controlName: string,
    inputs: FormGroup = this.stepForm?.get('inputs') as FormGroup,
  ): void {
    const val = inputs?.get(controlName)?.value;
    const isLinked = isStepOutputReference(val);
    this.inputModes[controlName] = isLinked ? 'linked' : 'fixed';
  }
}
