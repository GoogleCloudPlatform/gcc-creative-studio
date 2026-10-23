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

import {TestBed} from '@angular/core/testing';
import {Subject, of, throwError} from 'rxjs';
import {FolderTreeNode} from '../../common/models/folder.model';
import {FolderService} from '../../common/services/folder.service';
import {WorkflowFolderTreeStore} from './workflow-folder-tree.store';

describe('WorkflowFolderTreeStore', () => {
  const TREE_A: FolderTreeNode[] = [{id: 1, name: 'Campaign', children: []}];
  const TREE_B: FolderTreeNode[] = [{id: 2, name: 'Archive', children: []}];

  let store: WorkflowFolderTreeStore;
  let folderService: jasmine.SpyObj<FolderService>;

  beforeEach(() => {
    folderService = jasmine.createSpyObj<FolderService>('FolderService', [
      'getFolderTree',
    ]);
    TestBed.configureTestingModule({
      providers: [
        WorkflowFolderTreeStore,
        {provide: FolderService, useValue: folderService},
      ],
    });
    store = TestBed.inject(WorkflowFolderTreeStore);
  });

  it('returns null for a workspace that was never loaded', () => {
    expect(store.tree(1)).toBeNull();
    expect(folderService.getFolderTree).not.toHaveBeenCalled();
  });

  it('loads the tree once for repeated calls on the same workspace', () => {
    folderService.getFolderTree.and.returnValue(of(TREE_A));

    store.ensureLoaded(1);
    store.ensureLoaded(1);

    expect(folderService.getFolderTree).toHaveBeenCalledTimes(1);
    expect(store.tree(1)).toEqual(TREE_A);
  });

  it('shares one in-flight request between concurrent callers', () => {
    const response$ = new Subject<FolderTreeNode[]>();
    folderService.getFolderTree.and.returnValue(response$);

    const first$ = store.ensureLoaded(1);
    const second$ = store.ensureLoaded(1);
    expect(store.tree(1)).toBeNull();

    response$.next(TREE_A);
    response$.complete();

    expect(second$).toBe(first$);
    expect(folderService.getFolderTree).toHaveBeenCalledTimes(1);
    expect(store.tree(1)).toEqual(TREE_A);
  });

  it('loads each workspace separately', () => {
    folderService.getFolderTree.and.callFake(workspaceId =>
      of(workspaceId === 1 ? TREE_A : TREE_B),
    );

    store.ensureLoaded(1);
    store.ensureLoaded(2);

    expect(folderService.getFolderTree.calls.allArgs()).toEqual([[1], [2]]);
    expect(store.tree(1)).toEqual(TREE_A);
    expect(store.tree(2)).toEqual(TREE_B);
  });

  it('does not cache errors and retries on the next call', () => {
    const consoleError = spyOn(console, 'error');
    folderService.getFolderTree.and.returnValue(
      throwError(() => new Error('boom')),
    );

    store.ensureLoaded(1);
    expect(store.tree(1)).toBeNull();
    expect(consoleError).toHaveBeenCalled();

    folderService.getFolderTree.and.returnValue(of(TREE_A));
    store.ensureLoaded(1);

    expect(folderService.getFolderTree).toHaveBeenCalledTimes(2);
    expect(store.tree(1)).toEqual(TREE_A);
  });

  it('refetches on refresh and replaces the tree', () => {
    folderService.getFolderTree.and.returnValue(of(TREE_A));
    store.ensureLoaded(1);

    folderService.getFolderTree.and.returnValue(of(TREE_B));
    store.refresh(1);

    expect(folderService.getFolderTree).toHaveBeenCalledTimes(2);
    expect(store.tree(1)).toEqual(TREE_B);
  });

  it('keeps the previous tree when a refresh fails', () => {
    spyOn(console, 'error');
    folderService.getFolderTree.and.returnValue(of(TREE_A));
    store.ensureLoaded(1);

    folderService.getFolderTree.and.returnValue(
      throwError(() => new Error('boom')),
    );
    store.refresh(1);

    expect(store.tree(1)).toEqual(TREE_A);
  });

  it('ignores a stale response superseded by a refresh', () => {
    const stale$ = new Subject<FolderTreeNode[]>();
    folderService.getFolderTree.and.returnValue(stale$);
    store.ensureLoaded(1);

    folderService.getFolderTree.and.returnValue(of(TREE_B));
    store.refresh(1);
    stale$.next(TREE_A);

    expect(store.tree(1)).toEqual(TREE_B);
  });

  it('stops applying responses once destroyed', () => {
    const response$ = new Subject<FolderTreeNode[]>();
    folderService.getFolderTree.and.returnValue(response$);
    store.ensureLoaded(1);

    store.ngOnDestroy();
    response$.next(TREE_A);

    expect(store.tree(1)).toBeNull();
  });
});
