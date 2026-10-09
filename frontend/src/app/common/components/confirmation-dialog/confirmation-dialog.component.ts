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

import {Component, Inject} from '@angular/core';
import {MatDialogRef, MAT_DIALOG_DATA} from '@angular/material/dialog';
import {MatButtonModule} from '@angular/material/button';
import {MatDialogModule} from '@angular/material/dialog'; // Import MatDialogModule

/** Material palette used for the confirm button. */
export type ConfirmationDialogColor = 'primary' | 'accent' | 'warn';

export const DEFAULT_CONFIRM_LABEL = 'Delete';
export const DEFAULT_CONFIRM_COLOR: ConfirmationDialogColor = 'warn';
export const DEFAULT_CANCEL_LABEL = 'Cancel';

export interface ConfirmationDialogData {
  title: string;
  message: string;
  /** Confirm button text. Defaults to "Delete". */
  confirmLabel?: string;
  /** Confirm button colour. Defaults to "warn". */
  confirmColor?: ConfirmationDialogColor;
  /** Cancel button text. Defaults to "Cancel". */
  cancelLabel?: string;
}

@Component({
  selector: 'app-confirmation-dialog',
  templateUrl: './confirmation-dialog.component.html',
  styleUrl: './confirmation-dialog.component.scss',
})
export class ConfirmationDialogComponent {
  readonly confirmLabel: string;
  readonly confirmColor: ConfirmationDialogColor;
  readonly cancelLabel: string;

  constructor(
    public dialogRef: MatDialogRef<ConfirmationDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: ConfirmationDialogData,
  ) {
    this.confirmLabel = data?.confirmLabel ?? DEFAULT_CONFIRM_LABEL;
    this.confirmColor = data?.confirmColor ?? DEFAULT_CONFIRM_COLOR;
    this.cancelLabel = data?.cancelLabel ?? DEFAULT_CANCEL_LABEL;
  }

  onConfirm(): void {
    this.dialogRef.close(true);
  }

  onDismiss(): void {
    this.dialogRef.close(false);
  }
}
