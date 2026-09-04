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

import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {Workspace, WorkspaceScope} from '../../models/workspace.model';
import {WorkspaceService} from '../../../services/workspace/workspace.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {FlattenedWorkspaceOption} from '../move-to-folder-dialog/move-to-folder-dialog.component';

export interface CopyToWorkspaceDialogData {
  itemCount?: number;
  title?: string;
  subtitle?: string;
}

@Component({
  selector: 'app-copy-to-workspace-dialog',
  templateUrl: './copy-to-workspace-dialog.component.html',
  styleUrls: ['./copy-to-workspace-dialog.component.scss'],
})
export class CopyToWorkspaceDialogComponent implements OnInit {
  workspaces: FlattenedWorkspaceOption[] = [];
  searchQuery = '';
  selectedWorkspaceId: number | null = null;
  isLoading = false;
  currentWorkspaceId: number | null = null;

  constructor(
    public dialogRef: MatDialogRef<CopyToWorkspaceDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: CopyToWorkspaceDialogData,
    private workspaceService: WorkspaceService,
    private workspaceStateService: WorkspaceStateService,
  ) {
    this.currentWorkspaceId = this.workspaceStateService.getActiveWorkspaceId();
  }

  ngOnInit(): void {
    this.loadWorkspaces();
  }

  loadWorkspaces(): void {
    this.isLoading = true;
    this.workspaceService.getWorkspaces().subscribe({
      next: workspaces => {
        this.workspaces = workspaces.map(workspace => ({
          id: workspace.id,
          name: workspace.name,
          scope:
            workspace.scope === WorkspaceScope.PUBLIC ? 'public' : 'private',
          disabled: workspace.id === this.currentWorkspaceId,
        }));
        this.isLoading = false;
      },
      error: err => {
        console.error('Failed to load workspaces', err);
        this.isLoading = false;
      },
    });
  }

  get filteredWorkspaces(): FlattenedWorkspaceOption[] {
    if (!this.searchQuery) {
      return this.workspaces;
    }
    const query = this.searchQuery.toLowerCase();
    return this.workspaces.filter(w => w.name.toLowerCase().includes(query));
  }

  selectWorkspace(workspace: FlattenedWorkspaceOption): void {
    if (workspace.disabled) {
      return;
    }
    this.selectedWorkspaceId = workspace.id;
  }

  confirm(): void {
    if (this.selectedWorkspaceId) {
      this.dialogRef.close(this.selectedWorkspaceId);
    }
  }
}
