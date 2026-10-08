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

import {Component, Inject, Signal} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {StepEntry} from '../../workflow.models';
import {StepHistorySidebarDialogData} from './step-history-sidebar.models';

/**
 * Hosts {@link StepHistorySidebarComponent} inside a CDK overlay so it can be
 * stacked above other dialogs (e.g. the execution details modal).
 */
@Component({
  selector: 'app-step-history-sidebar-dialog',
  templateUrl: './step-history-sidebar-dialog.component.html',
  styles: [':host { display: block; height: 100%; }'],
})
export class StepHistorySidebarDialogComponent {
  /** Live entry of the inspected step. */
  readonly entry: Signal<StepEntry | null>;

  constructor(
    private dialogRef: MatDialogRef<StepHistorySidebarDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: StepHistorySidebarDialogData,
  ) {
    this.entry = data.entry;
  }

  close(): void {
    this.dialogRef.close();
  }
}
