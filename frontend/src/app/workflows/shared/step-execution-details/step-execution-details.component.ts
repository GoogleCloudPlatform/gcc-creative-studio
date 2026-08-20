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

import {Component, Input, OnInit} from '@angular/core';
import {Router} from '@angular/router';
import {NodeTypes} from '../../workflow.models';
import {IMAGE_MODE_ALLOWED_INPUTS} from '../../workflow-editor/step-components/step-configs/image-step.config';
import {STEP_CONFIGS_MAP} from '../step-configs.map';

@Component({
  selector: 'app-step-execution-details',
  templateUrl: './step-execution-details.component.html',
  styleUrls: ['./step-execution-details.component.scss'],
})
export class StepExecutionDetailsComponent implements OnInit {
  @Input() stepId = '';
  @Input() stepType = '';
  @Input() inputs: any = {};
  @Input() outputs: any = {};
  @Input() mediaUrlMap: Map<string, string> = new Map();
  @Input() mode?: string;

  loadedMedia = new Set<string>();
  NodeTypes = NodeTypes;

  constructor(private router: Router) {}

  ngOnInit(): void {}

  private isImageStep(): boolean {
    return (
      this.stepType === NodeTypes.IMAGE ||
      this.stepType === NodeTypes.GENERATE_IMAGE ||
      this.stepType === NodeTypes.EDIT_IMAGE ||
      this.stepType === NodeTypes.UPSCALE_IMAGE ||
      this.stepType === NodeTypes.VIRTUAL_TRY_ON
    );
  }

  private getActiveImageMode(): string {
    if (this.mode) {
      return this.mode;
    }
    if (
      [
        NodeTypes.EDIT_IMAGE,
        NodeTypes.UPSCALE_IMAGE,
        NodeTypes.VIRTUAL_TRY_ON,
      ].includes(this.stepType as NodeTypes)
    ) {
      return this.stepType;
    }
    return 'generate_image';
  }

  private hasValue(value: any): boolean {
    if (value === null || value === undefined || value === '') return false;
    if (Array.isArray(value) && value.length === 0) return false;
    return true;
  }

  get filteredInputs(): Record<string, any> {
    if (!this.inputs || typeof this.inputs !== 'object') return {};

    const result: Record<string, any> = {};

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
    const id = this.getIdFromValue(value);
    if (!id) return;

    // Use getKeyFromValue to check if we have it loaded, but navigation only works for Media Items currently
    // If it's an asset, we might not have a gallery route for it yet, or we assume it's media.
    // For now assuming ID is enough if it's in the map.
    const key = this.getKeyFromValue(value);
    if (key && this.mediaUrlMap.has(key)) {
      // Only navigate if it's a media item (heuristic: if key starts with media:)
      // Or just try to navigate if we have an ID.
      const urlTree = this.router.createUrlTree(['/gallery', id]);
      const url = this.router.serializeUrl(urlTree);
      window.open(url, '_blank');
    }
  }

  private getKeyFromValue(value: any): string | null {
    if (typeof value === 'number') {
      return `media:${value}`;
    } else if (value && typeof value === 'object') {
      const assetId = value.sourceAssetId ?? value.source_asset_id;
      if (assetId) {
        return `asset:${assetId}`;
      } else if (value.sourceMediaItem?.mediaItemId) {
        return `media:${value.sourceMediaItem.mediaItemId}`;
      }
    }
    return null;
  }

  private getIdFromValue(value: any): number | string | null {
    if (typeof value === 'number') {
      return value;
    } else if (value && typeof value === 'object') {
      const id =
        value.sourceAssetId ??
        value.source_asset_id ??
        value.sourceMediaItem?.mediaItemId;
      return id !== undefined && id !== null ? id : null;
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

  isImageOutput(outputName?: any): boolean {
    if (this.isImageStep()) {
      return true;
    }
    const config = this.getStepConfig();
    if (!config) return false;

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
    if (!config) return false;

    if (outputName) {
      const output = config.outputs?.find(
        (o: any) => o.name === String(outputName),
      );
      return output?.type === 'text';
    }
    return config.outputs?.some((o: any) => o.type === 'text') || false;
  }

  isVideoOutput(outputName?: any): boolean {
    const config = this.getStepConfig();
    if (!config) return false;

    if (outputName) {
      const output = config.outputs?.find(
        (o: any) => o.name === String(outputName),
      );
      return output?.type === 'video';
    }
    return config.outputs?.some((o: any) => o.type === 'video') || false;
  }

  isAudioOutput(outputName?: any): boolean {
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
}
