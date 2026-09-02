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
import {FolderTreeNode} from '../../models/folder.model';
import {FolderService} from '../../services/folder.service';
import {WorkspaceService} from '../../../services/workspace/workspace.service';
import {forkJoin} from 'rxjs';
import {WorkspaceScope} from '../../models/workspace.model';
import {MatTabChangeEvent} from '@angular/material/tabs';

export interface MoveToFolderDialogData {
  workspaceId: number;
  itemCount: number;
  movingFolderIds?: number[];
  currentFolderId?: number | null;
}

export interface FlattenedFolderOption {
  id: number | null; // null = Root
  name: string;
  depth: number;
  color?: string | null;
  disabled: boolean;
}

export interface FlattenedWorkspaceOption {
  id: number;
  name: string;
  scope: 'public' | 'private';
  disabled: boolean;
}

export interface MoveToFolderDialogResult {
  destinationWorkspaceId?: number;
  destinationFolderId?: number | null;
  destinationName: string;
}

@Component({
  selector: 'app-move-to-folder-dialog',
  templateUrl: './move-to-folder-dialog.component.html',
  styleUrls: ['./move-to-folder-dialog.component.scss'],
})
export class MoveToFolderDialogComponent implements OnInit {
  folderOptions: FlattenedFolderOption[] = [];
  workspaceOptions: FlattenedWorkspaceOption[] = [];
  selectedDestinationId?: number | null;
  isLoading = true;
  searchQuery = '';
  selectedTabIndex = 0;

  constructor(
    public dialogRef: MatDialogRef<MoveToFolderDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: MoveToFolderDialogData,
    private folderService: FolderService,
    private workspaceService: WorkspaceService,
  ) {}

  ngOnInit(): void {
    this.loadFolders();
  }

  loadFolders(): void {
    this.isLoading = true;
    forkJoin([
      this.folderService.getFolderTree(this.data.workspaceId),
      this.workspaceService.getWorkspaces(),
    ]).subscribe({
      next: ([tree, workspaceList]) => {
        // process workspaces
        this.workspaceOptions = workspaceList.map(workspace => ({
          id: workspace.id,
          name: workspace.name,
          scope:
            workspace.scope === WorkspaceScope.PUBLIC ? 'public' : 'private',
          disabled: workspace.id === this.data.workspaceId,
        }));

        // process tree
        const options: FlattenedFolderOption[] = [];
        // Add Root option
        const isCurrentRoot = this.data.currentFolderId === null;
        options.push({
          id: null,
          name: 'Gallery Root (Top Level)',
          depth: 0,
          color: '#8AB4F8',
          disabled: isCurrentRoot,
        });

        // Flatten the tree into indented rows
        const movingFolderIds = new Set<number>(
          this.data.movingFolderIds || [],
        );

        const traverse = (
          nodes: FolderTreeNode[],
          depth: number,
          isMovingParent: boolean,
        ) => {
          for (const node of nodes) {
            const isSelfMoving = movingFolderIds.has(node.id);
            const isDisabled =
              isMovingParent ||
              isSelfMoving ||
              this.data.currentFolderId === node.id;

            options.push({
              id: node.id,
              name: node.name,
              depth,
              color: node.color,
              disabled: isDisabled,
            });

            if (node.children && node.children.length > 0) {
              traverse(
                node.children,
                depth + 1,
                isSelfMoving || isMovingParent,
              );
            }
          }
        };

        traverse(tree, 1, false);
        this.folderOptions = options;
        this.isLoading = false;
      },
      error: err => {
        console.error('Failed to load folder tree', err);
        this.isLoading = false;
      },
    });
  }

  get selectedTab(): 'folder' | 'workspace' {
    return this.selectedTabIndex === 0 ? 'folder' : 'workspace';
  }

  get placeholderText(): string {
    return `Filter ${this.selectedTab}s...`;
  }

  get filteredOptions(): FlattenedFolderOption[] {
    if (!this.searchQuery.trim()) {
      return this.folderOptions;
    }
    const q = this.searchQuery.toLowerCase();
    return this.folderOptions.filter(opt => opt.name.toLowerCase().includes(q));
  }

  get filteredWorkspaces(): FlattenedWorkspaceOption[] {
    if (!this.searchQuery.trim()) {
      return this.workspaceOptions;
    }
    const q = this.searchQuery.toLowerCase();
    return this.workspaceOptions.filter(opt =>
      opt.name.toLowerCase().includes(q),
    );
  }

  onSelectedTabChange(event: MatTabChangeEvent): void {
    this.selectedTabIndex = event.index;
    this.selectedDestinationId = undefined;
  }

  selectOption(opt: FlattenedFolderOption): void {
    if (opt.disabled) {
      return;
    }
    this.selectedDestinationId = opt.id;
  }

  selectWorkspace(opt: FlattenedWorkspaceOption): void {
    if (opt.disabled) {
      return;
    }
    this.selectedDestinationId = opt.id;
  }

  confirm(): void {
    if (this.selectedDestinationId === undefined) {
      return;
    }
    let selectedOption: FlattenedFolderOption | FlattenedWorkspaceOption;
    if (this.selectedTab === 'folder') {
      selectedOption = this.folderOptions.find(
        f => f.id === this.selectedDestinationId,
      )!;
    } else {
      selectedOption = this.workspaceOptions.find(
        f => f.id === this.selectedDestinationId,
      )!;
    }
    this.dialogRef.close({
      destinationWorkspaceId:
        this.selectedTab === 'workspace'
          ? this.selectedDestinationId
          : undefined,
      destinationFolderId:
        this.selectedTab === 'folder' ? this.selectedDestinationId : undefined,
      destinationName: selectedOption.name,
    });
  }

  close(): void {
    this.dialogRef.close();
  }
}
