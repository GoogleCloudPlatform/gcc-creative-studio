/**
 * Copyright 2025 Google LLC
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
  Output,
  signal,
  HostListener,
  ViewChild,
  ElementRef,
  computed,
  OnInit,
  OnDestroy,
  inject,
} from '@angular/core';
import {MatSnackBar} from '@angular/material/snack-bar';
import {ReferenceImage, ReferenceVideo} from '../../models/search.model';
import {GenerationModelConfig} from '../../config/model-config';
import {MatIconModule} from '@angular/material/icon';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatButtonModule} from '@angular/material/button';
import {MatMenuModule} from '@angular/material/menu';
import {MatTooltipModule} from '@angular/material/tooltip';

export type NumPos = 1 | 2;

@Component({
  standalone: true,
  selector: 'app-flow-prompt-box',
  templateUrl: './flow-prompt-box.component.html',
  styleUrls: ['./flow-prompt-box.component.scss'],
  imports: [
    CommonModule,
    FormsModule,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatTooltipModule,
  ],
})
export class FlowPromptBoxComponent implements OnInit, OnDestroy {
  private snackBar = inject(MatSnackBar);

  @Input() searchRequest!: any; // Keep for now, but prefer individual inputs
  @Input() isLoading = false;
  @Input() prompt = '';
  @Input() aspectRatio = '16:9';
  @Input() outputs = 4;
  @Input() aspectRatioOptions: {
    value: string;
    viewValue: string;
    disabled: boolean;
    icon?: string;
  }[] = [];
  @Input() modes: {value: string; icon: string; label: string}[] = [];

  // --- setter inputs ---
  private _generationModels: GenerationModelConfig[] = [];
  private generationModelsSignal = signal<GenerationModelConfig[]>([]);
  @Input() set generationModels(val: GenerationModelConfig[]) {
    this._generationModels = val || [];
    this.generationModelsSignal.set(val || []);
    this.updateSupportedResolutions();
  }
  get generationModels(): GenerationModelConfig[] {
    return this._generationModels;
  }
  private _selectedGenerationModel = '';
  private selectedGenerationModelSignal = signal<string>('');
  @Input() set selectedGenerationModel(val: string) {
    this._selectedGenerationModel = val;
    this.selectedGenerationModelSignal.set(val);
    this.updateSupportedResolutions();
  }
  get selectedGenerationModel(): string {
    return this._selectedGenerationModel;
  }

  @Input() set mode(val: string) {
    if (val) {
      const oldMode = this.selectedMode();
      this.selectedMode.set(val);
      this.updateSupportedResolutions(
        undefined,
        oldMode !== '' && oldMode !== val,
      );
    }
  }
  get mode(): string {
    return this.selectedMode();
  }

  @Input() set resolution(val: '1K' | '2K' | '4K' | undefined) {
    if (val) {
      this.selectedResolution.set(val);
    }
  }
  @Input() set duration(val: number | undefined) {
    if (val) {
      this.selectedDuration.set(val);
    }
  }

  // --- outputs ---
  @Output() generateClicked = new EventEmitter<void>();
  @Output() rewriteClicked = new EventEmitter<void>();
  @Output() modelSelected = new EventEmitter<any>();
  @Output() promptChanged = new EventEmitter<string>();
  @Output() resolutionChanged = new EventEmitter<'1K' | '2K' | '4K'>();
  @Output() durationChanged = new EventEmitter<number>();
  @Output() aspectRatioChanged = new EventEmitter<string>();
  @Output() outputsChanged = new EventEmitter<number>();
  @Output() modeChanged = new EventEmitter<string>();
  @Output() openImageSelector = new EventEmitter<NumPos>();
  @Output() editImage = new EventEmitter<{num: NumPos}>();
  @Output() clearImage = new EventEmitter<{num: NumPos; event: Event}>();
  @Output() openImageSelectorForReference = new EventEmitter<void>();
  @Output() onReferenceImageDrop = new EventEmitter<DragEvent>();
  @Output() editReferenceImage = new EventEmitter<{
    index: number;
    ref: ReferenceImage;
  }>();
  @Output() clearReferenceImage = new EventEmitter<{
    index: number;
    event: Event;
  }>();
  @Output() toggleReferenceImagesType = new EventEmitter<boolean>();
  @Output() openVideoSelectorForReference = new EventEmitter<void>();
  @Output() clearReferenceVideo = new EventEmitter<Event>();
  @Output() openVideoSelectorForEdit = new EventEmitter<void>();
  @Output() clearEditSource = new EventEmitter<Event>();
  @Output() stripSourceAudioChanged = new EventEmitter<boolean>();
  @Output() resetClicked = new EventEmitter<void>();
  @Output() openAudioSelectorForReference = new EventEmitter<void>();
  @Output() clearReferenceAudio = new EventEmitter<Event>();

  @Input() image1Preview: string | null = null;
  @Input() image2Preview: string | null = null;
  @Input() referenceImages: ReferenceImage[] = [];
  @Input() referenceImagesType: 'ASSET' | 'STYLE' = 'ASSET';
  @Input() referenceVideo: any | null = null;
  /** The clip being modified in Edit Video mode. */
  @Input() editSource: ReferenceVideo | null = null;
  @Input() stripSourceAudio = true;
  @Input() referenceAudio: any | null = null;

  @ViewChild('promptInput') promptInput?: ElementRef<HTMLTextAreaElement>;
  @ViewChild('modeTrigger') modeTrigger!: ElementRef;
  @ViewChild('modeMenu') modeMenu!: ElementRef;
  @ViewChild('settingsTrigger') settingsTrigger!: ElementRef;
  @ViewChild('settingsMenu') settingsMenu!: ElementRef;

  private resolutionTimeoutId: ReturnType<typeof setTimeout> | null = null;

  constructor(private eRef: ElementRef) {}

  @HostListener('document:click', ['$event'])
  clickout(event: any) {
    // Close Mode Menu if clicked outside trigger and menu
    if (
      this.isModeMenuOpen() &&
      this.modeTrigger &&
      !this.modeTrigger.nativeElement.contains(event.target) &&
      (!this.modeMenu || !this.modeMenu.nativeElement.contains(event.target))
    ) {
      this.isModeMenuOpen.set(false);
    }

    // Close Settings Menu if clicked outside trigger and menu
    if (
      this.isSettingsMenuOpen() &&
      this.settingsTrigger &&
      !this.settingsTrigger.nativeElement.contains(event.target) &&
      (!this.settingsMenu ||
        !this.settingsMenu.nativeElement.contains(event.target))
    ) {
      this.isSettingsMenuOpen.set(false);
    }
  }

  // All possible resolutions
  readonly ALL_RESOLUTIONS: ('1K' | '2K' | '4K')[] = ['1K', '2K', '4K'];

  // --- Logic moved from VideoComponent ---

  promptText = signal<string>('');

  // Menu open/close states
  isModeMenuOpen = signal<boolean>(false);
  isSettingsMenuOpen = signal<boolean>(false);
  isSettingsDropdownOpen = signal<
    'aspect' | 'outputs' | 'model' | 'resolution' | 'duration' | null
  >(null);
  selectedMode = signal<string>('Text to Video');
  selectedPreset = signal<string>('');
  selectedResolution = signal<'1K' | '2K' | '4K'>('1K');
  selectedDuration = signal<number>(4);

  supportedResolutions = signal<('1K' | '2K' | '4K')[]>([]);

  // --- Computed Values ---
  isExtendVideo = computed(() => this.selectedMode() === 'Extend Video');
  isIngredientsToImage = computed(
    () => this.selectedMode() === 'Ingredients to Image',
  );
  isTextToVideo = computed(() => this.selectedMode() === 'Text to Video');
  hasResolutionOptions = computed(() => this.supportedResolutions().length > 0);
  hasDurationOptions = computed(
    () =>
      (this.getSelectedModelObject()?.capabilities?.supportedDurations ?? [])
        .length > 0,
  );

  // --- Lifecycle Hooks ---
  ngOnInit(): void {
    this.updateSupportedResolutions();
  }

  ngOnDestroy(): void {
    if (this.resolutionTimeoutId) {
      clearTimeout(this.resolutionTimeoutId);
    }
  }

  // --- Event Handlers ---

  onPromptInput(event: Event) {
    const target = event.target as HTMLTextAreaElement;
    this.promptChanged.emit(target.value);
  }

  /** True when there is anything for the reset control to clear. */
  get hasResettableInput(): boolean {
    return !!(
      this.prompt ||
      this.referenceImages.length ||
      this.image1Preview ||
      this.image2Preview ||
      this.referenceVideo ||
      this.editSource
    );
  }

  /**
   * Whether reference images can accompany an opening frame in Frames to Video.
   *
   * Veo types its reference images separately from its input image and rejects
   * both together. Omni carries every image in one multimodal input, so an
   * opening frame plus character sheets is the normal way to anchor a shot
   * while holding identities - the backend routes it to image_to_video so the
   * frame stays frame 1.
   */
  get supportsFramePlusReferences(): boolean {
    return !!this.getSelectedModelObject()?.capabilities
      ?.supportsFrameWithReferences;
  }

  /** Whether the active model binds <IMAGE_REF_N> tags to reference images. */
  get supportsRoleTags(): boolean {
    return !!this.getSelectedModelObject()?.capabilities?.supportsRoleTags;
  }

  /**
   * Inserts a role tag at the caret.
   *
   * Reference images are positional, so the index a tag refers to is otherwise
   * invisible - a user would have to count thumbnails and type the tag by hand.
   */
  insertRoleTag(tag: string): void {
    const textarea: HTMLTextAreaElement | undefined =
      this.promptInput?.nativeElement;
    const current = this.prompt ?? '';

    if (!textarea) {
      this.promptChanged.emit(`${current} ${tag}`.trim());
      return;
    }

    const start = textarea.selectionStart ?? current.length;
    const end = textarea.selectionEnd ?? start;
    const before = current.slice(0, start);
    const after = current.slice(end);

    // Keep the tag as its own word so it does not fuse with adjacent text.
    const lead = before && !/\s$/.test(before) ? ' ' : '';
    const trail = after && !/^\s/.test(after) ? ' ' : '';
    const insertion = `${lead}${tag}${trail}`;

    this.promptChanged.emit(before + insertion + after);

    // The prompt round-trips through the parent, so restore the caret once the
    // new value has been applied.
    const caret = start + insertion.length;
    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(caret, caret);
    });
  }

  onEditOverlayClick(num?: NumPos, index?: number, ref?: ReferenceImage): void {
    if (num) {
      this.editImage.emit({num});
    } else if (index !== undefined && ref) {
      this.editReferenceImage.emit({index, ref});
    }
  }

  // --- Menu Toggles ---

  toggleModeMenu() {
    this.isModeMenuOpen.set(!this.isModeMenuOpen());
    this.isSettingsMenuOpen.set(false);
  }

  toggleSettingsMenu() {
    this.isSettingsMenuOpen.set(!this.isSettingsMenuOpen());
    this.isModeMenuOpen.set(false);
    this.isSettingsDropdownOpen.set(null); // Close inner dropdowns
  }

  // --- Select Handlers ---

  selectMode(mode: string) {
    const oldMode = this.selectedMode();
    this.selectedMode.set(mode);
    this.modeChanged.emit(mode);
    this.isModeMenuOpen.set(false);

    // Call the centralized update method and explicitly pass modeChanged=true
    this.updateSupportedResolutions(
      undefined,
      oldMode !== '' && oldMode !== mode,
    );

    if (!this.isTextToVideo()) {
      const longest = this.getSelectedModelDurations().at(-1);
      if (longest) this.selectDuration(longest);
    }
  }

  selectResolution(resolution: '1K' | '2K' | '4K', model?: any) {
    if (!this.supportedResolutions().includes(resolution)) return;

    this.selectedResolution.set(resolution);
    this.resolutionChanged.emit(resolution);
    this.isSettingsDropdownOpen.set(null);

    if (resolution !== '1K') {
      const longest = this.getSelectedModelDurations(model).at(-1);
      if (longest) this.selectDuration(longest);
    }
  }

  selectDuration(duration: number) {
    this.selectedDuration.set(duration);
    this.durationChanged.emit(duration);
    this.isSettingsDropdownOpen.set(null);
  }

  selectNewAspectRatio(ratio: string) {
    this.aspectRatioChanged.emit(ratio);
    this.isSettingsDropdownOpen.set(null);
  }

  selectOutputs(count: number) {
    this.outputsChanged.emit(count);
    this.isSettingsDropdownOpen.set(null);
  }

  // Triggered from internal dropdown
  selectInternalModel(model: any) {
    this.isSettingsDropdownOpen.set(null);
    this.modelSelected.emit(model);

    this.updateSupportedResolutions(model);
  }

  selectPreset(preset: string) {
    this.selectedPreset.set(preset);
  }

  getSelectedModelObject(): GenerationModelConfig | undefined {
    return this.generationModelsSignal().find(
      m => m.viewValue === this.selectedGenerationModelSignal(),
    );
  }

  getSelectedModelResolutions(model?: any): ('1K' | '2K' | '4K')[] {
    const activeModel = model || this.getSelectedModelObject();
    const all = activeModel?.capabilities?.supportedResolutions ?? [];

    // Extending a video does drop to the lowest resolution. Editing an image
    // does not: Nano Banana Pro and Nano Banana 2 both return full 2K and 4K
    // with a reference image attached, verified against the live API. Pinning
    // Ingredients to Image to the smallest option withheld resolutions the
    // model would happily have produced.
    if (this.isExtendVideo()) {
      const smallest = all[0];
      return smallest ? [smallest] : [];
    }
    return all;
  }

  getSelectedModelDurations(model?: any): number[] {
    const activeModel = model || this.getSelectedModelObject();
    const all = activeModel?.capabilities?.supportedDurations ?? [];

    // Veo only offers shorter lengths in text-to-video, and only at 1K;
    // everywhere else it is pinned to the longest. That is a Veo constraint,
    // not a universal one - applying it to every model left Gemini Omni
    // stuck at 10s in every mode except text-to-video, even though it accepts
    // its full 3-10s range regardless of mode.
    if (!activeModel?.capabilities?.restrictsDurationOutsideTextToVideo) {
      return all;
    }

    if (!this.isTextToVideo() || this.selectedResolution() !== '1K') {
      const longest = all.at(-1);
      return longest ? [longest] : [];
    }

    return all;
  }

  /** Output counts the active model allows, for the x1..xN selector. */
  availableOutputs(): number[] {
    const max = this.getSelectedModelObject()?.capabilities?.maxOutputs ?? 4;
    return Array.from({length: Math.max(1, max)}, (_, i) => i + 1);
  }

  private updateSupportedResolutions(model?: any, modeChanged = false) {
    const supported = this.getSelectedModelResolutions(model);
    this.supportedResolutions.set(supported);

    const activeModel = model || this.getSelectedModelObject();

    // Notify user if resolution was artificially restricted by the current mode
    if (
      activeModel &&
      activeModel.capabilities?.supportedResolutions?.length > 1 &&
      supported.length === 1
    ) {
      // Only show the snackbar if the dropdown is opened or mode changed (avoid spamming on init)
      // Actually we can just show it if they selected the model manually or it's forced to change
      if (
        model ||
        modeChanged ||
        !supported.includes(this.selectedResolution())
      ) {
        this.snackBar.open(
          `For ${this.selectedMode()} mode, ${activeModel.viewValue} supports only ${supported[0]} resolution.`,
          'Close',
          {duration: 5000},
        );
      }
    }

    if (
      supported.length > 0 &&
      !supported.includes(this.selectedResolution())
    ) {
      const fallbackResolution = supported[0];
      this.selectedResolution.set(fallbackResolution);
      // Defer event emission to avoid ExpressionChangedAfterItHasBeenCheckedError in parent during change detection
      if (this.resolutionTimeoutId) clearTimeout(this.resolutionTimeoutId);
      this.resolutionTimeoutId = setTimeout(() =>
        this.resolutionChanged.emit(fallbackResolution),
      );
    }
  }
}
