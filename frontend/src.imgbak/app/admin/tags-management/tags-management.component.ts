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

import {Component, OnInit, ViewChild} from '@angular/core';
import {TagsService, TagModel} from '../../common/services/tags.service';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatTableDataSource} from '@angular/material/table';
import {MatPaginator, PageEvent} from '@angular/material/paginator';

@Component({
  selector: 'app-tags-management',
  templateUrl: './tags-management.component.html',
  styleUrls: ['./tags-management.component.scss'],
})
export class TagsManagementComponent implements OnInit {
  dataSource = new MatTableDataSource<TagModel>();
  displayedColumns: string[] = ['id', 'name', 'color', 'actions'];
  newTagName = '';
  isLoading = false;
  editingTagId: number | null = null;
  editName = '';
  editColor = '';

  // Pagination
  totalItems = 0;
  limit = 10;
  currentPageIndex = 0;

  @ViewChild(MatPaginator) paginator!: MatPaginator;

  constructor(
    private tagsService: TagsService,
    private workspaceStateService: WorkspaceStateService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.loadTags();
  }

  loadTags(targetPageIndex = 0): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId) {
      this.isLoading = true;
      this.tagsService
        .getTags(workspaceId, undefined, targetPageIndex + 1, this.limit)
        .subscribe({
          next: response => {
            this.dataSource.data = response.data;
            this.totalItems = response.count;
            this.currentPageIndex = targetPageIndex;
            this.isLoading = false;
          },
          error: err => {
            console.error('Failed to load tags', err);
            this.snackBar.open('Failed to load tags', 'Close', {
              duration: 3000,
            });
            this.isLoading = false;
          },
        });
    }
  }

  handlePageEvent(event: PageEvent) {
    if (this.limit !== event.pageSize) {
      this.limit = event.pageSize;
      this.currentPageIndex = 0;
      if (this.paginator) {
        this.paginator.pageIndex = 0;
      }
    }
    this.loadTags(event.pageIndex);
  }

  createTag(): void {
    if (!this.newTagName.trim()) return;
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId) {
      this.tagsService
        .createTag(workspaceId, this.newTagName.trim())
        .subscribe({
          next: () => {
            this.newTagName = '';
            this.snackBar.open('Tag created successfully', 'Close', {
              duration: 3000,
            });
            this.loadTags(this.currentPageIndex); // Reload current page
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
    this.editColor = tag.color || '#E8EAED';
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

  deleteTag(tagId: number): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId) {
      this.tagsService.deleteTag(workspaceId, tagId).subscribe({
        next: () => {
          this.snackBar.open('Tag deleted successfully', 'Close', {
            duration: 3000,
          });
          this.loadTags(this.currentPageIndex); // Reload current page
        },
        error: err => {
          console.error('Failed to delete tag', err);
          this.snackBar.open('Failed to delete tag', 'Close', {duration: 3000});
        },
      });
    }
  }
}
