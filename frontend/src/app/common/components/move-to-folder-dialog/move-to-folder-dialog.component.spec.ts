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

import {Component, Input} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {FormsModule} from '@angular/forms';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {MatIconModule} from '@angular/material/icon';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatTabsModule} from '@angular/material/tabs';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {of} from 'rxjs';
import {WorkspaceRole} from '../../models/workspace-member.model';
import {Workspace, WorkspaceScope} from '../../models/workspace.model';
import {FolderService} from '../../services/folder.service';
import {WorkspaceService} from '../../../services/workspace/workspace.service';
import {
  MoveToFolderDialogComponent,
  MoveToFolderDialogData,
} from './move-to-folder-dialog.component';

@Component({
  selector: 'studio-button',
  template: '<button [disabled]="disabled"><ng-content></ng-content></button>',
})
class MockStudioButtonComponent {
  @Input() variant = 'primary';
  @Input() size = 'medium';
  @Input() disabled = false;
}

describe('MoveToFolderDialogComponent', () => {
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
    id: 1,
    name: 'Public Gallery',
    ownerId: '99',
    scope: WorkspaceScope.PUBLIC,
    members: [],
    memberIds: [],
    currentUserRole: null,
  };

  const viewerPrivateWs: Workspace = {
    id: 20,
    name: 'Viewer Team',
    ownerId: '99',
    scope: WorkspaceScope.PRIVATE,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.VIEWER,
  };

  const editorPrivateWs: Workspace = {
    id: 30,
    name: 'Editor Team',
    ownerId: '99',
    scope: WorkspaceScope.PRIVATE,
    members: [],
    memberIds: [],
    currentUserRole: WorkspaceRole.EDITOR,
  };

  let component: MoveToFolderDialogComponent;
  let fixture: ComponentFixture<MoveToFolderDialogComponent>;

  async function setup(data: MoveToFolderDialogData): Promise<void> {
    const folderServiceSpy = jasmine.createSpyObj<FolderService>(
      'FolderService',
      ['getFolderTree'],
    );
    folderServiceSpy.getFolderTree.and.returnValue(of([]));
    (folderServiceSpy as unknown as {maxDepth: number}).maxDepth = 20;

    const workspaceServiceSpy = jasmine.createSpyObj<WorkspaceService>(
      'WorkspaceService',
      ['getWorkspaces'],
    );
    workspaceServiceSpy.getWorkspaces.and.returnValue(
      of([personalWs, publicWs, viewerPrivateWs, editorPrivateWs]),
    );

    await TestBed.configureTestingModule({
      declarations: [MoveToFolderDialogComponent, MockStudioButtonComponent],
      imports: [
        MatIconModule,
        MatTabsModule,
        MatProgressSpinnerModule,
        FormsModule,
        NoopAnimationsModule,
      ],
      providers: [
        {
          provide: MatDialogRef,
          useValue: jasmine.createSpyObj('MatDialogRef', ['close']),
        },
        {provide: MAT_DIALOG_DATA, useValue: data},
        {provide: FolderService, useValue: folderServiceSpy},
        {provide: WorkspaceService, useValue: workspaceServiceSpy},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(MoveToFolderDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  it('hides Workspace tab when source workspace is PERSONAL', async () => {
    await setup({workspaceId: 10, itemCount: 1});
    expect(component.hideWorkspaceTab).toBeTrue();
    const tabs = fixture.nativeElement.querySelectorAll('.mdc-tab');
    expect(tabs.length).toBe(1);
    expect(tabs[0].textContent).toContain('Folder');
  });

  it('shows Workspace tab for shared source workspace and excludes PERSONAL and VIEWER targets', async () => {
    await setup({workspaceId: 1, itemCount: 1});
    expect(component.hideWorkspaceTab).toBeFalse();
    expect(component.workspaceOptions.map(w => w.id)).toEqual([1, 30]);
    expect(component.workspaceOptions[0].disabled).toBeTrue();
    expect(component.workspaceOptions[1].disabled).toBeFalse();
  });
});
