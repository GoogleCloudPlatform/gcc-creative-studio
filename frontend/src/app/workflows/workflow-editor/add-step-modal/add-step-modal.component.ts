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

import { Component } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';

// Defines the UI for each button in the palette
interface StepTypeOption {
  type: string; // The ID, e.g., 'generate_image'
  label: string;
  description: string;
  icon: string; // Material Icon name
  disabled?: boolean;
}

@Component({
  selector: 'app-add-step-modal',
  templateUrl: './add-step-modal.component.html',
  styleUrls: ['./add-step-modal.component.scss']
})
export class AddStepModalComponent {

  // This list drives the UI. Add/remove items here to change the palette.
  stepTypes: StepTypeOption[] = [
    {
      type: 'generate_text',
      label: 'Generate Text',
      description: 'Generates text content using a large language model.',
      icon: 'description'
    },
    {
      type: 'generate_image',
      label: 'Generate Image',
      description: 'Generates an image from a text prompt.',
      icon: 'image'
    },
    {
      type: 'edit_image',
      label: 'Edit Image',
      description: 'Modifies an image using an editing or inpainting model.',
      icon: 'edit'
    },
    {
      type: 'virtual_try_on',
      label: 'Virtual Try-On',
      description: 'Applies a garment to a model image.',
      icon: 'checkroom'
    },
    {
      type: 'generate_video',
      label: 'Generate Video',
      description: 'Generates a video clip from a prompt or image.',
      icon: 'movie',
    },
    {
      type: 'generate_audio',
      label: 'Generate Audio',
      description: 'Generates audio (music or speech) from a text prompt.',
      icon: 'music_note',
    }
  ];

  constructor(
    public dialogRef: MatDialogRef<AddStepModalComponent>
  ) { }

  /**
   * Closes the dialog and returns the selected step type (e.g., 'generate_image')
   * to the component that opened it.
   */
  selectStep(type: string): void {
    this.dialogRef.close(type);
  }

  closeModal(): void {
    this.dialogRef.close(); // Close without returning any value
  }
}
