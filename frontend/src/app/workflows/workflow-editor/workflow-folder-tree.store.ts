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

import {Injectable, OnDestroy, inject, signal} from '@angular/core';
import {Observable, Subscription, shareReplay} from 'rxjs';
import {FolderTreeNode} from '../../common/models/folder.model';
import {FolderService} from '../../common/services/folder.service';

/**
 * Media Gallery folder tree shared by every step of one workflow editor page.
 *
 * Provided in `WorkflowEditorComponent.providers` (never in root), so the cache
 * lives exactly as long as the editor and the rest of the app keeps calling the
 * uncached `FolderService`. Trees are loaded lazily, once per workspace, and
 * concurrent callers share the in-flight request. Failed requests are not
 * cached: the next {@link ensureLoaded} retries.
 */
@Injectable()
export class WorkflowFolderTreeStore implements OnDestroy {
  private readonly folderService = inject(FolderService);

  /** Loaded trees by workspace id (a workspace is absent until loaded). */
  private readonly trees = signal<ReadonlyMap<number, FolderTreeNode[]>>(
    new Map(),
  );
  /** Latest request per workspace; dropped once it settles. */
  private readonly requests = new Map<number, Observable<FolderTreeNode[]>>();
  private readonly subscriptions = new Map<number, Subscription>();

  /**
   * Tree of the workspace, or null while it is not loaded (never requested,
   * loading or failed). Reactive when read inside a `computed`/template.
   */
  tree(workspaceId: number): FolderTreeNode[] | null {
    return this.trees().get(workspaceId) ?? null;
  }

  /**
   * Loads the workspace tree unless it is already loaded or loading. Returns
   * the shared request (or null when the tree is already loaded).
   */
  ensureLoaded(workspaceId: number): Observable<FolderTreeNode[]> | null {
    if (this.trees().has(workspaceId)) return null;
    return this.requests.get(workspaceId) ?? this.fetch(workspaceId);
  }

  /**
   * Refetches the workspace tree and replaces it for every reader. The
   * previous tree stays visible until the new one arrives (and on failure).
   */
  refresh(workspaceId: number): Observable<FolderTreeNode[]> {
    return this.fetch(workspaceId);
  }

  ngOnDestroy(): void {
    this.subscriptions.forEach(subscription => subscription.unsubscribe());
    this.subscriptions.clear();
    this.requests.clear();
  }

  private fetch(workspaceId: number): Observable<FolderTreeNode[]> {
    this.subscriptions.get(workspaceId)?.unsubscribe();
    const request$ = this.folderService
      .getFolderTree(workspaceId)
      .pipe(shareReplay({bufferSize: 1, refCount: false}));
    this.requests.set(workspaceId, request$);
    const settle = (): void => {
      // A newer refresh may have replaced this request in the meantime.
      if (this.requests.get(workspaceId) === request$) {
        this.requests.delete(workspaceId);
        this.subscriptions.delete(workspaceId);
      }
    };
    const subscription = request$.subscribe({
      next: tree => {
        if (this.requests.get(workspaceId) !== request$) return;
        this.trees.update(trees => new Map(trees).set(workspaceId, tree ?? []));
      },
      error: (err: unknown) => {
        console.error('Failed to load Media Gallery folders', err);
        settle();
      },
      complete: settle,
    });
    if (this.requests.get(workspaceId) === request$) {
      this.subscriptions.set(workspaceId, subscription);
    }
    return request$;
  }
}
