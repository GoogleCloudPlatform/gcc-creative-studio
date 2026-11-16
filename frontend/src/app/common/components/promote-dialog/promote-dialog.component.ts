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

import {CommonModule} from '@angular/common';
import {
  Component,
  Inject,
  OnDestroy,
  OnInit,
  computed,
  signal,
} from '@angular/core';
import {MatButtonModule} from '@angular/material/button';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {MatIconModule} from '@angular/material/icon';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatRadioModule} from '@angular/material/radio';
import {
  Subject,
  catchError,
  finalize,
  of,
  switchMap,
  takeUntil,
  tap,
} from 'rxjs';
import {FolderTreeNode} from '../../models/folder.model';
import {
  BulkCopyItem,
  PromoteResponse,
  PromoteTargetWorkspace,
} from '../../models/gallery-item.model';
import {FolderService} from '../../services/folder.service';
import {GalleryService} from '../../../gallery/gallery.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {WorkspaceService} from '../../../services/workspace/workspace.service';
import {CreateWorkspaceModalComponent} from '../create-workspace-modal/create-workspace-modal.component';

export interface PromoteDialogData {
  sourceWorkspaceId: number;
  items: BulkCopyItem[];
  defaultTargetWorkspaceId?: number | null;
  itemLabel?: string;
}

export interface PromoteDialogResult {
  response: PromoteResponse;
  targetWorkspaceName: string;
}

export interface TargetFolderOption {
  id: number | null;
  name: string;
  depth: number;
}

const ROOT_FOLDER_OPTION: TargetFolderOption = {
  id: null,
  name: 'All Media (Root)',
  depth: 0,
};

@Component({
  selector: 'app-promote-dialog',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatRadioModule,
  ],
  templateUrl: './promote-dialog.component.html',
  styleUrl: './promote-dialog.component.scss',
})
export class PromoteDialogComponent implements OnInit, OnDestroy {
  readonly isLoading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly targets = signal<PromoteTargetWorkspace[]>([]);
  readonly selectedTargetId = signal<number | null>(null);
  readonly folderOptions = signal<TargetFolderOption[]>([ROOT_FOLDER_OPTION]);
  readonly isLoadingFolders = signal(false);
  readonly folderLoadError = signal<string | null>(null);
  readonly selectedFolderId = signal<number | null>(null);
  readonly mode = signal<'update_or_create' | 'create_new'>('update_or_create');
  readonly isSubmitting = signal(false);
  readonly submitError = signal<string | null>(null);

  readonly selectedTarget = computed(
    () =>
      this.targets().find(t => t.workspaceId === this.selectedTargetId()) ??
      null,
  );
  readonly isBatch = computed(
    () =>
      this.data.items.length > 1 ||
      this.data.items.some(item => item.type === 'folder'),
  );
  readonly isFolderOnly = computed(
    () =>
      this.data.items.length > 0 &&
      this.data.items.every(item => item.type === 'folder'),
  );

  private readonly folderRequests$ = new Subject<number>();
  private readonly destroy$ = new Subject<void>();

  constructor(
    public dialogRef: MatDialogRef<
      PromoteDialogComponent,
      PromoteDialogResult | undefined
    >,
    @Inject(MAT_DIALOG_DATA) public data: PromoteDialogData,
    private galleryService: GalleryService,
    private folderService: FolderService,
    private workspaceService: WorkspaceService,
    private workspaceStateService: WorkspaceStateService,
    private dialog: MatDialog,
  ) {}

  ngOnInit(): void {
    this.folderRequests$
      .pipe(
        tap(() => {
          this.isLoadingFolders.set(true);
          this.folderLoadError.set(null);
          this.folderOptions.set([ROOT_FOLDER_OPTION]);
        }),
        switchMap(workspaceId =>
          this.folderService.getFolderTree(workspaceId).pipe(
            catchError(() => {
              this.isLoadingFolders.set(false);
              this.folderLoadError.set(
                'Could not load folders for this workspace.',
              );
              this.folderOptions.set([ROOT_FOLDER_OPTION]);
              return of<FolderTreeNode[] | null>(null);
            }),
          ),
        ),
        takeUntil(this.destroy$),
      )
      .subscribe(tree => {
        if (tree === null) {
          return;
        }
        const flattened: TargetFolderOption[] = [ROOT_FOLDER_OPTION];
        const walk = (nodes: FolderTreeNode[], depth: number): void => {
          for (const node of nodes) {
            flattened.push({id: node.id, name: node.name, depth});
            if (node.children?.length) {
              walk(node.children, depth + 1);
            }
          }
        };
        walk(tree || [], 1);
        this.folderOptions.set(flattened);
        if (
          this.selectedFolderId() !== null &&
          !flattened.some(f => f.id === this.selectedFolderId())
        ) {
          this.selectedFolderId.set(null);
        }
        this.isLoadingFolders.set(false);
      });

    this.loadTargets(this.data.defaultTargetWorkspaceId ?? null);
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  loadTargets(preferredTargetId: number | null = null): void {
    this.isLoading.set(true);
    this.loadError.set(null);
    this.galleryService
      .getPromoteTargets(this.data.sourceWorkspaceId, this.data.items)
      .pipe(
        takeUntil(this.destroy$),
        finalize(() => this.isLoading.set(false)),
      )
      .subscribe({
        next: targets => {
          this.targets.set(targets);
          if (targets.length === 0) {
            this.selectedTargetId.set(null);
            return;
          }
          const preferred =
            preferredTargetId !== null
              ? targets.find(t => t.workspaceId === preferredTargetId)
              : undefined;
          // Never auto-select org-wide public workspaces when no explicit
          // target was requested; require an intentional user click instead.
          const firstNonPublic = targets.find(t => t.scope !== 'public');
          const initialTarget = preferred ?? firstNonPublic ?? null;
          if (initialTarget) {
            this.selectTarget(initialTarget);
          } else {
            this.selectedTargetId.set(null);
            this.selectedFolderId.set(null);
            this.folderOptions.set([ROOT_FOLDER_OPTION]);
          }
        },
        error: () => {
          this.loadError.set(
            'Could not load shared workspaces. Please try again.',
          );
        },
      });
  }

  selectTarget(target: PromoteTargetWorkspace): void {
    this.selectedTargetId.set(target.workspaceId);
    this.submitError.set(null);
    this.mode.set('update_or_create');
    const initialFolderId =
      !this.isBatch() && target.existingPromotion?.targetFolderId !== undefined
        ? (target.existingPromotion.targetFolderId ?? null)
        : null;
    this.selectedFolderId.set(initialFolderId);
    this.folderRequests$.next(target.workspaceId);
  }

  retryLoadFolders(): void {
    const targetId = this.selectedTargetId();
    if (targetId !== null) {
      this.folderRequests$.next(targetId);
    }
  }

  selectFolder(folderId: number | null): void {
    this.selectedFolderId.set(folderId);
  }

  setMode(mode: 'update_or_create' | 'create_new'): void {
    this.mode.set(mode);
  }

  getTargetStatusLabel(target: PromoteTargetWorkspace): string {
    if (
      !this.isBatch() &&
      target.existingPromotion?.promotedRevisionNumber !== undefined &&
      target.existingPromotion?.promotedRevisionNumber !== null
    ) {
      return `v${target.existingPromotion.promotedRevisionNumber} shared`;
    }
    if (target.existingCount === 1 && target.newCount === 0) {
      return 'Shared';
    }
    if (target.existingCount > 0 && target.newCount > 0) {
      return `${target.existingCount} existing · ${target.newCount} new`;
    }
    if (target.existingCount > 1) {
      return `${target.existingCount} existing`;
    }
    return '';
  }

  openCreateWorkspace(): void {
    const createRef = this.dialog.open(CreateWorkspaceModalComponent, {
      width: '400px',
    });
    createRef
      .afterClosed()
      .pipe(takeUntil(this.destroy$))
      .subscribe((name: string | undefined) => {
        const trimmed = name?.trim();
        if (!trimmed) {
          return;
        }
        this.isLoading.set(true);
        this.workspaceService
          .createWorkspace(trimmed)
          .pipe(takeUntil(this.destroy$))
          .subscribe({
            next: created => {
              this.workspaceService
                .getWorkspaces()
                .pipe(takeUntil(this.destroy$))
                .subscribe({
                  next: list => this.workspaceStateService.setWorkspaces(list),
                  error: err =>
                    console.warn(
                      'Failed to refresh workspaces after create',
                      err,
                    ),
                });
              this.loadTargets(created.id);
            },
            error: () => {
              this.isLoading.set(false);
              this.loadError.set('Could not create shared workspace.');
            },
          });
      });
  }

  submit(): void {
    const target = this.selectedTarget();
    if (!target || this.isSubmitting() || this.isLoadingFolders()) {
      return;
    }
    this.isSubmitting.set(true);
    this.submitError.set(null);
    this.galleryService
      .promoteItems({
        sourceWorkspaceId: this.data.sourceWorkspaceId,
        targetWorkspaceId: target.workspaceId,
        targetFolderId: this.selectedFolderId(),
        ...(!this.isBatch() && this.selectedFolderId() === null
          ? {clearTargetFolder: true}
          : {}),
        items: this.data.items,
        mode: target.existingCount > 0 ? this.mode() : 'create_new',
      })
      .pipe(
        takeUntil(this.destroy$),
        finalize(() => this.isSubmitting.set(false)),
      )
      .subscribe({
        next: response => {
          this.dialogRef.close({
            response,
            targetWorkspaceName: target.workspaceName,
          });
        },
        error: err => {
          const detail = err?.error?.detail;
          this.submitError.set(
            typeof detail === 'string'
              ? detail
              : 'Failed to promote items. Please try again.',
          );
        },
      });
  }

  close(): void {
    this.dialogRef.close();
  }
}
