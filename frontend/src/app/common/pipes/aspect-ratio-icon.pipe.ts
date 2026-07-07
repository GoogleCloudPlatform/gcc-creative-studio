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

import {Pipe, PipeTransform} from '@angular/core';

@Pipe({
  name: 'aspectRatioIcon',
  standalone: true,
})
export class AspectRatioIconPipe implements PipeTransform {
  transform(aspectRatio: string | undefined | null): string {
    if (!aspectRatio) return 'crop_portrait';
    const ratio = aspectRatio.toLowerCase();
    if (ratio === 'auto') return 'aspect_ratio';
    if (ratio.includes(':')) {
      const parts = ratio.split(':');
      const w = parseFloat(parts[0]);
      const h = parseFloat(parts[1]);
      if (!isNaN(w) && !isNaN(h)) {
        if (w > h) return 'crop_landscape';
        if (w === h) return 'crop_square';
        return 'crop_portrait';
      }
    }
    if (
      ratio.includes('landscape') ||
      ratio.includes('horizontal') ||
      ratio.includes('wide') ||
      ratio.includes('pin') ||
      ratio.includes('banner')
    ) {
      return 'crop_landscape';
    }
    if (ratio.includes('square')) {
      return 'crop_square';
    }
    return 'crop_portrait';
  }
}
