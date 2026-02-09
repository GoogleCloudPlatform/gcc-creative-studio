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

import { Injectable } from '@angular/core';
import { forkJoin, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { SourceAssetService } from '../../common/services/source-asset.service';
import { GalleryService } from '../../gallery/gallery.service';
import { NodeTypes } from '../workflow.models';
import { STEP_CONFIGS_MAP } from './step-configs.map';

@Injectable({
  providedIn: 'root'
})
export class MediaResolutionService {

  constructor(
    private galleryService: GalleryService,
    private sourceAssetService: SourceAssetService
  ) { }

  /**
   * Resolves media URLs for the given step entries.
   * @param stepEntries The execution details step entries.
   * @param stepTypeMap A map of stepId -> stepType (NodeTypes | string).
   * @param mediaUrlMap The map to populate with resolved URLs (key format: "type:id").
   */
  resolveMediaUrls(stepEntries: any[], stepTypeMap: Map<string, NodeTypes | string>, mediaUrlMap: Map<string, string>): void {
    if (!stepEntries) return;

    const mediaItemIds = new Set<string | number>();
    const sourceAssetIds = new Set<string | number>();

    // Create a map of step outputs for reference resolution
    const stepOutputsMap = new Map<string, any>();
    stepEntries.forEach(step => {
      stepOutputsMap.set(step.step_id, step.step_outputs);
    });

    stepEntries.forEach((step: any) => {
      const type = stepTypeMap.get(step.step_id);
      if (!type) return;

      const config = STEP_CONFIGS_MAP[type as keyof typeof STEP_CONFIGS_MAP];
      if (!config) return;

      // Helper to process inputs/outputs
      const processIO = (ioConfig: any[], sourceData: any) => {
        if (!sourceData) return;
        ioConfig.forEach(item => {
          if (['image', 'audio', 'video'].includes(item.type)) {
            this.collectMediaIds(sourceData[item.name], mediaItemIds, sourceAssetIds, stepOutputsMap);
          }
        });
      };

      if (config.outputs) processIO(config.outputs, step.step_outputs);
      if (config.inputs) processIO(config.inputs, step.step_inputs);
    });

    // Filter out already resolved IDs using namespaced keys
    const mediaIdsToFetch = Array.from(mediaItemIds).filter(id => !mediaUrlMap.has(`media:${id}`));
    const sourceIdsToFetch = Array.from(sourceAssetIds).filter(id => !mediaUrlMap.has(`asset:${id}`));

    if (mediaIdsToFetch.length === 0 && sourceIdsToFetch.length === 0) return;

    const requests = [
      ...mediaIdsToFetch.map(id =>
        this.galleryService.getMedia(id as number).pipe(
          map(mediaItem => ({ key: `media:${id}`, url: mediaItem.presignedUrls?.[0] })),
          catchError(err => {
            console.error(`Failed to resolve media ID ${id}`, err);
            return of(null);
          })
        )
      ),
      ...sourceIdsToFetch.map(id =>
        this.sourceAssetService.getAsset(id as any).pipe(
          map(asset => ({ key: `asset:${id}`, url: asset.presignedUrl })),
          catchError(err => {
            console.error(`Failed to resolve source asset ID ${id}`, err);
            return of(null);
          })
        )
      )
    ];

    // Execute all requests in parallel
    forkJoin(requests).subscribe(results => {
      results.forEach(result => {
        if (result && result.url) {
          mediaUrlMap.set(result.key, result.url);
        }
      });
    });
  }

  private collectMediaIds(val: any, mediaItemIds: Set<string | number>, sourceAssetIds: Set<string | number>, stepOutputsMap: Map<string, any>): void {
    if (!val) return;

    if (typeof val === 'number') {
      mediaItemIds.add(val);
    } else if (Array.isArray(val)) {
      val.forEach(v => this.collectMediaIds(v, mediaItemIds, sourceAssetIds, stepOutputsMap));
    } else if (typeof val === 'object') {
      // Check if it's a reference to another step's output
      if (val.step && val.output) {
        // Resolve reference
        const outputs = stepOutputsMap.get(val.step);
        if (outputs && outputs[val.output] !== undefined) {
          const resolvedValue = outputs[val.output];
          // Attach resolved value to the reference object for UI usage
          val._resolvedValue = resolvedValue;
          // Recurse on the resolved value
          this.collectMediaIds(resolvedValue, mediaItemIds, sourceAssetIds, stepOutputsMap);
        }
      } else {
        const assetId = val.sourceAssetId ?? val.source_asset_id;
        if (assetId) {
          sourceAssetIds.add(assetId);
        } else if (val.sourceMediaItem?.mediaItemId) {
          mediaItemIds.add(val.sourceMediaItem.mediaItemId);
        }
      }
    }
  }
}
