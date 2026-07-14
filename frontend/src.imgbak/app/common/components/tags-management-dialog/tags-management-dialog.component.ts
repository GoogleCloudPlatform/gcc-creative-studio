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

import {Component, OnInit, Inject} from '@angular/core';
import {MatDialogRef, MAT_DIALOG_DATA} from '@angular/material/dialog';
import {TagsService, TagModel} from '../../services/tags.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {MatSnackBar} from '@angular/material/snack-bar';
import {UserService} from '../../../common/services/user.service';

@Component({
  selector: 'app-tags-management-dialog',
  templateUrl: './tags-management-dialog.component.html',
  styleUrl: './tags-management-dialog.component.scss',
})
export class TagsManagementDialogComponent implements OnInit {
  tags: TagModel[] = [];
  isLoading = false;
  editingTagId: number | null = null;
  editName = '';
  editColor = '';
  newTagName = '';

  // Search and Pagination
  searchQuery = '';
  pageSize = 10;
  currentPage = 1;
  totalTags = 0;
  onlyMyTags = true;
  userId: number | undefined;

  constructor(
    public dialogRef: MatDialogRef<TagsManagementDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: any,
    private tagsService: TagsService,
    private workspaceStateService: WorkspaceStateService,
    private snackBar: MatSnackBar,
    private userService: UserService,
  ) {
    const user = this.userService.getUserDetails();
    this.userId = user?.id as number;
  }

  ngOnInit(): void {
    this.loadTags();
  }

  get displayedTags(): TagModel[] {
    return this.tags;
  }

  loadTags(): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId) {
      this.isLoading = true;
      const filterUserId = this.onlyMyTags ? this.userId : undefined;
      this.tagsService
        .getTags(
          workspaceId,
          this.searchQuery,
          this.currentPage,
          this.pageSize,
          filterUserId,
        )
        .subscribe({
          next: response => {
            if (this.currentPage === 1) {
              this.tags = response.data;
            } else {
              this.tags = [...this.tags, ...response.data];
            }
            this.totalTags = response.count;
            this.isLoading = false;
          },
          error: () => {
            this.isLoading = false;
            this.snackBar.open('Failed to load tags.', 'Close', {
              duration: 3000,
            });
          },
        });
    }
  }

  toggleOnlyMyTags(checked: boolean): void {
    this.onlyMyTags = checked;
    this.currentPage = 1; // Reset pagination
    this.loadTags();
  }

  onSearch(): void {
    this.currentPage = 1; // Reset pagination on search
    this.loadTags();
  }

  loadMore(): void {
    this.currentPage++;
    this.loadTags();
  }

  createTag(): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId && this.newTagName.trim()) {
      this.tagsService.createTag(workspaceId, this.newTagName).subscribe({
        next: tag => {
          this.tags.push(tag);
          this.newTagName = '';
          this.snackBar.open('Tag created successfully', 'Close', {
            duration: 3000,
          });
          this.totalTags++;
        },
        error: err => {
          console.error('Failed to create tag', err);
          this.snackBar.open('Failed to create tag', 'Close', {
            duration: 3000,
          });
        },
      });
    }
  }

  startEdit(tag: TagModel): void {
    this.editingTagId = tag.id;
    this.editName = tag.name;
    this.editColor = tag.color || '#1D8DF8';
  }

  cancelEdit(): void {
    this.editingTagId = null;
    this.editName = '';
    this.editColor = '';
  }

  saveEdit(tag: TagModel): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId && this.editName.trim()) {
      this.tagsService
        .updateTag(workspaceId, tag.id, this.editName, this.editColor)
        .subscribe({
          next: () => {
            this.snackBar.open(`Tag "${this.editName}" updated.`, 'Close', {
              duration: 3000,
            });
            this.editingTagId = null;
            this.currentPage = 1; // Reset to reload from first page!
            this.loadTags();
          },
          error: () => {
            this.snackBar.open('Failed to update tag.', 'Close', {
              duration: 3000,
            });
          },
        });
    }
  }

  deleteTag(tag: TagModel): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId) {
      this.tagsService.deleteTag(workspaceId, tag.id).subscribe({
        next: () => {
          this.snackBar.open(`Tag "${tag.name}" deleted.`, 'Close', {
            duration: 3000,
          });
          this.currentPage = 1; // Reset to reload from first page!
          this.loadTags();
        },
        error: () => {
          this.snackBar.open('Failed to delete tag.', 'Close', {
            duration: 3000,
          });
        },
      });
    }
  }

  close(): void {
    this.dialogRef.close();
  }
}
