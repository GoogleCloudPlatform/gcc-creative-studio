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
import {FormsModule} from '@angular/forms';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {MatCheckboxModule} from '@angular/material/checkbox';
import {MatIconModule} from '@angular/material/icon';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {of} from 'rxjs';
import {UserRolesEnum} from '../../models/user.model';
import {WorkspaceRole} from '../../models/workspace-member.model';
import {Workspace, WorkspaceScope} from '../../models/workspace.model';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {TagModel, TagsService} from '../../services/tags.service';
import {UserService} from '../../services/user.service';
import {TagsManagementDialogComponent} from './tags-management-dialog.component';

describe('TagsManagementDialogComponent', () => {
  const editorUser = {
    id: 7,
    email: 'editor@example.com',
    roles: [UserRolesEnum.USER],
  };

  const privateAdminWs: Workspace = {
    id: 10,
    name: 'Private Admin WS',
    ownerId: '99',
    scope: WorkspaceScope.PRIVATE,
    currentUserRole: WorkspaceRole.ADMIN,
    members: [],
    memberIds: ['7', '99'],
  };

  const privateEditorWs: Workspace = {
    id: 20,
    name: 'Private Editor WS',
    ownerId: '99',
    scope: WorkspaceScope.PRIVATE,
    currentUserRole: WorkspaceRole.EDITOR,
    members: [],
    memberIds: ['7', '99'],
  };

  const personalWs: Workspace = {
    id: 30,
    name: 'My Workspace',
    ownerId: '7',
    scope: WorkspaceScope.PERSONAL,
    currentUserRole: WorkspaceRole.OWNER,
    members: [],
    memberIds: ['7'],
  };

  const myTag: TagModel = {
    id: 1,
    name: 'mine',
    workspaceId: 20,
    userId: 7,
    color: '#1D8DF8',
  };

  const peerTag: TagModel = {
    id: 2,
    name: 'theirs',
    workspaceId: 20,
    userId: 99,
    color: '#F28B82',
  };

  let workspaceStateService: WorkspaceStateService;
  let tagsServiceSpy: jasmine.SpyObj<TagsService>;
  let snackBarSpy: jasmine.SpyObj<MatSnackBar>;
  let currentUser: {id: number; email: string; roles: UserRolesEnum[]};

  function setup(
    activeWs: Workspace,
  ): ComponentFixture<TagsManagementDialogComponent> {
    workspaceStateService.syncUser(currentUser);
    workspaceStateService.setWorkspaces([
      privateAdminWs,
      privateEditorWs,
      personalWs,
    ]);
    workspaceStateService.setActiveWorkspaceId(activeWs.id);

    const fixture = TestBed.createComponent(TagsManagementDialogComponent);
    fixture.detectChanges();
    return fixture;
  }

  beforeEach(async () => {
    currentUser = {...editorUser};
    tagsServiceSpy = jasmine.createSpyObj<TagsService>('TagsService', [
      'getTags',
      'createTag',
      'updateTag',
      'deleteTag',
    ]);
    tagsServiceSpy.getTags.and.returnValue(
      of({
        data: [myTag, peerTag],
        count: 2,
        page: 1,
        pageSize: 10,
        totalPages: 1,
      }),
    );
    snackBarSpy = jasmine.createSpyObj<MatSnackBar>('MatSnackBar', ['open']);

    await TestBed.configureTestingModule({
      declarations: [TagsManagementDialogComponent],
      imports: [
        FormsModule,
        MatCheckboxModule,
        MatIconModule,
        MatProgressSpinnerModule,
        NoopAnimationsModule,
      ],
      providers: [
        WorkspaceStateService,
        {provide: TagsService, useValue: tagsServiceSpy},
        {provide: MatSnackBar, useValue: snackBarSpy},
        {provide: MatDialogRef, useValue: {close: jasmine.createSpy('close')}},
        {provide: MAT_DIALOG_DATA, useValue: {}},
        {
          provide: UserService,
          useValue: {getUserDetails: () => currentUser},
        },
      ],
    }).compileComponents();

    workspaceStateService = TestBed.inject(WorkspaceStateService);
  });

  it('defaults onlyMyTags to false for workspace ADMIN/OWNER and allows managing all row actions', () => {
    const fixture = setup(privateAdminWs);
    const component = fixture.componentInstance;

    expect(component.onlyMyTags).toBeFalse();
    expect(tagsServiceSpy.getTags).toHaveBeenCalledWith(
      10,
      '',
      1,
      10,
      undefined,
    );

    const actionGroups = fixture.nativeElement.querySelectorAll('.tag-actions');
    expect(actionGroups.length).toBe(2);
    expect(component.canManageTag(myTag)).toBeTrue();
    expect(component.canManageTag(peerTag)).toBeTrue();
  });

  it('defaults onlyMyTags to true for EDITOR and gates row edit/delete buttons to tag creator', () => {
    const fixture = setup(privateEditorWs);
    const component = fixture.componentInstance;

    expect(component.onlyMyTags).toBeTrue();
    expect(tagsServiceSpy.getTags).toHaveBeenCalledWith(20, '', 1, 10, 7);

    const actionGroups = fixture.nativeElement.querySelectorAll('.tag-actions');
    expect(actionGroups.length).toBe(1);
    expect(component.canManageTag(myTag)).toBeTrue();
    expect(component.canManageTag(peerTag)).toBeFalse();
  });

  it('defaults onlyMyTags to false for personal workspace owner', () => {
    const fixture = setup(personalWs);
    const component = fixture.componentInstance;

    expect(component.onlyMyTags).toBeFalse();
    expect(tagsServiceSpy.getTags).toHaveBeenCalledWith(
      30,
      '',
      1,
      10,
      undefined,
    );
    expect(component.canManageTag(peerTag)).toBeTrue();
  });
});
