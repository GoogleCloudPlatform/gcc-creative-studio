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

import {Injectable, inject} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {Observable, catchError, forkJoin, map, of, take} from 'rxjs';
import {AssetTypeEnum} from '../../admin/source-assets-management/source-asset.model';
import {
  ImageSelectorComponent,
  ImageSelectorDialogData,
} from '../../common/components/image-selector/image-selector.component';
import {FolderSelectionResult} from '../../common/models/folder.model';
import {FolderService} from '../../common/services/folder.service';
import {FolderPathMap, joinFolderBreadcrumbs} from '../utils/folder-path.util';
import {toFolderId} from '../workflow-editor/step-components/step-configs/folder-setting.util';

/** Folder id paired with its resolved path (`null` when it failed). */
type FolderPathEntry = readonly [number, string | null];

/** Folder id paired with a successfully resolved path. */
type ResolvedFolderPathEntry = readonly [number, string];

/**
 * Folder picking and path resolution for workflow runs (run modal, resume,
 * batch). Stateless: nothing is cached between calls.
 */
@Injectable({providedIn: 'root'})
export class RunFolderService {
  private readonly dialog = inject(MatDialog);
  private readonly folderService = inject(FolderService);

  /**
   * Opens the Media Gallery in folder mode at `initialFolderId` (`null` =
   * root). Emits once: the picked folder, or `null` on cancel or an invalid
   * id. Never errors.
   */
  pickFolder(
    initialFolderId: number | null,
  ): Observable<FolderSelectionResult | null> {
    const data: ImageSelectorDialogData = {
      selectionTarget: 'folder',
      initialFolderId,
      mimeType: null,
      assetType: AssetTypeEnum.GENERIC_IMAGE,
    };
    return this.dialog
      .open<
        ImageSelectorComponent,
        ImageSelectorDialogData,
        FolderSelectionResult | null
      >(ImageSelectorComponent, {
        width: '90vw',
        height: '80vh',
        maxWidth: '90vw',
        panelClass: 'image-selector-dialog',
        data,
      })
      .afterClosed()
      .pipe(
        take(1),
        map(result =>
          result && toFolderId(result.folderId) !== null ? result : null,
        ),
        catchError((error: unknown) => {
          console.warn('Folder picker failed', error);
          return of(null);
        }),
      );
  }

  /**
   * Resolves the full path of each folder in `workspaceId`. Duplicate ids are
   * requested once; ids that fail are left out. Never errors.
   */
  resolveFolderPaths(
    folderIds: readonly number[],
    workspaceId: number | null,
  ): Observable<FolderPathMap> {
    const ids = [...new Set(folderIds)];
    if (ids.length === 0) {
      return of(new Map<number, string>());
    }
    return forkJoin(
      ids.map(id => this.resolveFolderPath(id, workspaceId)),
    ).pipe(
      map(
        entries =>
          new Map(
            entries.filter(
              (entry): entry is ResolvedFolderPathEntry => entry[1] !== null,
            ),
          ),
      ),
    );
  }

  private resolveFolderPath(
    folderId: number,
    workspaceId: number | null,
  ): Observable<FolderPathEntry> {
    return this.folderService
      .getBreadcrumbs(folderId, workspaceId ?? undefined)
      .pipe(
        map(joinFolderBreadcrumbs),
        catchError((error: unknown) => {
          console.warn('Failed to resolve folder path', folderId, error);
          return of(null);
        }),
        map((path): FolderPathEntry => [folderId, path]),
      );
  }
}
