import { Component, Input, Output, EventEmitter, ViewChild, TemplateRef, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { Transition, TransitionType } from '../../../common/models/workbench.model';

@Component({
  selector: 'app-transition-indicator',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule, MatDialogModule, MatButtonModule],
  templateUrl: './transition-indicator.component.html',
  styleUrls: ['./transition-indicator.component.scss']
})
export class TransitionIndicatorComponent {
  @Input({ required: true }) left!: number;
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
    { type: TransitionType.NONE, label: 'None', icon: 'swap_horiz' },
    { type: TransitionType.FADE, label: 'Blur', icon: 'blur_on' },
    { type: TransitionType.WIPE_LEFT, label: 'Wipe Left', icon: 'keyboard_double_arrow_left' },
    { type: TransitionType.WIPE_RIGHT, label: 'Wipe Right', icon: 'keyboard_double_arrow_right' },
  ];

  selectedType: TransitionType = TransitionType.NONE;
  durationSeconds = 0;

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
    const originalType = this.transition ? this.transition.type : TransitionType.NONE;
    const originalDuration = this.transition ? this.transition.duration_seconds : 0;
    return this.selectedType !== originalType || this.durationSeconds !== originalDuration;
  }

  selectType(type: TransitionType) {
    this.selectedType = type;
  }

  saveTransition() {
    this.transitionChange.emit({
      role: this.role,
      index: this.role === 'middle' ? this.transitionIndex : undefined,
      type: this.selectedType,
      duration_seconds: this.selectedType === TransitionType.NONE ? 0 : this.durationSeconds
    });
  }

  openModal() {
    this.selectedType = this.transition ? this.transition.type : TransitionType.NONE;
    this.durationSeconds = this.transition ? this.transition.duration_seconds : 0;

    this.dialog.open(this.transitionModal, {
      width: '350px',
      panelClass: 'transition-dialog-panel'
    });
  }
}
