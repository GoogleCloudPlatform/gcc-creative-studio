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

import {Component, DestroyRef, Inject, inject, signal} from '@angular/core';
import {takeUntilDestroyed} from '@angular/core/rxjs-interop';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {handleErrorSnackbar} from '../../../utils/handleMessageSnackbar';
import {
  WorkflowStep,
  WorkflowTemplate,
  WorkflowTemplateCreateDto,
} from '../../workflow.models';
import {WorkflowService} from '../../workflow.service';

export interface SaveTemplateDialogData {
  defaultName?: string;
  defaultDescription?: string;
  steps?: WorkflowStep[];
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

  private destroyRef = inject(DestroyRef);

  constructor(
    private fb: FormBuilder,
    public dialogRef: MatDialogRef<
      SaveTemplateModalComponent,
      WorkflowTemplate | null
    >,
    @Inject(MAT_DIALOG_DATA) public data: SaveTemplateDialogData | null,
    private workflowService: WorkflowService,
    private snackBar: MatSnackBar,
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

    this.templateForm.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        if (this.errorMessage()) {
          this.errorMessage.set(null);
        }
      });
  }

  get isFormInvalid(): boolean {
    return this.templateForm.invalid;
  }

  onSave(): void {
    if (this.templateForm.invalid || this.isSubmitting()) {
      this.templateForm.markAllAsTouched();
      return;
    }

    const raw = this.templateForm.getRawValue();
    const templateDto: WorkflowTemplateCreateDto = {
      name: (raw.name as string).trim(),
      description: ((raw.description as string) || '').trim(),
      steps: this.data?.steps || [],
    };

    this.isSubmitting.set(true);
    this.errorMessage.set(null);
    this.dialogRef.disableClose = true;

    this.workflowService.createTemplate(templateDto).subscribe({
      next: createdTemplate => {
        this.isSubmitting.set(false);
        this.dialogRef.disableClose = false;
        this.dialogRef.close(createdTemplate);
      },
      error: err => {
        this.isSubmitting.set(false);
        this.dialogRef.disableClose = false;
        console.error('Failed to save template', err);
        const errorMsg =
          err.error?.detail ||
          err.error?.message ||
          'Failed to save workflow template.';
        this.errorMessage.set(errorMsg);
        handleErrorSnackbar(
          this.snackBar,
          {message: errorMsg},
          'Save template',
        );
      },
    });
  }

  onCancel(): void {
    if (this.isSubmitting()) {
      return;
    }
    this.dialogRef.close(null);
  }
}
