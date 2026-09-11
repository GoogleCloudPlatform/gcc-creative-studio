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

import {Component, Inject} from '@angular/core';
import {MatDialogRef, MAT_DIALOG_DATA} from '@angular/material/dialog';
import {ConflictStrategy} from '../../models/folder.model';

export type FolderConflictChoice = ConflictStrategy | 'stop';

export interface FolderConflictDialogData {
  folderNames: string[];
  destinationName: string;
  isMove?: boolean;
}

@Component({
  selector: 'app-folder-conflict-dialog',
  templateUrl: './folder-conflict-dialog.component.html',
  styleUrls: ['./folder-conflict-dialog.component.scss'],
})
export class FolderConflictDialogComponent {
  constructor(
    public dialogRef: MatDialogRef<FolderConflictDialogComponent, FolderConflictChoice>,
    @Inject(MAT_DIALOG_DATA) public data: FolderConflictDialogData,
  ) {}

  get title(): string {
    return this.data.folderNames.length > 1
      ? 'Folders already exist'
      : 'Folder already exists';
  }

  get subtitle(): string {
    const dest = this.data.destinationName || 'the destination';
    const action = this.data.isMove ? 'move' : 'copy';
    if (this.data.folderNames.length === 1) {
      return `A folder named "${this.data.folderNames[0]}" already exists in ${dest}. How would you like to resolve this conflict?`;
    }
    return `${this.data.folderNames.length} folders already exist in ${dest}. How would you like to resolve these conflicts?`;
  }

  onKeepBoth(): void {
    this.dialogRef.close('keep_both');
  }

  onMerge(): void {
    this.dialogRef.close('merge');
  }

  onStop(): void {
    this.dialogRef.close('stop');
  }
}
