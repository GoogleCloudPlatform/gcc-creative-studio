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

import {Component, Input, Output, EventEmitter} from '@angular/core';

@Component({
  selector: 'studio-toolbar-button',
  template: `
    <button
      mat-button
      class="glass-toolbar-btn"
      [class.active]="active"
      [disabled]="disabled"
      (click)="onClick.emit($event)"
    >
      <ng-content></ng-content>
    </button>
  `,
  styleUrls: ['./studio-toolbar-button.component.scss'],
})
export class StudioToolbarButtonComponent {
  @Input() active = false;
  @Input() disabled = false;
  @Output() onClick = new EventEmitter<MouseEvent>();
}
