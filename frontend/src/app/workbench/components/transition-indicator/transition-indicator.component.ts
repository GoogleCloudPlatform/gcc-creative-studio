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
  Input,
  Output,
  EventEmitter,
  ViewChild,
  TemplateRef,
  inject,
} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatIconModule} from '@angular/material/icon';
import {MatDialog, MatDialogModule} from '@angular/material/dialog';
import {MatButtonModule} from '@angular/material/button';
import {
  Transition,
  TransitionType,
} from '../../../common/models/workbench.model';

import {SharedModule} from '../../../common/shared.module';

@Component({
  selector: 'app-transition-indicator',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatIconModule,
    MatDialogModule,
    MatButtonModule,
    SharedModule,
  ],
  templateUrl: './transition-indicator.component.html',
  styleUrls: ['./transition-indicator.component.scss'],
})
export class TransitionIndicatorComponent {
  @Input({required: true}) left!: number;
  @Input() transitionIndex?: number;
  @Input() transition: Transition | null = null;
  @Input() role: 'in' | 'out' | 'middle' = 'middle';
  @Output() transitionChange = new EventEmitter<{
    role: 'in' | 'out' | 'middle';
    index?: number;
    type: TransitionType;
    duration_seconds: number;
  }>();

  readonly transitionOptions = [
    {type: TransitionType.NONE, label: 'None', icon: 'swap_horiz'},
    {type: TransitionType.FADE, label: 'Blur', icon: 'blur_on'},
    {
      type: TransitionType.WIPE_LEFT,
      label: 'Wipe Left',
      icon: 'keyboard_double_arrow_left',
    },
    {
      type: TransitionType.WIPE_RIGHT,
      label: 'Wipe Right',
      icon: 'keyboard_double_arrow_right',
    },
  ];

  selectedType: TransitionType = TransitionType.NONE;
  private _durationSeconds = 0;
  get durationSeconds(): number {
    return this._durationSeconds;
  }
  set durationSeconds(value: number) {
    if (value === null || value === undefined || isNaN(value)) {
      this._durationSeconds = value;
      return;
    }
    if (value > 4) {
      this._durationSeconds = 4;
    } else if (value < 0) {
      this._durationSeconds = 0;
    } else {
      this._durationSeconds = value;
    }
  }

  private dialog = inject(MatDialog);
  @ViewChild('transitionModal') transitionModal!: TemplateRef<any>;

  get transitionIcon(): string {
    if (!this.transition) return 'swap_horiz';
    switch (this.transition.type) {
      case TransitionType.FADE:
        return 'blur_on';
      case TransitionType.WIPE_LEFT:
        return 'keyboard_double_arrow_left';
      case TransitionType.WIPE_RIGHT:
        return 'keyboard_double_arrow_right';
      default:
        return 'swap_horiz';
    }
  }

  get hasActiveTransition(): boolean {
    return !!this.transition && this.transition.type !== TransitionType.NONE;
  }

  get hasChanges(): boolean {
    const originalType = this.transition
      ? this.transition.type
      : TransitionType.NONE;
    const originalDuration = this.transition
      ? this.transition.duration_seconds
      : 0;
    return (
      this.selectedType !== originalType ||
      this.durationSeconds !== originalDuration
    );
  }

  get isSaveDisabled(): boolean {
    if (!this.hasChanges) {
      return true;
    }
    if (this.selectedType !== TransitionType.NONE) {
      const val = Number(this.durationSeconds);
      return !this.durationSeconds || val <= 0 || val > 4;
    }
    return false;
  }

  selectType(type: TransitionType) {
    this.selectedType = type;
  }

  saveTransition() {
    this.transitionChange.emit({
      role: this.role,
      index: this.role === 'middle' ? this.transitionIndex : undefined,
      type: this.selectedType,
      duration_seconds:
        this.selectedType === TransitionType.NONE ? 0 : this.durationSeconds,
    });
  }

  openModal() {
    this.selectedType = this.transition
      ? this.transition.type
      : TransitionType.NONE;
    this.durationSeconds = this.transition
      ? this.transition.duration_seconds
      : 0;

    this.dialog.open(this.transitionModal, {
      width: '350px',
      panelClass: 'transition-dialog-panel',
    });
  }
}
