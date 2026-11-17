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

import {OverlayContainer} from '@angular/cdk/overlay';
import {PLATFORM_ID} from '@angular/core';
import {
  ComponentFixture,
  fakeAsync,
  flush,
  TestBed,
} from '@angular/core/testing';
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {MatDividerModule} from '@angular/material/divider';
import {MatIconModule} from '@angular/material/icon';
import {MatMenuModule, MatMenuTrigger} from '@angular/material/menu';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatTooltipModule} from '@angular/material/tooltip';
import {By} from '@angular/platform-browser';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {ActivatedRoute, convertToParamMap} from '@angular/router';
import {of} from 'rxjs';
import {BrandGuidelineModel} from '../../models/brand-guideline.model';
import {JobStatus} from '../../models/media-item.model';
import {UserModel, UserRolesEnum} from '../../models/user.model';
import {WorkspaceRole} from '../../models/workspace-member.model';
import {Workspace, WorkspaceScope} from '../../models/workspace.model';
import {BrandGuidelineService} from '../../services/brand-guideline/brand-guideline.service';
import {NotificationService} from '../../services/notification.service';
import {UserService} from '../../services/user.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {WorkspaceService} from '../../../services/workspace/workspace.service';
import {useTestBedAppInjector} from '../../../testing/app-injector.testing';
import {WorkspaceSwitcherComponent} from './workspace-switcher.component';

describe('WorkspaceSwitcherComponent', () => {
  const SESSION_KEY_PREFIX = 'cs_active_workspace_id';
  const SESSION_KEY = `${SESSION_KEY_PREFIX}:10`;

  const publicWs: Workspace = {
    id: 1,
    name: 'Public Workspace',
    ownerId: '99',
    scope: WorkspaceScope.PUBLIC,
    members: [],
    memberIds: [],
    currentUserRole: null,
  };

  const personalWs: Workspace = {
    id: 2,
    name: 'My Workspace',
    ownerId: '10',
    scope: WorkspaceScope.PERSONAL,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.OWNER,
  };

  const privateViewerWs: Workspace = {
    id: 3,
    name: 'Client Viewer Team',
    ownerId: '99',
    scope: WorkspaceScope.PRIVATE,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.VIEWER,
  };

  const privateAdminWs: Workspace = {
    id: 4,
    name: 'Client Admin Team',
    ownerId: '99',
    scope: WorkspaceScope.PRIVATE,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.ADMIN,
  };

  const privateEditorWs: Workspace = {
    id: 5,
    name: 'Client Editor Team',
    ownerId: '99',
    scope: WorkspaceScope.PRIVATE,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.EDITOR,
  };

  let fixture: ComponentFixture<WorkspaceSwitcherComponent>;
  let component: WorkspaceSwitcherComponent;
  let workspaceStateService: WorkspaceStateService;
  let workspaceServiceSpy: jasmine.SpyObj<WorkspaceService>;
  let brandGuidelineServiceSpy: jasmine.SpyObj<BrandGuidelineService>;
  let dialogSpy: jasmine.SpyObj<MatDialog>;
  let overlayContainer: OverlayContainer;
  let snackBarSpy: jasmine.SpyObj<MatSnackBar>;
  let notificationServiceSpy: jasmine.SpyObj<NotificationService>;
  let currentUser: UserModel;

  async function setup(options?: {
    workspaces?: Workspace[];
    queryWorkspaceId?: string | null;
    user?: UserModel;
  }): Promise<void> {
    sessionStorage.clear();
    localStorage.removeItem('USER_DETAILS');
    localStorage.removeItem('activeWorkspaceId');

    currentUser = options?.user ?? {
      id: 10,
      email: 'creator@example.com',
      roles: [UserRolesEnum.USER],
    };

    workspaceServiceSpy = jasmine.createSpyObj<WorkspaceService>(
      'WorkspaceService',
      ['getWorkspaces', 'createWorkspace', 'inviteUser'],
    );
    workspaceServiceSpy.getWorkspaces.and.returnValue(
      of(options?.workspaces ?? [publicWs, privateViewerWs, personalWs]),
    );
    workspaceServiceSpy.inviteUser.and.returnValue(of(void 0));
    brandGuidelineServiceSpy = jasmine.createSpyObj<BrandGuidelineService>(
      'BrandGuidelineService',
      [
        'getBrandGuidelineForWorkspace',
        'createBrandGuideline',
        'deleteBrandGuideline',
        'setProcessingState',
        'clearActiveJob',
        'clearCache',
      ],
      {activeBrandGuidelineJob$: of(null)},
    );
    brandGuidelineServiceSpy.getBrandGuidelineForWorkspace.and.returnValue(
      of(null),
    );
    brandGuidelineServiceSpy.createBrandGuideline.and.returnValue(
      of({} as BrandGuidelineModel),
    );
    brandGuidelineServiceSpy.deleteBrandGuideline.and.returnValue(of(void 0));
    dialogSpy = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    snackBarSpy = jasmine.createSpyObj<MatSnackBar>('MatSnackBar', ['open']);
    notificationServiceSpy = jasmine.createSpyObj<NotificationService>(
      'NotificationService',
      ['show'],
    );

    const queryParams = options?.queryWorkspaceId
      ? {workspaceId: options.queryWorkspaceId}
      : {};

    await TestBed.configureTestingModule({
      declarations: [WorkspaceSwitcherComponent],
      imports: [
        MatMenuModule,
        MatDividerModule,
        MatIconModule,
        MatTooltipModule,
        NoopAnimationsModule,
      ],
      providers: [
        WorkspaceStateService,
        {provide: WorkspaceService, useValue: workspaceServiceSpy},
        {provide: BrandGuidelineService, useValue: brandGuidelineServiceSpy},
        {
          provide: UserService,
          useValue: {getUserDetails: () => currentUser},
        },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {queryParamMap: convertToParamMap(queryParams)},
          },
        },
        {provide: MatDialog, useValue: dialogSpy},
        {provide: MatSnackBar, useValue: snackBarSpy},
        {provide: NotificationService, useValue: notificationServiceSpy},
        {provide: PLATFORM_ID, useValue: 'browser'},
      ],
    }).compileComponents();

    useTestBedAppInjector();
    workspaceStateService = TestBed.inject(WorkspaceStateService);
    overlayContainer = TestBed.inject(OverlayContainer);
    fixture = TestBed.createComponent(WorkspaceSwitcherComponent);
    component = fixture.componentInstance;
  }

  afterEach(() => {
    overlayContainer?.ngOnDestroy();
    sessionStorage.clear();
    localStorage.removeItem('USER_DETAILS');
    localStorage.removeItem('activeWorkspaceId');
  });

  it('pins PERSONAL workspace first, defaults fresh session to PERSONAL, and writes only to per-user sessionStorage', async () => {
    const localSetSpy = spyOn(Storage.prototype, 'setItem').and.callThrough();
    await setup();
    fixture.detectChanges();

    expect(component.workspaces.map(w => w.id)).toEqual([2, 1, 3]);
    expect(component.activeWorkspaceId).toBe(2);
    expect(workspaceStateService.personalWorkspaceId()).toBe(2);
    expect(sessionStorage.getItem(SESSION_KEY)).toBe('2');
    expect(sessionStorage.getItem(SESSION_KEY_PREFIX)).toBeNull();
    expect(localStorage.getItem('activeWorkspaceId')).toBeNull();
    expect(
      localSetSpy.calls.allArgs().some(([key]) => key === 'activeWorkspaceId'),
    ).toBeFalse();

    expect(component.getWorkspaceIcon(WorkspaceScope.PERSONAL)).toBe('person');
    expect(component.getWorkspaceIcon(WorkspaceScope.PUBLIC)).toBe('public');
    expect(component.getWorkspaceIcon(WorkspaceScope.PRIVATE)).toBe('lock');
  });

  it('respects precedence: URL query param > current active > sessionStorage > personal', async () => {
    await setup({queryWorkspaceId: '3'});
    sessionStorage.setItem(SESSION_KEY, '1');
    fixture.detectChanges();

    expect(component.activeWorkspaceId).toBe(3);

    TestBed.resetTestingModule();
    await setup();
    sessionStorage.setItem(SESSION_KEY, '1');
    fixture.detectChanges();
    expect(component.activeWorkspaceId).toBe(1);
    expect(notificationServiceSpy.show).not.toHaveBeenCalled();
  });

  it('shows Access Denied snackbar only for inaccessible ?workspaceId query params and falls back silently for stale session keys or user switches', async () => {
    // 1. Inaccessible URL query param triggers Access Denied snackbar and falls back to personal.
    await setup({queryWorkspaceId: '999'});
    fixture.detectChanges();
    expect(component.activeWorkspaceId).toBe(2);
    expect(notificationServiceSpy.show).toHaveBeenCalledWith(
      jasmine.stringContaining('permission to access the requested workspace'),
      'error',
      jasmine.anything(),
      undefined,
      jasmine.anything(),
    );

    // 2. Stale sessionStorage ID for same user falls back to personal silently without Access Denied snackbar.
    TestBed.resetTestingModule();
    await setup();
    sessionStorage.setItem(SESSION_KEY, '999');
    fixture.detectChanges();
    expect(component.activeWorkspaceId).toBe(2);
    expect(notificationServiceSpy.show).not.toHaveBeenCalled();

    // 3. Switching user identity ignores previous user activeWorkspaceId/sessionStorage and lands in new user personal workspace cleanly.
    component.setActiveWorkspace(3);
    expect(sessionStorage.getItem(SESSION_KEY)).toBe('3');
    const personalWsUserB: Workspace = {
      id: 22,
      name: 'My Workspace',
      ownerId: '20',
      scope: WorkspaceScope.PERSONAL,
      members: [],
      memberIds: [],
      currentUserRole: WorkspaceRole.OWNER,
    };
    currentUser = {
      id: 20,
      email: 'userb@example.com',
      roles: [UserRolesEnum.USER],
    };
    workspaceServiceSpy.getWorkspaces.and.returnValue(
      of([publicWs, personalWsUserB]),
    );
    component.loadWorkspaces();
    expect(component.activeWorkspaceId).toBe(22);
    expect(sessionStorage.getItem(`${SESSION_KEY_PREFIX}:20`)).toBe('22');
    expect(notificationServiceSpy.show).not.toHaveBeenCalled();
  });

  it('gates Invite Users and Brand Guidelines by workspace scope and WorkspaceRole', async () => {
    await setup({
      workspaces: [
        publicWs,
        personalWs,
        privateViewerWs,
        privateEditorWs,
        privateAdminWs,
      ],
    });
    fixture.detectChanges();

    // PERSONAL active: neither Invite nor Brand Guidelines available.
    component.setActiveWorkspace(2);
    expect(component.canInvite).toBeFalse();
    expect(component.canAccessBrandGuidelines).toBeFalse();
    expect(component.canPerformEditActionsOnBrandGuidelines).toBeFalse();

    // PRIVATE VIEWER: can view Brand Guidelines, cannot invite or edit Brand Guidelines.
    component.setActiveWorkspace(3);
    expect(component.canInvite).toBeFalse();
    expect(component.canAccessBrandGuidelines).toBeTrue();
    expect(component.canPerformEditActionsOnBrandGuidelines).toBeFalse();

    // PRIVATE EDITOR: can view Brand Guidelines, cannot invite or edit Brand Guidelines.
    component.setActiveWorkspace(5);
    expect(component.canInvite).toBeFalse();
    expect(component.canAccessBrandGuidelines).toBeTrue();
    expect(component.canPerformEditActionsOnBrandGuidelines).toBeFalse();

    // PRIVATE ADMIN: can invite and edit Brand Guidelines with Owner parity.
    component.setActiveWorkspace(4);
    expect(component.canInvite).toBeTrue();
    expect(component.canAccessBrandGuidelines).toBeTrue();
    expect(component.canPerformEditActionsOnBrandGuidelines).toBeTrue();
  });

  it('reactively updates workspaces when WorkspaceStateService updates externally', async () => {
    await setup();
    fixture.detectChanges();

    const newlyCreated: Workspace = {
      id: 99,
      name: 'Brand Launch',
      ownerId: '10',
      scope: WorkspaceScope.PRIVATE,
      members: [],
      memberIds: [],
      currentUserRole: WorkspaceRole.OWNER,
    };
    workspaceStateService.setWorkspaces([publicWs, personalWs, newlyCreated]);
    expect(component.workspaces.map(w => w.id)).toEqual([2, 1, 99]);

    component.setActiveWorkspace(99);
    expect(component.activeWorkspace?.name).toBe('Brand Launch');
  });

  it('hides Invite Users from menu DOM unless canInvite is true and blocks handler bypasses', async () => {
    await setup({
      workspaces: [
        publicWs,
        personalWs,
        privateViewerWs,
        privateEditorWs,
        privateAdminWs,
      ],
    });
    fixture.detectChanges();

    const getMenuLabels = async (): Promise<string[]> => {
      fixture.detectChanges();
      const trigger = fixture.debugElement
        .query(By.directive(MatMenuTrigger))
        .injector.get(MatMenuTrigger);
      trigger.openMenu();
      fixture.detectChanges();
      await fixture.whenStable();
      const labels = Array.from(
        overlayContainer
          .getContainerElement()
          .querySelectorAll('button[mat-menu-item]'),
      ).map(el => el.textContent ?? '');
      trigger.closeMenu();
      fixture.detectChanges();
      await fixture.whenStable();
      return labels;
    };

    for (const workspaceId of [privateViewerWs.id, privateEditorWs.id]) {
      component.setActiveWorkspace(workspaceId);
      const labels = await getMenuLabels();
      expect(labels.some(text => text.includes('Invite Users'))).toBeFalse();
      expect(labels.some(text => text.includes('Brand Guidelines'))).toBeTrue();

      dialogSpy.open.calls.reset();
      component.openInviteDialog(new MouseEvent('click'));
      expect(dialogSpy.open).not.toHaveBeenCalled();
    }

    component.setActiveWorkspace(privateAdminWs.id);
    const adminLabels = await getMenuLabels();
    expect(adminLabels.some(text => text.includes('Invite Users'))).toBeTrue();

    dialogSpy.open.and.returnValue({
      afterClosed: () => of(null),
    } as MatDialogRef<unknown>);
    component.openInviteDialog(new MouseEvent('click'));
    expect(dialogSpy.open).toHaveBeenCalledTimes(1);
  });

  it('blocks Brand Guidelines delete and upload mutations when viewer or editor triggers closed actions', async () => {
    await setup({
      workspaces: [publicWs, personalWs, privateViewerWs, privateAdminWs],
    });
    fixture.detectChanges();

    const existingGuideline: BrandGuidelineModel = {
      id: 77,
      name: 'Acme',
      workspaceId: privateViewerWs.id,
      sourcePdfGcsUris: ['gs://b/a.pdf'],
      colorPalette: ['#000000'],
      status: JobStatus.COMPLETED,
    };
    brandGuidelineServiceSpy.getBrandGuidelineForWorkspace.and.returnValue(
      of(existingGuideline),
    );

    component.setActiveWorkspace(privateViewerWs.id);
    dialogSpy.open.and.returnValue({
      afterClosed: () => of({delete: true}),
    } as MatDialogRef<unknown>);
    component.openBrandGuidelinesDialog(new MouseEvent('click'));
    expect(dialogSpy.open).toHaveBeenCalledTimes(1);
    expect(
      brandGuidelineServiceSpy.deleteBrandGuideline,
    ).not.toHaveBeenCalled();

    dialogSpy.open.calls.reset();
    dialogSpy.open.and.returnValue({
      afterClosed: () =>
        of({
          name: 'Upload Attempt',
          file: new File(['pdf'], 'brand.pdf', {type: 'application/pdf'}),
        }),
    } as MatDialogRef<unknown>);
    component.openBrandGuidelinesDialog(new MouseEvent('click'));
    expect(brandGuidelineServiceSpy.setProcessingState).not.toHaveBeenCalled();
    expect(
      brandGuidelineServiceSpy.createBrandGuideline,
    ).not.toHaveBeenCalled();

    component.setActiveWorkspace(privateAdminWs.id);
    dialogSpy.open.calls.reset();
    dialogSpy.open.and.returnValues(
      {afterClosed: () => of({delete: true})} as MatDialogRef<unknown>,
      {afterClosed: () => of(true)} as MatDialogRef<unknown>,
    );
    component.openBrandGuidelinesDialog(new MouseEvent('click'));
    expect(dialogSpy.open).toHaveBeenCalledTimes(2);
    expect(brandGuidelineServiceSpy.deleteBrandGuideline).toHaveBeenCalledWith(
      existingGuideline.id,
    );
  });
});
