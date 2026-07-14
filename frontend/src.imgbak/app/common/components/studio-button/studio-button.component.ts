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

import {Component, Input} from '@angular/core';

@Component({
  selector: 'studio-button',
  templateUrl: './studio-button.component.html',
  styleUrls: ['./studio-button.component.scss'],
})
export class StudioButtonComponent {
  @Input() variant: 'primary' | 'cta' = 'primary';
  @Input() shape: 'pill' | 'circle' = 'pill';
  @Input() size: 'small' | 'medium' | 'large' | 'none' = 'none';
  @Input() disabled = false;

  get classes(): string {
    const classList = [];

    if (this.variant === 'cta') {
      classList.push('btn-cta');
    } else {
      classList.push('btn-glass-primary');
    }

    if (this.shape === 'circle') {
      classList.push('btn-glass-circle');
    }

    if (this.size !== 'none') {
      classList.push(`btn-${this.size}`);
    }

    return classList.join(' ');
  }
}
