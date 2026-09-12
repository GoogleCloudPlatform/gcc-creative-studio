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

import {Component, Inject, signal} from '@angular/core';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';

export interface SaveTemplateDialogData {
  defaultName?: string;
  defaultDescription?: string;
}

export interface SaveTemplateDialogResult {
  name: string;
  description: string;
}

@Component({
  selector: 'app-save-template-modal',
  templateUrl: './save-template-modal.component.html',
  styleUrls: ['./save-template-modal.component.scss'],
})
export class SaveTemplateModalComponent {
  readonly templateForm: FormGroup;
  readonly isSubmitting = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);

  constructor(
    private fb: FormBuilder,
    public dialogRef: MatDialogRef<
      SaveTemplateModalComponent,
      SaveTemplateDialogResult | null
    >,
    @Inject(MAT_DIALOG_DATA) public data: SaveTemplateDialogData | null,
  ) {
    this.templateForm = this.fb.group({
      name: [
        data?.defaultName ? `${data.defaultName} Template` : '',
        [
          Validators.required,
          Validators.minLength(2),
          Validators.maxLength(100),
        ],
      ],
      description: [
        data?.defaultDescription || '',
        [Validators.maxLength(500)],
      ],
    });
  }

  get isFormInvalid(): boolean {
    return this.templateForm.invalid;
  }

  onSave(): void {
    if (this.templateForm.invalid) {
      this.templateForm.markAllAsTouched();
      return;
    }

    const raw = this.templateForm.getRawValue();
    const result: SaveTemplateDialogResult = {
      name: (raw.name as string).trim(),
      description: ((raw.description as string) || '').trim(),
    };

    this.dialogRef.close(result);
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }
}
