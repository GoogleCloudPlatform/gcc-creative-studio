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
  MatDialogModule,
  MatDialogRef,
  MAT_DIALOG_DATA,
} from '@angular/material/dialog';
import {MatIconModule} from '@angular/material/icon';
import {MatTabsModule} from '@angular/material/tabs';
import {FormsModule} from '@angular/forms';
import {of, throwError} from 'rxjs';
import {
  CopyToFolderDialogComponent,
  CopyToFolderDialogData,
} from './copy-to-folder-dialog.component';
import {FolderService} from '../../services/folder.service';
import {WorkspaceService} from '../../../services/workspace/workspace.service';
import {FolderTreeNode} from '../../models/folder.model';
import {Workspace, WorkspaceScope} from '../../models/workspace.model';
import {Component, Input} from '@angular/core';

@Component({
  selector: 'studio-button',
  template: '<button [disabled]="disabled"><ng-content></ng-content></button>',
})
class MockStudioButtonComponent {
  @Input() variant = 'primary';
  @Input() size = 'medium';
  @Input() disabled = false;
}

describe('CopyToFolderDialogComponent', () => {
  let component: CopyToFolderDialogComponent;
  let fixture: ComponentFixture<CopyToFolderDialogComponent>;
  let mockDialogRef: jasmine.SpyObj<MatDialogRef<CopyToFolderDialogComponent>>;
  let mockFolderService: jasmine.SpyObj<FolderService>;
  let mockWorkspaceService: jasmine.SpyObj<WorkspaceService>;

  const mockData: CopyToFolderDialogData = {
    workspaceId: 1,
    itemCount: 2,
    copyingFolderIds: [10],
    currentFolderId: 10,
  };

  const mockFolderTree: FolderTreeNode[] = [
    {
      id: 10,
      name: 'Folder A',
      parentId: null,
      color: '#FF0000',
      children: [
        {
          id: 11,
          name: 'Folder A.1',
          parentId: 10,
          color: null,
          children: [],
        },
      ],
    },
    {
      id: 20,
      name: 'Folder B',
      parentId: null,
      color: '#00FF00',
      children: [],
    },
  ];

  const mockWorkspaces: Workspace[] = [
    {
      id: 1,
      name: 'Workspace 1 (Current)',
      ownerId: 'user-1',
      scope: WorkspaceScope.PUBLIC,
      members: [],
      memberIds: ['user-1'],
    },
    {
      id: 2,
      name: 'Workspace 2',
      ownerId: 'user-2',
      scope: WorkspaceScope.PRIVATE,
      members: [],
      memberIds: ['user-2'],
    },
  ];

  beforeEach(async () => {
    mockDialogRef = jasmine.createSpyObj('MatDialogRef', ['close']);
    mockFolderService = jasmine.createSpyObj('FolderService', [
      'getFolderTree',
    ]);
    mockWorkspaceService = jasmine.createSpyObj('WorkspaceService', [
      'getWorkspaces',
    ]);

    mockFolderService.getFolderTree.and.returnValue(of(mockFolderTree));
    mockWorkspaceService.getWorkspaces.and.returnValue(of(mockWorkspaces));
    (mockFolderService as any).maxDepth = 20;

    await TestBed.configureTestingModule({
      declarations: [CopyToFolderDialogComponent, MockStudioButtonComponent],
      imports: [MatDialogModule, MatIconModule, MatTabsModule, FormsModule],
      providers: [
        {provide: MatDialogRef, useValue: mockDialogRef},
        {provide: MAT_DIALOG_DATA, useValue: mockData},
        {provide: FolderService, useValue: mockFolderService},
        {provide: WorkspaceService, useValue: mockWorkspaceService},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(CopyToFolderDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create and load folder tree & workspaces', () => {
    expect(component).toBeTruthy();
    expect(component.isLoading).toBeFalse();
    // Options include root + Folder A + Folder A.1 + Folder B
    expect(component.folderOptions.length).toBe(4);
    expect(component.folderOptions[0].id).toBeNull();
    expect(component.folderOptions[0].name).toBe('Gallery Root (Top Level)');
    // Workspace options include 2 workspaces, current workspace is disabled
    expect(component.workspaceOptions.length).toBe(2);
    expect(component.workspaceOptions[0].disabled).toBeTrue();
    expect(component.workspaceOptions[1].disabled).toBeFalse();
  });

  it('should handle error when loading folders', () => {
    mockFolderService.getFolderTree.and.returnValue(
      throwError(() => new Error('Failed')),
    );
    component.loadFolders();
    expect(component.isLoading).toBeFalse();
  });

  it('should disable folders if copying exceeds max depth', () => {
    // maxDepth = 2, and copyingFolder subtree height = 2 (Folder 10 has child 11)
    (mockFolderService as any).maxDepth = 2;
    component.loadFolders();
    // depth 1 + height 2 = 3 > 2 => depth 1 folders should be disabled
    const folderB = component.folderOptions.find(f => f.id === 20);
    expect(folderB?.disabled).toBeTrue();
    expect(folderB?.disabledReason).toContain('Max depth (2) reached');
  });

  it('should filter folder options by search query', () => {
    component.searchQuery = 'A.1';
    expect(component.filteredOptions.length).toBe(1);
    expect(component.filteredOptions[0].name).toBe('Folder A.1');
  });

  it('should filter workspace options by search query', () => {
    component.searchQuery = 'Workspace 2';
    expect(component.filteredWorkspaces.length).toBe(1);
    expect(component.filteredWorkspaces[0].name).toBe('Workspace 2');
  });

  it('should select a valid folder option', () => {
    const option = component.folderOptions[0]; // Root
    component.selectOption(option);
    expect(component.selectedDestinationId).toBeNull();
  });

  it('should not select a disabled folder option', () => {
    const disabledOption = {
      id: 99,
      name: 'Disabled Folder',
      depth: 1,
      disabled: true,
    };
    component.selectOption(disabledOption);
    expect(component.selectedDestinationId).toBeUndefined();
  });

  it('should select a valid workspace option', () => {
    const workspace = component.workspaceOptions[1]; // Workspace 2
    component.selectWorkspace(workspace);
    expect(component.selectedDestinationId).toBe(2);
  });

  it('should not select a disabled workspace option', () => {
    const disabledWorkspace = component.workspaceOptions[0]; // Workspace 1 (current)
    component.selectWorkspace(disabledWorkspace);
    expect(component.selectedDestinationId).toBeUndefined();
  });

  it('should reset selectedDestinationId when changing tab', () => {
    component.selectedDestinationId = 20;
    component.onSelectedTabChange({index: 1, tab: {} as any});
    expect(component.selectedTabIndex).toBe(1);
    expect(component.selectedDestinationId).toBeUndefined();
    expect(component.selectedTab).toBe('workspace');
    expect(component.placeholderText).toBe('Filter workspaces...');
  });

  it('should confirm folder copy selection', () => {
    component.selectedDestinationId = 20;
    component.confirm();
    expect(mockDialogRef.close).toHaveBeenCalledWith({
      destinationWorkspaceId: undefined,
      destinationFolderId: 20,
      destinationName: 'Folder B',
    });
  });

  it('should confirm workspace copy selection', () => {
    component.selectedTabIndex = 1;
    component.selectedDestinationId = 2;
    component.confirm();
    expect(mockDialogRef.close).toHaveBeenCalledWith({
      destinationWorkspaceId: 2,
      destinationFolderId: undefined,
      destinationName: 'Workspace 2',
    });
  });

  it('should not confirm if nothing is selected', () => {
    component.selectedDestinationId = undefined;
    component.confirm();
    expect(mockDialogRef.close).not.toHaveBeenCalled();
  });

  it('should close dialog on close()', () => {
    component.close();
    expect(mockDialogRef.close).toHaveBeenCalledWith();
  });
});
