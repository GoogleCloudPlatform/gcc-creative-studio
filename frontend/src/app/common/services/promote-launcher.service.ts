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

import {Injectable} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {EMPTY, Observable, switchMap} from 'rxjs';
import {
  PromoteDialogComponent,
  PromoteDialogData,
  PromoteDialogResult,
} from '../components/promote-dialog/promote-dialog.component';
import {Workspace, WorkspaceScope} from '../models/workspace.model';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {handleSuccessSnackbar} from '../../utils/handleMessageSnackbar';

export interface OpenPromoteRequest {
  sourceWorkspaceId?: number | null;
  items: PromoteDialogData['items'];
  defaultTargetWorkspaceId?: number | null;
  itemLabel?: string;
  successPrefix?: string;
}

@Injectable({
  providedIn: 'root',
})
export class PromoteLauncherService {
  constructor(
    private dialog: MatDialog,
    private snackBar: MatSnackBar,
    private workspaceStateService: WorkspaceStateService,
  ) {}

  getActivePublishableTarget(): Workspace | null {
    const active = this.workspaceStateService.activeWorkspace();
    const canEdit = this.workspaceStateService.canEditActiveWorkspace();
    if (
      !active ||
      active.scope === WorkspaceScope.PERSONAL ||
      active.scope === WorkspaceScope.PUBLIC ||
      !canEdit
    ) {
      return null;
    }
    return active;
  }

  getPromoteButtonLabel(): string {
    const target = this.getActivePublishableTarget();
    return target ? `Promote to ${target.name}` : 'Promote...';
  }

  getDefaultTargetWorkspaceId(overrideId?: number | null): number | null {
    if (overrideId !== undefined) {
      return overrideId;
    }
    return this.getActivePublishableTarget()?.id ?? null;
  }

  openPromoteDialog(req: OpenPromoteRequest): Observable<PromoteDialogResult> {
    const sourceWorkspaceId =
      req.sourceWorkspaceId ??
      this.workspaceStateService.personalWorkspaceId() ??
      0;
    if (!sourceWorkspaceId || req.items.length === 0) {
      return EMPTY;
    }

    const dialogRef = this.dialog.open(PromoteDialogComponent, {
      data: {
        sourceWorkspaceId,
        items: req.items,
        defaultTargetWorkspaceId: this.getDefaultTargetWorkspaceId(
          req.defaultTargetWorkspaceId,
        ),
        itemLabel: req.itemLabel,
      },
    });

    const prefix = req.successPrefix ?? 'Promoted';
    return dialogRef.afterClosed().pipe(
      switchMap((result: PromoteDialogResult | undefined) => {
        if (!result) {
          return EMPTY;
        }
        handleSuccessSnackbar(
          this.snackBar,
          `${prefix} to ${result.targetWorkspaceName}`,
        );
        return [result];
      }),
    );
  }
}
