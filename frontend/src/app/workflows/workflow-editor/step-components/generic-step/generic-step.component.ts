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
import {
  AbstractControl,
  FormBuilder,
  FormGroup,
  ValidatorFn,
  Validators,
} from '@angular/forms';
import {MatDialog} from '@angular/material/dialog';
import {NotificationService} from '../../../../common/services/notification.service';
import {FloatLabelType} from '@angular/material/form-field';
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
  getSupportedModelDurations,
} from '../../../../common/config/model-config';
import {
  InputUnlinkState,
  StepConfig,
  StepInput,
  StepOutput,
  StepSetting,
  UnlinkMenuItem,
  UnlinkOption,
} from './step.model';
import {
  AvailableOutput,
  DynamicStepRecord,
  EditorMode,
  NodeTypes,
  StepEntry,
  StepInputUnlinkEvent,
  StepInputValue,
  StepOutputReference,
  StepStatusEnum,
} from '../../../workflow.models';
import {
  getLinkedRefs,
  isSameStepOutput,
  isStepOutputReference,
} from '../../../utils/workflow-step.util';
import {
  getLatestStepInputs,
  getLatestStepOutputs,
} from '../../../utils/step-history.util';
import {
  LOOP_CURRENT_ITEM_PORT,
  LOOP_ENDING_PORT,
  LOOP_FOLDER_INPUT,
  LOOP_ITEMS_TEXT_INPUT,
  LOOP_ITEM_TYPE_MIME_MAP,
  LOOP_ITEM_TYPE_SETTING,
  LOOP_LINKED_ITEMS_INPUT,
  LOOP_MODE_FOLDER,
  LOOP_MODE_LINKED_ITEMS,
  LOOP_MODE_SETTING,
  LOOP_MODE_TEXT_INPUT,
  MAX_LOOP_ITEMS,
  getLoopCurrentItemType,
  getLoopLinkedItemsInputType,
  loopItemsTextValidator,
  loopLinkedItemsRequiredValidator,
  toLoopItemType,
  toLoopMode,
} from '../step-configs/loop-step.config';
import {
  FolderPreviewMimeType,
  folderInputValidator,
} from '../step-configs/folder-setting.util';
import {getOutputFolderMimeType} from '../step-configs/output-folder-setting';
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
import {MatMenuTrigger} from '@angular/material/menu';

type InputUnlinkStates = Record<string, InputUnlinkState>;

const UNLINK_MENU_OPEN_KEYS: ReadonlySet<string> = new Set(['Enter', ' ']);

/** Media kind of a Generate Video reference input. */
type ReferenceKind = 'image' | 'video';

/** How long the reference trimming notice stays visible. */
const TRIM_NOTICE_DURATION_MS = 5000;

/** Outcome of trimming one kind of reference to a model's limit. */
interface TrimmedReferences {
  removed: number;
  max: number;
  kind: ReferenceKind;
}

@Component({
  selector: 'app-generic-step',
  templateUrl: './generic-step.component.html',
  styleUrls: ['./generic-step.component.scss'],
})
export class GenericStepComponent implements OnInit, OnChanges, OnDestroy {
  @Input() stepForm!: FormGroup;
  @Input() stepIndex!: number;
  @Input() availableOutputs: AvailableOutput[] = [];
  @Input() mode: EditorMode = EditorMode.Create;
  @Input() config!: StepConfig;
  @Input() showValidationErrors = false;
  @Input() mediaUrlMap!: Map<string, string>;
  @Input() isSelected = false;
  @Input() isHighlighted = false;
  @Input() activeMagneticPort: {stepId: string; inputName: string} | null =
    null;
  @Input() dragSourcePort: DragSourcePort | null = null;

  protected readonly unlinkStateByInput = signal<InputUnlinkStates>({});
  readonly noUnlinkState: InputUnlinkState = {
    canUnlink: false,
    ariaLabel: null,
    items: [],
  };
  readonly trackUnlinkItem = (_i: number, item: UnlinkMenuItem): string =>
    item.id;
  /** Unlink chosen in the unlink menu, emitted once the menu has closed. */
  private pendingUnlink: StepInputUnlinkEvent | null = null;
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
  @Output() unlink = new EventEmitter<StepInputUnlinkEvent>();

  StepStatusEnum = StepStatusEnum;
  EditorMode = EditorMode;
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
  readonly loopLinkedItemsInputName = LOOP_LINKED_ITEMS_INPUT;
  /** Media previewed by the folder picker of this node's folder inputs. */
  readonly folderPickerMimeType = signal<FolderPreviewMimeType>('image/*');

  private readonly fb = inject(FormBuilder);
  private readonly notificationService = inject(NotificationService);
  private settingsSubscription?: Subscription;
  private inputModeSubscription?: Subscription;
  private modeSubscription?: Subscription;
  private inputsSubscription?: Subscription;
  private collapsedSubscription?: Subscription;
  private loopItemTypeSubscription?: Subscription;
  currentMaxReferenceImages = 1;

  isCollapsed = false;
  inputModes: {[key: string]: 'fixed' | 'linked' | 'mixed'} = {};
  /**
   * Inputs whose value is currently a single step-output reference (wired).
   * Used to detect when a wire is removed so the input returns to fixed mode,
   * without overriding an explicit "Link" mode chosen with no wire yet.
   */
  private wiredInputs = new Set<string>();
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
    if (
      this.localConfig?.type === NodeTypes.GENERATE_VIDEO &&
      inputName === 'input_video'
    ) {
      const currentModel = this.stepForm?.get('settings.model')?.value;
      const modelConfig = MODEL_CONFIGS.find(c => c.value === currentModel);
      if ((modelConfig?.capabilities.maxReferenceVideos ?? 0) === 0) {
        return 'This model does not support Video as reference';
      }
    }
    return '';
  }

  private getInputValue(inputName: string): StepInputValue {
    return this.stepForm?.get('inputs')?.get(inputName)?.value;
  }

  canUnlink(inputName: string): boolean {
    if (this.mode === EditorMode.Run || this.isInputDisabled(inputName))
      return false;
    return getLinkedRefs(this.getInputValue(inputName)).length > 0;
  }

  getUnlinkOptions(inputName: string): UnlinkOption[] {
    const refs = getLinkedRefs(this.getInputValue(inputName));
    return refs.map(ref => ({
      ref,
      label: this.getLinkLabel(ref),
    }));
  }

  private getLinkLabel(ref: StepOutputReference): string {
    return this.availableOutputs.reduce((carry, item) => {
      const newLabel = isSameStepOutput(item.value, ref)
        ? item.label.trim()
        : '';
      return newLabel === '' ? carry : newLabel;
    }, `${ref.step}.${ref.output}`);
  }

  private getStepId(): string {
    return this.stepForm?.value?.stepId ?? '';
  }

  private getInputs(): StepInput[] {
    return this.localConfig?.inputs ?? [];
  }

  private toUnlinkMenuItem(
    stepId: string,
    input: StepInput,
    option: UnlinkOption,
  ): UnlinkMenuItem {
    return {
      ...option,
      id: `unlink-option-${stepId}-${input.name}-${option.ref.step}.${option.ref.output}`,
      text: `Unlink ${option.label}`,
      ariaLabel: `Unlink ${option.label} from ${input.label}`,
    };
  }

  private refreshUnlinkStates(): void {
    const states: InputUnlinkStates = {};
    const stepId = this.getStepId();
    this.getInputs().forEach(input => {
      const canUnlink = this.canUnlink(input.name);
      const availableItems = canUnlink ? this.getUnlinkOptions(input.name) : [];
      const items = availableItems.map(
        this.toUnlinkMenuItem.bind(this, stepId, input),
      );
      const ariaLabel = canUnlink ? `Unlink options for ${input.label}` : null;
      states[input.name] = {canUnlink, ariaLabel, items};
    });
    this.unlinkStateByInput.set(states);
  }

  private stopPropagationIfUnlinkable(event: Event, inputName: string): void {
    if (this.canUnlink(inputName)) event.stopPropagation();
  }

  onInputPortMouseDown(event: MouseEvent, inputName: string): void {
    this.stopPropagationIfUnlinkable(event, inputName);
  }

  onInputPortClick(event: MouseEvent, inputName: string): void {
    this.stopPropagationIfUnlinkable(event, inputName);
  }

  /**
   * Stores the chosen link; it is emitted by {@link onUnlinkMenuClosed}.
   * Emitting right away would unbind the menu (no links left) while the
   * trigger is still closing, which breaks MatMenuTrigger.
   */
  onUnlinkOptionSelected(inputName: string, ref: StepOutputReference): void {
    this.pendingUnlink = {stepId: this.getStepId(), inputName, ref};
  }

  /** Emits the pending unlink, if any, once the unlink menu has fully closed. */
  onUnlinkMenuClosed(): void {
    const pendingUnlink = this.pendingUnlink;
    this.pendingUnlink = null;
    if (pendingUnlink) this.unlink.emit(pendingUnlink);
  }

  /** A div gets no native click from Enter/Space, so open the menu here. */
  onInputPortKeydown(
    event: KeyboardEvent,
    inputName: string,
    trigger: MatMenuTrigger,
  ): void {
    if (!UNLINK_MENU_OPEN_KEYS.has(event.key) || !this.canUnlink(inputName))
      return;
    event.preventDefault();
    trigger.openMenu();
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
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['stepForm'] || changes['config']) {
      this.initializeStepState();
    }
    if (changes['availableOutputs']) {
      this.updateCompatibleOutputs();
    }
    if (changes['availableOutputs'] || changes['mode']) {
      this.refreshUnlinkStates();
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
      const validators = this.buildInputValidators(input);

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
    this.wiredInputs = new Set(
      Object.keys(inputs.controls).filter(key =>
        isStepOutputReference(inputs.get(key)?.value),
      ),
    );
    this.inputsSubscription = inputs.valueChanges.subscribe(value => {
      if (!value) return;
      Object.keys(value).forEach(key => {
        const val = value[key];
        const isLinked = isStepOutputReference(val);
        if (isLinked && this.inputModes[key] !== 'linked') {
          this.inputModes[key] = 'linked';
        }
        const wasWired = this.wiredInputs.has(key);
        if (isLinked) {
          this.wiredInputs.add(key);
        } else {
          this.wiredInputs.delete(key);
        }
        if (
          wasWired &&
          !isLinked &&
          !Array.isArray(val) &&
          !this.isLinkedOnlyInput(key)
        ) {
          this.inputModes[key] = 'fixed';
        }
      });
      this.refreshUnlinkStates();
      if (this.localConfig?.type === NodeTypes.GENERATE_VIDEO) {
        this.syncVideoDurationSetting();
      }
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
            this.updateDynamicConfig(value, true);
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
          this.syncVideoDurationSetting();
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

      this.folderPickerMimeType.set(this.getFolderPickerMimeType());
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
    this.refreshUnlinkStates();
  }

  /** Validators of a step input: `required` and, for folders, a valid id or link. */
  private buildInputValidators(input: StepInput): ValidatorFn[] {
    const requiredValidators = input.required ? [Validators.required] : [];
    return input.type === 'folder'
      ? [...requiredValidators, folderInputValidator]
      : requiredValidators;
  }

  /**
   * Applies model-dependent settings. `notifyTrimming` is only set for
   * user-driven model changes so hydrating a saved step stays silent.
   */
  private updateDynamicConfig(
    modelValue: string | null,
    notifyTrimming = false,
  ): void {
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
        } else if (
          this.localConfig.type === NodeTypes.GENERATE_VIDEO &&
          this.stepForm.get('settings.resolution')
        ) {
          this.resetVideoResolutionTo1K();
        }
      } else if (
        this.localConfig.type === NodeTypes.GENERATE_VIDEO &&
        modelMeta.supportedResolutions.length === 0 &&
        this.stepForm.get('settings.resolution')
      ) {
        this.resetVideoResolutionTo1K();
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
    if (this.localConfig.type === NodeTypes.GENERATE_VIDEO) {
      this.syncVideoDurationSetting();
    } else {
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

    // 5. Update Inputs based on Mode and Max Refs
    const maxRefs = modelMeta.maxReferenceImages; // 0, 1, or more
    this.currentMaxReferenceImages = maxRefs;

    if (
      this.localConfig.type === NodeTypes.GENERATE_VIDEO &&
      !this.stepForm.disabled
    ) {
      const inputs = this.stepForm.get('inputs') as FormGroup | null;
      const maxImages = modelMeta.maxReferenceImages ?? 0;
      const maxVideos = modelMeta.maxReferenceVideos ?? 0;
      const removedImages =
        this.trimControlToMax(inputs?.get('input_images'), maxImages) +
        this.trimControlToMax(inputs?.get('reference_images'), maxImages);
      const removedVideos = this.trimControlToMax(
        inputs?.get('input_video'),
        maxVideos,
      );
      if (notifyTrimming) {
        this.notifyTrimmedReferences(
          modelConfig.viewValue,
          {removed: removedImages, max: maxImages, kind: 'image'},
          {removed: removedVideos, max: maxVideos, kind: 'video'},
        );
      }
    }

    this.updateInputVisibility();
  }

  private notifyTrimmedReferences(
    modelLabel: string,
    ...trims: TrimmedReferences[]
  ): void {
    const messages = trims
      .filter(trim => trim.removed > 0)
      .map(trim =>
        trim.max <= 0
          ? `Removed the reference ${trim.kind}(s) because ${modelLabel} does not support ${trim.kind} references.`
          : `Removed ${trim.removed} excess reference ${trim.kind}(s) because ${modelLabel} supports up to ${trim.max}.`,
      );
    if (messages.length > 0) {
      this.notificationService.show(
        messages.join(' '),
        'info',
        undefined,
        'info',
        TRIM_NOTICE_DURATION_MS,
      );
    }
  }

  private resetVideoResolutionTo1K(): void {
    const resolutionControl = this.stepForm.get('settings.resolution');
    const currentResolution = resolutionControl?.value;
    if (currentResolution && currentResolution !== '1K') {
      resolutionControl?.setValue('1K');
    }
  }

  private hasStepInputValue(val: unknown): boolean {
    if (val === null || val === undefined || val === '') {
      return false;
    }
    if (Array.isArray(val)) {
      return val.length > 0;
    }
    if (typeof val === 'object') {
      return Object.keys(val as Record<string, unknown>).length > 0;
    }
    return true;
  }

  /**
   * Trims a list input to `maxAllowed` items (clearing it when the limit is 0)
   * and returns how many items were removed.
   */
  private trimControlToMax(
    control: AbstractControl | null | undefined,
    maxAllowed: number,
  ): number {
    if (!control || control.value === null || control.value === undefined) {
      return 0;
    }
    const value: unknown = control.value;
    if (maxAllowed <= 0) {
      control.setValue(null);
      if (Array.isArray(value)) {
        return value.length;
      }
      return this.hasStepInputValue(value) ? 1 : 0;
    }
    if (Array.isArray(value) && value.length > maxAllowed) {
      control.setValue(value.slice(0, maxAllowed));
      return value.length - maxAllowed;
    }
    return 0;
  }

  private syncVideoDurationSetting(): void {
    if (this.localConfig?.type !== NodeTypes.GENERATE_VIDEO) {
      return;
    }
    const durationSetting = this.localConfig.settings.find(
      s => s.name === 'duration_seconds',
    );
    if (!durationSetting) {
      return;
    }

    const modelValue = this.stepForm?.get('settings.model')?.value;
    const modelConfig = MODEL_CONFIGS.find(c => c.value === modelValue);
    const currentMode =
      this.stepForm?.get('settings.input_mode')?.value || 'Text to Video';
    const currentResolution =
      (this.stepForm?.get('settings.resolution')?.value as
        | '1K'
        | '2K'
        | '4K'
        | undefined) ?? '1K';
    const inputs = this.stepForm?.get('inputs') as FormGroup | null;
    const hasEndFrame = this.hasStepInputValue(inputs?.get('end_frame')?.value);
    const supportedDurations = getSupportedModelDurations(
      modelConfig,
      currentMode,
      currentResolution,
      hasEndFrame,
    );

    if (supportedDurations.length > 0) {
      durationSetting.hidden = false;
      durationSetting.options = supportedDurations.map(duration => ({
        value: duration,
        label: `${duration}s`,
      }));

      const durationControl = this.stepForm?.get('settings.duration_seconds');
      const currentDuration = Number(durationControl?.value);
      if (
        durationControl &&
        !this.stepForm.disabled &&
        (Number.isNaN(currentDuration) ||
          !supportedDurations.includes(currentDuration))
      ) {
        const maxSupported = supportedDurations[supportedDurations.length - 1];
        const targetDuration =
          !Number.isNaN(currentDuration) && currentDuration > maxSupported
            ? maxSupported
            : supportedDurations[0];
        if (durationControl.value !== targetDuration) {
          durationControl.setValue(targetDuration);
        }
      }
    } else {
      durationSetting.hidden = true;
    }
  }

  private updateInputVisibility(): void {
    const currentMode = this.stepForm.get('settings.input_mode')?.value;
    const currentModel = this.stepForm.get('settings.model')?.value;
    const modelConfig = MODEL_CONFIGS.find(c => c.value === currentModel);
    const supportsVideoRef =
      (modelConfig?.capabilities.maxReferenceVideos ?? 0) > 0;
    const maxRefs = this.currentMaxReferenceImages;

    this.localConfig.inputs.forEach(input => {
      // Logic for specific inputs
      if (
        this.localConfig.type === NodeTypes.GENERATE_VIDEO &&
        (input.name === 'input_images' ||
          input.name === 'reference_images' ||
          input.name === 'input_video')
      ) {
        const showIngredients = currentMode === 'Ingredients to Video';
        const isImageRef =
          input.name === 'input_images' || input.name === 'reference_images';
        const isVideoRef = input.name === 'input_video';
        const isVisible = isImageRef
          ? showIngredients && maxRefs > 0
          : showIngredients;

        if (isVisible) {
          input.hidden = false;
          if (isVideoRef && !supportsVideoRef) {
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
      } else if (
        this.localConfig.type === NodeTypes.GENERATE_VIDEO &&
        input.name === 'source_video'
      ) {
        if (currentMode === 'Extend Video') {
          input.hidden = false;
          this.stepForm.get('inputs')?.get(input.name)?.enable();
          this.inputModes[input.name] = 'mixed';
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
    this.loopItemTypeSubscription?.unsubscribe();
    this.loopItemTypeSubscription = settings
      .get(LOOP_ITEM_TYPE_SETTING)
      ?.valueChanges.subscribe(() => this.updateLoopModeConfig());
    this.updateLoopModeConfig();
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
      if (setting.name === LOOP_ITEM_TYPE_SETTING) {
        setting.hidden = isTextMode;
      }
    });

    this.applyLoopSourceInput(LOOP_FOLDER_INPUT, isFolderMode, [
      Validators.required,
      folderInputValidator,
    ]);
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

    this.folderPickerMimeType.set(this.getFolderPickerMimeType());
    this.updateCompatibleOutputs();
    this.refreshUnlinkStates();
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

  /** Media previewed by the folder picker for this node. */
  private getFolderPickerMimeType(): FolderPreviewMimeType {
    if (!this.isLoopStep) {
      return getOutputFolderMimeType(this.localConfig.type);
    }
    const itemType = toLoopItemType(
      this.stepForm.get('settings')?.get(LOOP_ITEM_TYPE_SETTING)?.value,
    );
    return LOOP_ITEM_TYPE_MIME_MAP[itemType];
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
    this.refreshUnlinkStates();
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
    this.refreshUnlinkStates();
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

  private isLinkedOnlyInput(inputName: string): boolean {
    return !!this.localConfig?.inputs.find(i => i.name === inputName)
      ?.linkedOnly;
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
