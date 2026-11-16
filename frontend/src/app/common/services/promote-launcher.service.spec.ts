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
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {of} from 'rxjs';
import {WorkspaceRole} from '../models/workspace-member.model';
import {WorkspaceScope} from '../models/workspace.model';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {PromoteDialogComponent} from '../components/promote-dialog/promote-dialog.component';
import {PromoteLauncherService} from './promote-launcher.service';

describe('PromoteLauncherService & WorkspaceStateService helpers', () => {
  let service: PromoteLauncherService;
  let wsState: WorkspaceStateService;
  let dialogSpy: jasmine.SpyObj<MatDialog>;
  let snackBarSpy: jasmine.SpyObj<MatSnackBar>;

  beforeEach(() => {
    dialogSpy = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    snackBarSpy = jasmine.createSpyObj<MatSnackBar>('MatSnackBar', ['open']);

    TestBed.configureTestingModule({
      providers: [
        WorkspaceStateService,
        PromoteLauncherService,
        {provide: MatDialog, useValue: dialogSpy},
        {provide: MatSnackBar, useValue: snackBarSpy},
      ],
    });

    wsState = TestBed.inject(WorkspaceStateService);
    service = TestBed.inject(PromoteLauncherService);
    wsState.setWorkspaces([
      {
        id: 10,
        name: 'My Workspace',
        ownerId: '1',
        scope: WorkspaceScope.PERSONAL,
        members: [],
        memberIds: ['1'],
      },
      {
        id: 20,
        name: 'Brand Team',
        ownerId: '2',
        scope: WorkspaceScope.PRIVATE,
        currentUserRole: WorkspaceRole.EDITOR,
        members: [],
        memberIds: ['1', '2'],
      },
      {
        id: 30,
        name: 'Read Only Team',
        ownerId: '3',
        scope: WorkspaceScope.PRIVATE,
        currentUserRole: WorkspaceRole.VIEWER,
        members: [],
        memberIds: ['1', '3'],
      },
    ]);
  });

  it('computes isPersonalItem accurately', () => {
    expect(wsState.isPersonalItem({workspaceId: 10})).toBeTrue();
    expect(
      wsState.isPersonalItem({
        workspaceId: 99,
        workspaceScope: WorkspaceScope.PERSONAL,
      }),
    ).toBeTrue();
    expect(wsState.isPersonalItem({workspaceId: 20})).toBeFalse();
    expect(wsState.isPersonalItem(null)).toBeFalse();
  });

  it('formats Promote button label for editable shared workspace', () => {
    wsState.setActiveWorkspaceId(10);
    expect(service.getPromoteButtonLabel()).toBe('Promote...');

    wsState.setActiveWorkspaceId(30);
    expect(service.getPromoteButtonLabel()).toBe('Promote...');

    wsState.setActiveWorkspaceId(20);
    expect(service.getPromoteButtonLabel()).toBe('Promote to Brand Team');
  });

  it('excludes PUBLIC workspaces from getActivePublishableTarget', () => {
    wsState.setWorkspaces([
      ...wsState.workspaces(),
      {
        id: 40,
        name: 'Company Public',
        ownerId: '4',
        scope: WorkspaceScope.PUBLIC,
        currentUserRole: WorkspaceRole.EDITOR,
        members: [],
        memberIds: [],
      },
    ]);
    wsState.setActiveWorkspaceId(40);
    expect(service.getActivePublishableTarget()).toBeNull();
    expect(service.getDefaultTargetWorkspaceId()).toBeNull();
    expect(service.getPromoteButtonLabel()).toBe('Promote...');
  });

  it('opens PromoteDialogComponent and shows snackbar feedback', () => {
    wsState.setActiveWorkspaceId(20);
    const mockResult = {
      response: {
        promotedCount: 1,
        createdCount: 1,
        updatedCount: 0,
        promotedItems: [],
      },
      targetWorkspaceName: 'Brand Team',
    };
    dialogSpy.open.and.returnValue({
      afterClosed: () => of(mockResult),
    } as MatDialogRef<unknown>);

    const results: unknown[] = [];
    service
      .openPromoteDialog({
        items: [{id: 55, type: 'media_item'}],
        itemLabel: 'Banner',
      })
      .subscribe(r => results.push(r));

    expect(dialogSpy.open).toHaveBeenCalledWith(PromoteDialogComponent, {
      data: {
        sourceWorkspaceId: 10,
        items: [{id: 55, type: 'media_item'}],
        defaultTargetWorkspaceId: 20,
        itemLabel: 'Banner',
      },
    });
    expect(results).toEqual([mockResult]);
  });
});
