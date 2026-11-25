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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {Subject, of, throwError} from 'rxjs';
import {FolderTreeNode} from '../../models/folder.model';
import {PromoteTargetWorkspace} from '../../models/gallery-item.model';
import {WorkspaceScope} from '../../models/workspace.model';
import {FolderService} from '../../services/folder.service';
import {GalleryService} from '../../../gallery/gallery.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {WorkspaceService} from '../../../services/workspace/workspace.service';
import {
  PromoteDialogComponent,
  PromoteDialogData,
} from './promote-dialog.component';

describe('PromoteDialogComponent', () => {
  let fixture: ComponentFixture<PromoteDialogComponent>;
  let component: PromoteDialogComponent;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<PromoteDialogComponent>>;
  let galleryServiceSpy: jasmine.SpyObj<GalleryService>;
  let folderServiceSpy: jasmine.SpyObj<FolderService>;
  let workspaceServiceSpy: jasmine.SpyObj<WorkspaceService>;
  let matDialogSpy: jasmine.SpyObj<MatDialog>;

  const brandTarget: PromoteTargetWorkspace = {
    workspaceId: 20,
    workspaceName: 'Summer Campaign',
    scope: 'private',
    currentUserRole: 'editor',
    existingCount: 1,
    newCount: 0,
    existingPromotion: {
      targetWorkspaceId: 20,
      targetWorkspaceName: 'Summer Campaign',
      targetItemId: 500,
      targetFolderId: 7,
      promotedRevisionNumber: 2,
    },
  };

  const reviewTarget: PromoteTargetWorkspace = {
    workspaceId: 21,
    workspaceName: 'Client Review',
    scope: 'private',
    currentUserRole: 'editor',
    existingCount: 0,
    newCount: 1,
    existingPromotion: null,
  };

  const publicTarget: PromoteTargetWorkspace = {
    workspaceId: 1,
    workspaceName: 'Public Gallery',
    scope: 'public',
    currentUserRole: null,
    existingCount: 0,
    newCount: 1,
    existingPromotion: null,
  };

  async function setup(data: PromoteDialogData): Promise<void> {
    dialogRefSpy = jasmine.createSpyObj<MatDialogRef<PromoteDialogComponent>>(
      'MatDialogRef',
      ['close'],
    );
    galleryServiceSpy = jasmine.createSpyObj<GalleryService>('GalleryService', [
      'getPromoteTargets',
      'promoteItems',
    ]);
    folderServiceSpy = jasmine.createSpyObj<FolderService>('FolderService', [
      'getFolderTree',
    ]);
    workspaceServiceSpy = jasmine.createSpyObj<WorkspaceService>(
      'WorkspaceService',
      ['createWorkspace', 'getWorkspaces'],
    );
    matDialogSpy = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);

    galleryServiceSpy.getPromoteTargets.and.returnValue(
      of([publicTarget, brandTarget]),
    );
    folderServiceSpy.getFolderTree.and.returnValue(
      of([{id: 7, name: 'Finals', parentId: null, children: []}]),
    );
    workspaceServiceSpy.getWorkspaces.and.returnValue(of([]));

    await TestBed.configureTestingModule({
      imports: [PromoteDialogComponent, NoopAnimationsModule],
      providers: [
        WorkspaceStateService,
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {provide: MAT_DIALOG_DATA, useValue: data},
        {provide: GalleryService, useValue: galleryServiceSpy},
        {provide: FolderService, useValue: folderServiceSpy},
        {provide: WorkspaceService, useValue: workspaceServiceSpy},
        {provide: MatDialog, useValue: matDialogSpy},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(PromoteDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  it('loads targets, preselects existing folder, and submits update', async () => {
    await setup({
      sourceWorkspaceId: 10,
      items: [{id: 40, type: 'media_item'}],
      defaultTargetWorkspaceId: 20,
      itemLabel: 'Hero Shot',
    });

    expect(component.selectedTargetId()).toBe(20);
    expect(component.selectedFolderId()).toBe(7);
    expect(component.getTargetStatusLabel(brandTarget)).toBe('v2 shared');

    const root = fixture.nativeElement as HTMLElement;
    const pressedWorkspaceBtns = root.querySelectorAll(
      'button.option-row[aria-pressed="true"]',
    );
    expect(pressedWorkspaceBtns.length).toBeGreaterThanOrEqual(2);

    galleryServiceSpy.promoteItems.and.returnValue(
      of({
        targetWorkspaceId: 20,
        promotedCount: 1,
        createdCount: 0,
        updatedCount: 1,
        promotedItems: [
          {
            sourceId: 40,
            sourceType: 'media_item',
            targetId: 500,
            targetWorkspaceId: 20,
            action: 'updated',
          },
        ],
      }),
    );

    component.submit();
    expect(galleryServiceSpy.promoteItems).toHaveBeenCalledWith(
      jasmine.objectContaining({
        sourceWorkspaceId: 10,
        targetWorkspaceId: 20,
        targetFolderId: 7,
        mode: 'update_or_create',
      }),
    );
    expect(dialogRefSpy.close).toHaveBeenCalledWith(
      jasmine.objectContaining({targetWorkspaceName: 'Summer Campaign'}),
    );
  });

  it('never auto-selects public target without explicit default', async () => {
    await TestBed.configureTestingModule({
      imports: [PromoteDialogComponent, NoopAnimationsModule],
      providers: [
        WorkspaceStateService,
        {
          provide: MatDialogRef,
          useValue: jasmine.createSpyObj('MatDialogRef', ['close']),
        },
        {
          provide: MAT_DIALOG_DATA,
          useValue: {
            sourceWorkspaceId: 10,
            items: [{id: 40, type: 'media_item'}],
          } as PromoteDialogData,
        },
        {
          provide: GalleryService,
          useValue: {
            getPromoteTargets: () => of([publicTarget]),
            promoteItems: () => of(),
          },
        },
        {
          provide: FolderService,
          useValue: {getFolderTree: jasmine.createSpy('getFolderTree')},
        },
        {
          provide: WorkspaceService,
          useValue: jasmine.createSpyObj('WorkspaceService', [
            'createWorkspace',
          ]),
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(PromoteDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    expect(component.selectedTargetId()).toBeNull();
    const submitBtn = fixture.nativeElement.querySelector(
      '#promote-submit-btn',
    ) as HTMLButtonElement;
    expect(submitBtn.disabled).toBeTrue();

    TestBed.inject(FolderService).getFolderTree = jasmine
      .createSpy('getFolderTree')
      .and.returnValue(of([]));
    component.selectTarget(publicTarget);
    fixture.detectChanges();
    expect(component.selectedTargetId()).toBe(1);
    expect(submitBtn.disabled).toBeFalse();
  });

  it('uses latest-request-wins when switching targets out of order', async () => {
    const firstFolders$ = new Subject<FolderTreeNode[]>();
    const secondFolders$ = new Subject<FolderTreeNode[]>();
    await setup({
      sourceWorkspaceId: 10,
      items: [{id: 40, type: 'media_item'}],
    });

    galleryServiceSpy.getPromoteTargets.and.returnValue(
      of([brandTarget, reviewTarget]),
    );
    folderServiceSpy.getFolderTree.and.callFake((wsId: number) =>
      wsId === 20 ? firstFolders$ : secondFolders$,
    );

    component.selectTarget(brandTarget);
    component.selectTarget(reviewTarget);

    secondFolders$.next([
      {id: 91, name: 'Review Finals', parentId: null, children: []},
    ]);
    firstFolders$.next([
      {id: 7, name: 'Stale Brand Folder', parentId: null, children: []},
    ]);

    expect(component.selectedTargetId()).toBe(21);
    expect(component.folderOptions().map(f => f.name)).toEqual([
      'All Media (Root)',
      'Review Finals',
    ]);
  });

  it('surfaces folderLoadError with retry recovery on failure', async () => {
    await setup({
      sourceWorkspaceId: 10,
      items: [{id: 40, type: 'media_item'}],
      defaultTargetWorkspaceId: 20,
    });

    component.targets.set([publicTarget, brandTarget, reviewTarget]);
    folderServiceSpy.getFolderTree.and.returnValue(
      throwError(() => new Error('folder error')),
    );
    component.selectTarget(reviewTarget);
    fixture.detectChanges();

    expect(component.folderLoadError()).toContain('Could not load folders');
    const retryBtn = fixture.nativeElement.querySelector(
      '#promote-folder-retry-btn',
    ) as HTMLButtonElement;
    expect(retryBtn).not.toBeNull();
    const submitBtn = fixture.nativeElement.querySelector(
      '#promote-submit-btn',
    ) as HTMLButtonElement;
    expect(submitBtn.disabled).toBeTrue();

    folderServiceSpy.getFolderTree.and.returnValue(
      of([{id: 55, name: 'Recovered', parentId: null, children: []}]),
    );
    retryBtn.click();
    fixture.detectChanges();

    expect(component.folderLoadError()).toBeNull();
    expect(component.folderOptions().map(f => f.name)).toEqual([
      'All Media (Root)',
      'Recovered',
    ]);
    expect(submitBtn.disabled).toBeFalse();
  });

  it('offers Create Shared Workspace empty CTA and reloads targets', async () => {
    await setup({
      sourceWorkspaceId: 10,
      items: [{id: 40, type: 'media_item'}],
    });
    galleryServiceSpy.getPromoteTargets.and.returnValue(of([]));
    component.loadTargets();
    fixture.detectChanges();

    expect(
      fixture.nativeElement.querySelector('#promote-create-workspace-btn'),
    ).not.toBeNull();

    matDialogSpy.open.and.returnValue({
      afterClosed: () => of('Campaign X'),
    } as MatDialogRef<unknown>);
    workspaceServiceSpy.createWorkspace.and.returnValue(
      of({
        id: 77,
        name: 'Campaign X',
        ownerId: '1',
        scope: WorkspaceScope.PRIVATE,
        members: [],
        memberIds: [],
      }),
    );
    galleryServiceSpy.getPromoteTargets.and.returnValue(
      of([
        {
          workspaceId: 77,
          workspaceName: 'Campaign X',
          scope: 'private',
          existingCount: 0,
          newCount: 1,
          existingPromotion: null,
        },
      ]),
    );

    component.openCreateWorkspace();
    expect(workspaceServiceSpy.createWorkspace).toHaveBeenCalledWith(
      'Campaign X',
    );
    expect(component.selectedTargetId()).toBe(77);
  });

  it('displays server error when promote submission fails', async () => {
    await setup({
      sourceWorkspaceId: 10,
      items: [{id: 40, type: 'media_item'}],
      defaultTargetWorkspaceId: 20,
    });
    galleryServiceSpy.promoteItems.and.returnValue(
      throwError(() => ({
        error: {detail: 'Cannot promote into a viewer workspace'},
      })),
    );

    component.submit();
    fixture.detectChanges();
    expect(component.submitError()).toBe(
      'Cannot promote into a viewer workspace',
    );
    expect(dialogRefSpy.close).not.toHaveBeenCalled();
  });

  it('resets stale folder selection to root when folder was deleted', async () => {
    await setup({
      sourceWorkspaceId: 10,
      items: [{id: 40, type: 'media_item'}],
      defaultTargetWorkspaceId: 20,
    });
    expect(component.selectedFolderId()).toBe(7);

    folderServiceSpy.getFolderTree.and.returnValue(
      of([{id: 99, name: 'Other', parentId: null, children: []}]),
    );
    component.selectTarget(brandTarget);
    fixture.detectChanges();

    expect(component.selectedFolderId()).toBeNull();
  });
});
