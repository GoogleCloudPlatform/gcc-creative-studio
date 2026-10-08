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

import {Component, Input, OnInit, computed, signal} from '@angular/core';
import {Router} from '@angular/router';
import {
  DynamicStepRecord,
  LoopItemType,
  LoopMode,
  NodeTypes,
  StepErrorInfo,
} from '../../workflow.models';
import {IMAGE_MODE_ALLOWED_INPUTS} from '../../workflow-editor/step-components/step-configs/image-step.config';
import {
  LOOP_MODE_LABELS,
  LOOP_MODE_TEXT_INPUT,
  buildLoopTruncationMessage,
  isLoopMediaMode,
  toLoopItemType,
  toLoopMode,
} from '../../workflow-editor/step-components/step-configs/loop-step.config';
import {isVideoUrl} from '../../utils/workflow-step.util';
import {STEP_CONFIGS_MAP} from '../step-configs.map';

/** Output key holding a Loop step's resolved items. */
const LOOP_ITEMS_KEY = 'items';

/** Input key holding a Loop step's source mode. */
const LOOP_MODE_KEY = 'mode';

/** Recorded Loop inputs shown in run details, per source mode. */
const LOOP_INPUT_KEYS_BY_MODE: Readonly<Record<LoopMode, readonly string[]>> = {
  folder: [LOOP_MODE_KEY, 'folder_name', 'item_type'],
  text_input: [LOOP_MODE_KEY, 'items_text'],
  linked_items: [LOOP_MODE_KEY, 'item_type', 'source_count', 'skipped_count'],
};

/** `mediaUrlMap` key prefixes (see MediaResolutionService). */
const MEDIA_KEY_PREFIX = 'media:';
const ASSET_KEY_PREFIX = 'asset:';

@Component({
  selector: 'app-step-execution-details',
  templateUrl: './step-execution-details.component.html',
  styleUrls: ['./step-execution-details.component.scss'],
})
export class StepExecutionDetailsComponent implements OnInit {
  @Input() stepId = '';
  @Input() mediaUrlMap: Map<string, string> = new Map();
  @Input() mode: string | null = null;
  @Input() attempts: number | null = null;
  @Input() lastError: StepErrorInfo | null = null;
  @Input() error: StepErrorInfo | string | null = null;
  /** Whether the Inputs block is rendered (node cards never show inputs). */
  @Input() showInputs = true;
  /** Whether the Outputs block is rendered. */
  @Input() showOutputs = true;

  private readonly stepTypeState = signal<string>('');
  private readonly inputsState = signal<DynamicStepRecord>({});
  private readonly outputsState = signal<DynamicStepRecord>({});

  @Input() set stepType(value: string | null) {
    this.stepTypeState.set(value ?? '');
  }
  get stepType(): string {
    return this.stepTypeState();
  }

  @Input() set inputs(value: DynamicStepRecord | null) {
    this.inputsState.set(value ?? {});
  }
  get inputs(): DynamicStepRecord {
    return this.inputsState();
  }

  @Input() set outputs(value: DynamicStepRecord | null) {
    this.outputsState.set(value ?? {});
  }
  get outputs(): DynamicStepRecord {
    return this.outputsState();
  }

  /** True when rendering a Loop step's run data. */
  readonly isLoopStep = computed(() => this.stepTypeState() === NodeTypes.LOOP);

  /** Media type of a Loop's items in a media mode, otherwise `null`. */
  readonly loopMediaType = computed<LoopItemType | null>(() => {
    if (!this.isLoopStep()) return null;
    const inputs = this.inputsState();
    // The raw value is compared on purpose: a missing mode is not a media mode.
    return isLoopMediaMode(inputs[LOOP_MODE_KEY])
      ? toLoopItemType(inputs['item_type'])
      : null;
  });

  /** True when a Loop iterates comma-separated text items. */
  readonly isLoopTextMode = computed(
    () =>
      this.isLoopStep() &&
      this.inputsState()[LOOP_MODE_KEY] === LOOP_MODE_TEXT_INPUT,
  );

  /** Resolved Loop text items rendered as a numbered list. */
  readonly loopTextItems = computed<string[]>(() => {
    if (!this.isLoopTextMode()) return [];
    const items = this.outputsState()[LOOP_ITEMS_KEY];
    return Array.isArray(items) ? items.map(item => String(item)) : [];
  });

  /** Warning banner shown above a truncated Loop's items. */
  readonly loopTruncationMessage = computed<string | null>(() => {
    if (!this.isLoopStep()) return null;
    const outputs = this.outputsState();
    if (outputs['truncated'] !== true) return null;
    const totalFound = Number(outputs['total_found'] ?? 0);
    return buildLoopTruncationMessage(totalFound);
  });

  loadedMedia = new Set<string>();
  NodeTypes = NodeTypes;
  readonly loopItemsKey = LOOP_ITEMS_KEY;

  constructor(private router: Router) {}

  ngOnInit(): void {}

  get resolvedAttempts(): number | null {
    if (
      this.attempts !== null &&
      this.attempts !== undefined &&
      this.attempts > 0
    ) {
      return this.attempts;
    }
    return null;
  }

  get resolvedError(): StepErrorInfo | null {
    const candidate = this.lastError ?? this.error;
    if (!candidate) return null;
    if (typeof candidate === 'string') {
      return candidate.trim() ? {category: 'ERROR', detail: candidate} : null;
    }
    if (
      typeof candidate === 'object' &&
      (candidate.category || candidate.detail)
    ) {
      return {
        category: candidate.category || 'UNKNOWN',
        detail: candidate.detail || '',
      };
    }
    return null;
  }

  private isImageStep(): boolean {
    return this.stepType === NodeTypes.IMAGE;
  }

  private getActiveImageMode(): string {
    return this.mode || 'generate_image';
  }

  private hasValue(value: any): boolean {
    if (value === null || value === undefined || value === '') return false;
    if (Array.isArray(value) && value.length === 0) return false;
    return true;
  }

  get filteredInputs(): Record<string, any> {
    if (!this.inputs || typeof this.inputs !== 'object') return {};

    const result: Record<string, any> = {};

    if (this.isLoopStep()) {
      const loopMode = toLoopMode(this.inputs['mode']);
      LOOP_INPUT_KEYS_BY_MODE[loopMode]
        .filter(key => this.hasValue(this.inputs[key]))
        .forEach(key => (result[key] = this.inputs[key]));
      if (LOOP_MODE_KEY in result) {
        result[LOOP_MODE_KEY] = LOOP_MODE_LABELS[loopMode];
      }
      return result;
    }

    if (this.isImageStep()) {
      const activeMode = this.getActiveImageMode();
      const allowedKeys = IMAGE_MODE_ALLOWED_INPUTS[activeMode] || ['prompt'];

      for (const [key, value] of Object.entries(this.inputs)) {
        if (allowedKeys.includes(key) && this.hasValue(value)) {
          result[key] = value;
        }
      }
      return result;
    }

    const config = this.getStepConfig();
    const configInputNames = config?.inputs?.map((i: any) => i.name) || [];

    for (const [key, value] of Object.entries(this.inputs)) {
      if (
        (configInputNames.length === 0 || configInputNames.includes(key)) &&
        this.hasValue(value)
      ) {
        result[key] = value;
      }
    }

    return result;
  }

  get filteredOutputs(): Record<string, any> {
    if (!this.outputs || typeof this.outputs !== 'object') return {};

    const result: Record<string, any> = {};

    if (this.isLoopStep()) {
      if (this.hasValue(this.outputs[LOOP_ITEMS_KEY])) {
        result[LOOP_ITEMS_KEY] = this.outputs[LOOP_ITEMS_KEY];
      }
      return result;
    }

    if (this.isImageStep()) {
      const primaryKey = 'generated_image';
      if (this.hasValue(this.outputs[primaryKey])) {
        result[primaryKey] = this.outputs[primaryKey];
      } else if (this.hasValue(this.outputs['edited_image'])) {
        result[primaryKey] = this.outputs['edited_image'];
      } else if (this.hasValue(this.outputs['upscaled_image'])) {
        result[primaryKey] = this.outputs['upscaled_image'];
      } else if (this.hasValue(this.outputs['image_output'])) {
        result[primaryKey] = this.outputs['image_output'];
      }
      return result;
    }

    const config = this.getStepConfig();
    const configOutputNames = config?.outputs?.map((o: any) => o.name) || [];

    for (const [key, value] of Object.entries(this.outputs)) {
      if (
        (configOutputNames.length === 0 || configOutputNames.includes(key)) &&
        this.hasValue(value)
      ) {
        result[key] = value;
      }
    }

    return result;
  }

  getMediaUrl(value: any): string {
    const key = this.getKeyFromValue(value);
    if (key && this.mediaUrlMap.has(key)) {
      return this.mediaUrlMap.get(key)!;
    }

    if (value && typeof value === 'object' && value.previewUrl) {
      return value.previewUrl;
    } else if (
      typeof value === 'string' &&
      (value.startsWith('http') || value.startsWith('data:'))
    ) {
      return value;
    }

    return '';
  }

  onMediaLoaded(value: any): void {
    const key = this.getKeyFromValue(value);
    if (key) {
      this.loadedMedia.add(key);
    }
  }

  navigateToGallery(value: any): void {
    // Only generated media items have a gallery route; uploaded source
    // assets (`asset:` keys) share the ID space with nothing in /gallery.
    const key = this.getKeyFromValue(value);
    if (!key?.startsWith(MEDIA_KEY_PREFIX) || !this.mediaUrlMap.has(key)) {
      return;
    }
    const id = key.slice(MEDIA_KEY_PREFIX.length);
    const urlTree = this.router.createUrlTree(['/gallery', id]);
    const url = this.router.serializeUrl(urlTree);
    window.open(url, '_blank');
  }

  private getKeyFromValue(value: any): string | null {
    if (
      typeof value === 'number' ||
      (typeof value === 'string' && /^\d+$/.test(value))
    ) {
      return `${MEDIA_KEY_PREFIX}${value}`;
    } else if (value && typeof value === 'object') {
      const assetId = value.sourceAssetId ?? value.source_asset_id;
      if (assetId) {
        return `${ASSET_KEY_PREFIX}${assetId}`;
      } else if (value.sourceMediaItem?.mediaItemId) {
        return `${MEDIA_KEY_PREFIX}${value.sourceMediaItem.mediaItemId}`;
      }
    }
    return null;
  }

  isLoaded(value: any): boolean {
    const key = this.getKeyFromValue(value);
    return key ? this.loadedMedia.has(key) : false;
  }

  isArray(val: any): boolean {
    return Array.isArray(val);
  }

  getResolvedValues(val: any): any[] {
    if (Array.isArray(val)) {
      return val.flatMap(v => this.getResolvedValues(v));
    } else if (val && typeof val === 'object' && val._resolvedValue) {
      return this.getResolvedValues(val._resolvedValue);
    }
    return [val];
  }

  getStepConfig() {
    return (STEP_CONFIGS_MAP as any)[this.stepType];
  }

  isImageInput(inputName: any): boolean {
    if (this.isImageStep()) {
      return String(inputName) !== 'prompt';
    }
    const config = this.getStepConfig();
    if (!config) return false;
    const input = config.inputs?.find((i: any) => i.name === String(inputName));
    return input?.type === 'image';
  }

  /** Loop folder-mode items render as media of the configured `item_type`. */
  private isLoopMediaOutput(
    outputName: unknown,
    mediaType: LoopItemType,
  ): boolean {
    return (
      String(outputName) === LOOP_ITEMS_KEY &&
      this.loopMediaType() === mediaType
    );
  }

  isImageOutput(outputName?: any): boolean {
    if (this.isLoopStep()) {
      return this.isLoopMediaOutput(outputName, 'image');
    }
    if (this.isImageStep()) {
      return true;
    }
    const config = this.getStepConfig();
    if (!config) {
      if (outputName && this.outputs) {
        const val = this.outputs[outputName];
        if (
          val &&
          typeof val === 'object' &&
          (val.previewUrl || val.sourceAssetId || val.sourceMediaItem)
        ) {
          if (!this.isVideoOutput(outputName)) {
            return true;
          }
        }
      }
      return false;
    }

    if (outputName) {
      const output = config.outputs?.find(
        (o: any) => o.name === String(outputName),
      );
      return output?.type === 'image';
    }

    return config.outputs?.some((o: any) => o.type === 'image') || false;
  }

  isTextOutput(outputName?: any): boolean {
    const config = this.getStepConfig();
    if (!config) {
      return (
        !this.isImageOutput(outputName) &&
        !this.isVideoOutput(outputName) &&
        !this.isAudioOutput(outputName)
      );
    }

    if (outputName) {
      const output = config.outputs?.find(
        (o: any) => o.name === String(outputName),
      );
      return output?.type === 'text';
    }
    return config.outputs?.some((o: any) => o.type === 'text') || false;
  }

  isVideoOutput(outputName?: any): boolean {
    if (this.isLoopStep()) {
      return this.isLoopMediaOutput(outputName, 'video');
    }
    const config = this.getStepConfig();
    if (!config) {
      if (outputName && this.outputs) {
        const val = this.outputs[outputName];
        if (
          val &&
          typeof val === 'object' &&
          ((val.previewUrl && isVideoUrl(val.previewUrl)) ||
            val.sourceMediaItem?.role === 'reference_video')
        ) {
          return true;
        }
      }
      return false;
    }

    if (outputName) {
      const output = config.outputs?.find(
        (o: any) => o.name === String(outputName),
      );
      return output?.type === 'video';
    }
    return config.outputs?.some((o: any) => o.type === 'video') || false;
  }

  isAudioOutput(outputName?: any): boolean {
    if (this.isLoopStep()) {
      return this.isLoopMediaOutput(outputName, 'audio');
    }
    const config = this.getStepConfig();
    if (!config) return false;

    if (outputName) {
      const output = config.outputs?.find(
        (o: any) => o.name === String(outputName),
      );
      return output?.type === 'audio';
    }
    return config.outputs?.some((o: any) => o.type === 'audio') || false;
  }

  isVideoInput(inputName: any): boolean {
    const config = this.getStepConfig();
    if (!config) return false;
    const input = config.inputs?.find((i: any) => i.name === String(inputName));
    return input?.type === 'video';
  }

  isAudioInput(inputName: any): boolean {
    const config = this.getStepConfig();
    if (!config) return false;
    const input = config.inputs?.find((i: any) => i.name === String(inputName));
    return input?.type === 'audio';
  }

  get inputCount(): number {
    return Object.keys(this.filteredInputs).length;
  }

  get outputCount(): number {
    return Object.keys(this.filteredOutputs).length;
  }

  trackByKey = (index: number, item: any): string => {
    return item?.key || index.toString();
  };

  trackByMedia = (index: number, item: any): any => {
    if (item === null || item === undefined) return index;
    const key = this.getKeyFromValue(item);
    if (key) return key;
    if (typeof item === 'object' && item.previewUrl) return item.previewUrl;
    if (typeof item === 'string' || typeof item === 'number') return item;
    return index;
  };

  formatDisplayValue(value: any): string {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') {
      return String(value);
    }
    return JSON.stringify(value, null, 2);
  }
}
