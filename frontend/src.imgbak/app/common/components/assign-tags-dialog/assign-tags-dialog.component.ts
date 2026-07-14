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

import {Component, Inject, OnInit, HostListener} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {TagsService, TagModel} from '../../services/tags.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {UserService} from '../../../common/services/user.service';

@Component({
  selector: 'app-assign-tags-dialog',
  templateUrl: './assign-tags-dialog.component.html',
  styleUrls: ['./assign-tags-dialog.component.scss'],
})
export class AssignTagsDialogComponent implements OnInit {
  availableTags: TagModel[] = [];
  selectedTags: string[] = [];
  newTagName = '';
  pageSize = 10;
  currentPage = 1;
  totalTags = 0;
  onlyMyTags = true;
  userId: number | undefined;

  get displayedTags(): TagModel[] {
    return this.availableTags;
  }

  constructor(
    public dialogRef: MatDialogRef<AssignTagsDialogComponent>,
    @Inject(MAT_DIALOG_DATA)
    public data: {assetId: number; assetType: string; existingTags: string[]},
    private tagsService: TagsService,
    private workspaceStateService: WorkspaceStateService,
    private userService: UserService,
  ) {
    this.selectedTags = [...(data.existingTags || [])];
    const user = this.userService.getUserDetails();
    this.userId = user?.id as number;
  }

  ngOnInit(): void {
    this.loadTags();
  }

  loadTags(): void {
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (workspaceId) {
      const filterUserId = this.onlyMyTags ? this.userId : undefined;
      this.tagsService
        .getTags(
          workspaceId,
          undefined,
          this.currentPage,
          this.pageSize,
          filterUserId,
        )
        .subscribe(response => {
          if (this.currentPage === 1) {
            this.availableTags = response.data;
          } else {
            this.availableTags = [...this.availableTags, ...response.data];
          }
          this.totalTags = response.count;
        });
    }
  }

  toggleOnlyMyTags(checked: boolean): void {
    this.onlyMyTags = checked;
    this.currentPage = 1; // Reset pagination
    this.loadTags();
  }

  loadMore(): void {
    this.currentPage++;
    this.loadTags();
  }

  toggleTag(tagName: string): void {
    const index = this.selectedTags.indexOf(tagName);
    if (index > -1) {
      this.selectedTags.splice(index, 1);
    } else {
      this.selectedTags.push(tagName);
    }
  }

  isSelected(tagName: string): boolean {
    return this.selectedTags.includes(tagName);
  }

  isNotAvailable(tagName: string): boolean {
    return !this.availableTags.some(t => t.name === tagName);
  }

  addTag(): void {
    if (this.newTagName.trim()) {
      const tagName = this.newTagName.trim();
      if (!this.selectedTags.includes(tagName)) {
        this.selectedTags.push(tagName);
      }
      this.newTagName = '';
    }
  }

  @HostListener('window:keydown.control.enter', ['$event'])
  handleCtrlEnter(event: KeyboardEvent) {
    event.preventDefault();
    this.onSave();
  }

  onSave(): void {
    this.dialogRef.close(this.selectedTags);
  }

  onCancel(): void {
    this.dialogRef.close();
  }
}
