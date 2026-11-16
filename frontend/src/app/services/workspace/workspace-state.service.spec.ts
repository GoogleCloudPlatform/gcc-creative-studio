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
import {UserModel, UserRolesEnum} from '../../common/models/user.model';
import {WorkspaceRole} from '../../common/models/workspace-member.model';
import {Workspace, WorkspaceScope} from '../../common/models/workspace.model';
import {WorkspaceStateService} from './workspace-state.service';

describe('WorkspaceStateService', () => {
  let service: WorkspaceStateService;

  const personalWs: Workspace = {
    id: 10,
    name: 'My Workspace',
    ownerId: '1',
    scope: WorkspaceScope.PERSONAL,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.OWNER,
  };

  const publicWs: Workspace = {
    id: 20,
    name: 'Public Gallery',
    ownerId: '2',
    scope: WorkspaceScope.PUBLIC,
    members: [],
    memberIds: [],
    currentUserRole: null,
  };

  const privateViewerWs: Workspace = {
    id: 30,
    name: 'Team ReadOnly',
    ownerId: '2',
    scope: WorkspaceScope.PRIVATE,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.VIEWER,
  };

  const privateEditorWs: Workspace = {
    id: 40,
    name: 'Team Creators',
    ownerId: '2',
    scope: WorkspaceScope.PRIVATE,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.EDITOR,
  };

  const privateAdminWs: Workspace = {
    id: 50,
    name: 'Team Admins',
    ownerId: '2',
    scope: WorkspaceScope.PRIVATE,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.ADMIN,
  };

  const privateOwnerWs: Workspace = {
    id: 60,
    name: 'Team Owners',
    ownerId: '2',
    scope: WorkspaceScope.PRIVATE,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.OWNER,
  };

  beforeEach(() => {
    localStorage.removeItem('USER_DETAILS');
    sessionStorage.clear();
    TestBed.configureTestingModule({});
    service = TestBed.inject(WorkspaceStateService);
  });

  afterEach(() => {
    localStorage.removeItem('USER_DETAILS');
    sessionStorage.clear();
  });

  it('computes personalWorkspace, activeWorkspace, and edit/manage permissions', () => {
    service.setWorkspaces([
      publicWs,
      privateViewerWs,
      personalWs,
      privateEditorWs,
      privateAdminWs,
      privateOwnerWs,
    ]);

    expect(service.personalWorkspace()?.id).toBe(10);
    expect(service.personalWorkspaceId()).toBe(10);

    service.setActiveWorkspaceId(10);
    expect(service.activeWorkspace()?.id).toBe(10);
    expect(service.isPersonalWorkspaceActive()).toBeTrue();
    expect(service.canEditActiveWorkspace()).toBeTrue();
    expect(service.canManageActiveWorkspace()).toBeTrue();

    service.setActiveWorkspaceId(30);
    expect(service.isPersonalWorkspaceActive()).toBeFalse();
    expect(service.canEditActiveWorkspace()).toBeFalse();
    expect(service.canManageActiveWorkspace()).toBeFalse();

    service.setActiveWorkspaceId(40);
    expect(service.canEditActiveWorkspace()).toBeTrue();
    expect(service.canManageActiveWorkspace()).toBeFalse();

    service.setActiveWorkspaceId(50);
    expect(service.canEditActiveWorkspace()).toBeTrue();
    expect(service.canManageActiveWorkspace()).toBeTrue();
  });

  it('enforces Owner/Admin/Editor/Viewer parity on canEditWorkspace and canManageWorkspace', () => {
    const memberUser: UserModel = {
      id: 99,
      email: 'member@example.com',
      roles: [UserRolesEnum.USER],
    };
    const globalAdmin: UserModel = {
      id: 77,
      email: 'admin@example.com',
      roles: [UserRolesEnum.ADMIN],
    };

    expect(service.canEditWorkspace(null, memberUser)).toBeFalse();
    expect(service.canEditWorkspace(undefined, memberUser)).toBeFalse();
    expect(service.canEditWorkspace(publicWs, memberUser)).toBeTrue();
    expect(service.canEditWorkspace(privateViewerWs, memberUser)).toBeFalse();
    expect(service.canEditWorkspace(privateEditorWs, memberUser)).toBeTrue();
    expect(service.canEditWorkspace(privateAdminWs, memberUser)).toBeTrue();
    expect(service.canEditWorkspace(privateOwnerWs, memberUser)).toBeTrue();

    expect(service.canManageWorkspace(publicWs, memberUser)).toBeFalse();
    expect(service.canManageWorkspace(publicWs, globalAdmin)).toBeTrue();
    expect(service.canManageWorkspace(privateViewerWs, memberUser)).toBeFalse();
    expect(service.canManageWorkspace(privateEditorWs, memberUser)).toBeFalse();
    expect(service.canManageWorkspace(privateAdminWs, memberUser)).toBeTrue();
    expect(service.canManageWorkspace(privateOwnerWs, memberUser)).toBeTrue();
    expect(service.canManageWorkspace(personalWs, globalAdmin)).toBeFalse();
    expect(service.canEditWorkspace(personalWs, null)).toBeFalse();
    expect(
      service.canEditWorkspace(personalWs, {id: undefined, roles: []}),
    ).toBeFalse();
    expect(service.canManageWorkspace(personalWs, null)).toBeFalse();
    expect(
      service.canManageWorkspace({
        ...publicWs,
        currentUserRole: WorkspaceRole.ADMIN,
      }),
    ).toBeTrue();
    expect(service.canManageWorkspace(publicWs)).toBeFalse();
  });

  it('scopes sessionStorage by signed-in user and clears active state on user switch or logout', () => {
    sessionStorage.setItem('cs_active_workspace_id', '99');

    service.syncUser({id: 1, email: 'user1@example.com'});
    service.setWorkspaces([personalWs, publicWs, privateEditorWs]);
    service.setActiveWorkspaceId(40);

    expect(sessionStorage.getItem('cs_active_workspace_id:1')).toBe('40');
    expect(sessionStorage.getItem('cs_active_workspace_id')).toBeNull();
    expect(service.readStoredWorkspaceId()).toBe(40);

    // Switching to another user resets active state synchronously and ignores prior user storage.
    service.syncUser({id: 2, email: 'user2@example.com'});
    expect(service.getActiveWorkspaceId()).toBeNull();
    expect(service.workspaces()).toEqual([]);
    expect(service.readStoredWorkspaceId()).toBeNull();
    expect(sessionStorage.getItem('cs_active_workspace_id:1')).toBeNull();

    // Logout (null) clears active state as well.
    service.setWorkspaces([publicWs]);
    service.setActiveWorkspaceId(20);
    service.syncUser(null);
    expect(service.getActiveWorkspaceId()).toBeNull();
    expect(service.workspaces()).toEqual([]);
    expect(service.readStoredWorkspaceId()).toBeNull();
  });

  it('automatically resets active workspace when localStorage USER_DETAILS clears or changes account', () => {
    localStorage.setItem(
      'USER_DETAILS',
      JSON.stringify({id: 11, email: 'a@example.com'}),
    );
    const localService = new WorkspaceStateService();
    localService.setWorkspaces([personalWs, publicWs]);
    localService.setActiveWorkspaceId(20);
    expect(sessionStorage.getItem('cs_active_workspace_id:11')).toBe('20');

    // Simulate logout removing USER_DETAILS in localStorage.
    localStorage.removeItem('USER_DETAILS');
    expect(localService.getActiveWorkspaceId()).toBeNull();
    expect(localService.workspaces()).toEqual([]);
    expect(sessionStorage.getItem('cs_active_workspace_id:11')).toBeNull();

    // Simulate new user login writing different USER_DETAILS.
    localStorage.setItem(
      'USER_DETAILS',
      JSON.stringify({id: 22, email: 'b@example.com'}),
    );
    expect(localService.readStoredWorkspaceId()).toBeNull();
    localService.setActiveWorkspaceId(10);
    expect(sessionStorage.getItem('cs_active_workspace_id:22')).toBe('10');
  });
});
