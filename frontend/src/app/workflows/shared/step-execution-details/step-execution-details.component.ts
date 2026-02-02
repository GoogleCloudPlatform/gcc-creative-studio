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

import { Component, Input, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { NodeTypes } from '../../workflow.models';
import { STEP_CONFIGS_MAP } from '../step-configs.map';

@Component({
  selector: 'app-step-execution-details',
  templateUrl: './step-execution-details.component.html',
  styleUrls: ['./step-execution-details.component.scss']
})
export class StepExecutionDetailsComponent implements OnInit {
  @Input() stepId: string = '';
  @Input() stepType: string = '';
  @Input() inputs: any = {};
  @Input() outputs: any = {};
  @Input() mediaUrlMap: Map<string, string> = new Map();

  loadedMedia = new Set<string>();
  NodeTypes = NodeTypes;


  constructor(private router: Router) { }

  ngOnInit(): void {
  }

  getMediaUrl(value: any): string {
    const key = this.getKeyFromValue(value);
    if (key && this.mediaUrlMap.has(key)) {
      return this.mediaUrlMap.get(key)!;
    }

    if (value && typeof value === 'object' && value.previewUrl) {
      return value.previewUrl;
    } else if (typeof value === 'string' && (value.startsWith('http') || value.startsWith('data:'))) {
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
      const id = value.sourceAssetId ?? value.source_asset_id ?? value.sourceMediaItem?.mediaItemId;
      return (id !== undefined && id !== null) ? id : null;
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
    const config = this.getStepConfig();
    if (!config) return false;
    const input = config.inputs.find((i: any) => i.name === String(inputName));
    return input?.type === 'image';
  }

  isImageOutput(outputName?: any): boolean {
    const config = this.getStepConfig();
    if (!config) return false;

    if (outputName) {
      const output = config.outputs.find((o: any) => o.name === String(outputName));
      return output?.type === 'image';
    }

    return config.outputs.some((o: any) => o.type === 'image');
  }

  isTextOutput(outputName?: any): boolean {
    const config = this.getStepConfig();
    if (!config) return false;

    if (outputName) {
      const output = config.outputs.find((o: any) => o.name === String(outputName));
      return output?.type === 'text';
    }
    return config.outputs.some((o: any) => o.type === 'text');
  }

  isVideoOutput(outputName?: any): boolean {
    const config = this.getStepConfig();
    if (!config) return false;

    if (outputName) {
      const output = config.outputs.find((o: any) => o.name === String(outputName));
      return output?.type === 'video';
    }
    return config.outputs.some((o: any) => o.type === 'video');
  }

  isAudioOutput(outputName?: any): boolean {
    const config = this.getStepConfig();
    if (!config) return false;

    if (outputName) {
      const output = config.outputs.find((o: any) => o.name === String(outputName));
      return output?.type === 'audio';
    }
    return config.outputs.some((o: any) => o.type === 'audio');
  }

  isVideoInput(inputName: any): boolean {
    const config = this.getStepConfig();
    if (!config) return false;
    const input = config.inputs.find((i: any) => i.name === String(inputName));
    return input?.type === 'video';
  }

  isAudioInput(inputName: any): boolean {
    const config = this.getStepConfig();
    if (!config) return false;
    const input = config.inputs.find((i: any) => i.name === String(inputName));
    return input?.type === 'audio';
  }

  get inputCount(): number {
    return this.inputs ? Object.keys(this.inputs).length : 0;
  }

  get outputCount(): number {
    return this.outputs ? Object.keys(this.outputs).length : 0;
  }
}
