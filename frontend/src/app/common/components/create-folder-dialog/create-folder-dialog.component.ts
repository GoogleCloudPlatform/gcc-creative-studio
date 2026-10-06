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

import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {Folder} from '../../models/folder.model';

export interface CreateFolderDialogData {
  workspaceId: number;
  parentId?: number | null;
  folder?: Folder; // If provided, acts as Rename/Edit mode
  existingFolderNames?: string[];
}

@Component({
  selector: 'app-create-folder-dialog',
  templateUrl: './create-folder-dialog.component.html',
  styleUrls: ['./create-folder-dialog.component.scss'],
})
export class CreateFolderDialogComponent implements OnInit {
  folderName = '';
  selectedColor = '#8AB4F8';
  isEditMode = false;

  readonly colorOptions = [
    '#8AB4F8', // Blue
    '#C58AF9', // Purple
    '#F28B82', // Red/Coral
    '#FDD663', // Amber/Yellow
    '#81C995', // Green
    '#78D9EC', // Cyan
    '#FF8BCB', // Pink
    '#9AA0A6', // Gray
  ];

  constructor(
    public dialogRef: MatDialogRef<CreateFolderDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: CreateFolderDialogData,
  ) {}

  ngOnInit(): void {
    if (this.data.folder) {
      this.isEditMode = true;
      this.folderName = this.data.folder.name;
      this.selectedColor = this.data.folder.color || '#8AB4F8';
    }
  }

  get isDuplicateName(): boolean {
    const trimmed = this.folderName.trim().toLowerCase();
    if (!trimmed) return false;
    if (
      this.isEditMode &&
      this.data.folder &&
      this.data.folder.name.trim().toLowerCase() === trimmed
    ) {
      return false;
    }
    const existing = this.data.existingFolderNames || [];
    return existing.some(name => name.trim().toLowerCase() === trimmed);
  }

  get isValid(): boolean {
    return this.folderName.trim().length > 0 && !this.isDuplicateName;
  }

  save(): void {
    if (!this.isValid) {
      return;
    }
    this.dialogRef.close({
      name: this.folderName.trim(),
      color: this.selectedColor,
    });
  }

  close(): void {
    this.dialogRef.close();
  }
}
