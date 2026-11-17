/**
 * Copyright 2025 Google LLC
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
import {provideRouter} from '@angular/router';
import {provideHttpClient} from '@angular/common/http';
import {provideHttpClientTesting} from '@angular/common/http/testing';
import {MatDialogModule} from '@angular/material/dialog';
import {MatMenuModule} from '@angular/material/menu';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatTooltipModule} from '@angular/material/tooltip';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';

import {MediaLightboxComponent} from './media-lightbox.component';
import {TagsService} from '../../services/tags.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {FolderService} from '../../services/folder.service';
import {GalleryService} from '../../../gallery/gallery.service';
import {UserService} from '../../services/user.service';
import {WorkspaceScope} from '../../models/workspace.model';
import {WorkspaceRole} from '../../models/workspace-member.model';
import {PromoteLauncherService} from '../../services/promote-launcher.service';
import {MatDialogRef} from '@angular/material/dialog';
import {of, throwError} from 'rxjs';

describe('MediaLightboxComponent', () => {
  let component: MediaLightboxComponent;
  let fixture: ComponentFixture<MediaLightboxComponent>;
  let workspaceStateService: WorkspaceStateService;
  let mockUserDetails: {id: number; roles: string[]};

  beforeEach(async () => {
    mockUserDetails = {id: 7, roles: []};
    await TestBed.configureTestingModule({
      declarations: [MediaLightboxComponent],
      imports: [
        MatDialogModule,
        MatMenuModule,
        MatSnackBarModule,
        MatTooltipModule,
        NoopAnimationsModule,
      ],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: TagsService,
          useValue: {bulkAssign: () => of(null)},
        },
        {
          provide: GalleryService,
          useValue: {
            bulkMove: jasmine.createSpy('bulkMove').and.returnValue(of({})),
          },
        },
        {
          provide: UserService,
          useValue: {getUserDetails: () => mockUserDetails},
        },
        WorkspaceStateService,
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    workspaceStateService = TestBed.inject(WorkspaceStateService);
    workspaceStateService.setWorkspaces([
      {
        id: 1,
        name: 'My Workspace',
        ownerId: '7',
        scope: WorkspaceScope.PERSONAL,
        members: [],
        memberIds: ['7'],
      },
      {
        id: 20,
        name: 'Team Viewer',
        ownerId: '99',
        scope: WorkspaceScope.PRIVATE,
        currentUserRole: WorkspaceRole.VIEWER,
        members: [],
        memberIds: ['7', '99'],
      },
      {
        id: 30,
        name: 'Team Editor',
        ownerId: '99',
        scope: WorkspaceScope.PRIVATE,
        currentUserRole: WorkspaceRole.EDITOR,
        members: [],
        memberIds: ['7', '99'],
      },
    ]);
    workspaceStateService.setActiveWorkspaceId(1);

    fixture = TestBed.createComponent(MediaLightboxComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('move to folder', () => {
    beforeEach(() => {
      component.mediaItem = {
        id: 9,
        workspaceId: 1,
        folderId: 2,
        itemType: 'media_item',
        createdAt: '2026-01-01T00:00:00Z',
      } as any;
    });

    it('emits `moved` with the destination folder after a successful move', () => {
      const folderService = TestBed.inject(FolderService);
      spyOn(folderService, 'moveItems').and.returnValue(of({total_moved: 1}));
      const emitted: Array<number | null> = [];
      component.moved.subscribe(id => emitted.push(id));

      component['executeMove'](1, 5, 'Campaigns');

      expect(folderService.moveItems).toHaveBeenCalledWith(
        jasmine.objectContaining({
          workspaceId: 1,
          mediaItemIds: [9],
          sourceAssetIds: [],
          destinationFolderId: 5,
        }),
      );
      expect(component.mediaItem?.folderId).toBe(5);
      expect(emitted).toEqual([5]);
    });

    it('does not emit `moved` when the move fails or is a no-op', () => {
      const folderService = TestBed.inject(FolderService);
      const moveSpy = spyOn(folderService, 'moveItems').and.returnValue(
        throwError(() => new Error('boom')),
      );
      spyOn(console, 'error');
      const emitted: Array<number | null> = [];
      component.moved.subscribe(id => emitted.push(id));

      component['executeMove'](1, 5, 'Campaigns');
      expect(emitted).toEqual([]);

      // Same folder → nothing is sent and nothing is emitted.
      moveSpy.calls.reset();
      component['executeMove'](1, 2, 'Same');
      expect(moveSpy).not.toHaveBeenCalled();
      expect(emitted).toEqual([]);
    });

    it('resolves workspace-tab move destination via galleryService.bulkMove', () => {
      const galleryService = TestBed.inject(GalleryService);
      spyOn(component.dialog, 'open').and.returnValue({
        afterClosed: () =>
          of({destinationWorkspaceId: 30, destinationName: 'Team Editor'}),
      } as MatDialogRef<unknown>);
      const emitted: Array<number | null> = [];
      component.moved.subscribe(id => emitted.push(id));

      component.openBatchMoveDialog();

      expect(galleryService.bulkMove).toHaveBeenCalledWith(
        [{id: 9, type: 'media_item'}],
        30,
      );
      expect(component.mediaItem?.workspaceId).toBe(30);
      expect(emitted).toEqual([null]);
    });
  });

  describe('flat toolbar permission gating', () => {
    it('keeps actions flat and hides move/tags/delete for shared VIEWER items', () => {
      component.showMoveButton = true;
      component.showDeleteButton = true;
      component.mediaItem = {
        id: 11,
        workspaceId: 20, // Team Viewer
        itemType: 'media_item',
        mimeType: 'image/png',
        presignedUrls: ['https://example.com/img.png'],
        createdAt: '2026-01-01T00:00:00Z',
      } as any;
      fixture.detectChanges();

      expect(component.canEditItemWorkspace).toBeFalse();
      const root = fixture.nativeElement as HTMLElement;
      expect(root.querySelector('#lightbox-more-actions-btn')).toBeNull();
      expect(
        root.querySelector('[matTooltip="Edit this media"]'),
      ).not.toBeNull();
      expect(root.querySelector('[matTooltip="Move to folder"]')).toBeNull();
      expect(root.querySelector('[matTooltip="Assign tags"]')).toBeNull();
      expect(root.querySelector('[matTooltip="Delete"]')).toBeNull();

      // Switching to editable workspace reveals move/tags/delete inline.
      component.mediaItem = {...component.mediaItem!, workspaceId: 30} as any;
      fixture.detectChanges();
      expect(component.canEditItemWorkspace).toBeTrue();
      expect(
        root.querySelector('[matTooltip="Move to folder"]'),
      ).not.toBeNull();
      expect(root.querySelector('[matTooltip="Assign tags"]')).not.toBeNull();
      expect(root.querySelector('[matTooltip="Delete"]')).not.toBeNull();
    });

    it('defaults showWorkspacePromoteBar to false and renders bar only when enabled for personal items', () => {
      const promoteLauncher = TestBed.inject(PromoteLauncherService);
      const mockPromoResult = {
        response: {
          targetWorkspaceId: 30,
          promotedCount: 1,
          createdCount: 1,
          updatedCount: 0,
          promotedItems: [],
        },
        targetWorkspaceName: 'Team Editor',
      };
      const openSpy = spyOn(
        promoteLauncher,
        'openPromoteDialog',
      ).and.returnValue(of(mockPromoResult));

      expect(component.showWorkspacePromoteBar).toBeFalse();
      component.mediaItem = {
        id: 12,
        workspaceId: 1,
        itemType: 'media_item',
        mimeType: 'image/png',
        prompt: 'Personal Draft',
        presignedUrls: ['https://example.com/p.png'],
        createdAt: '2026-01-01T00:00:00Z',
      } as any;
      fixture.detectChanges();
      expect(
        fixture.nativeElement.querySelector('#lightbox-promote-btn'),
      ).toBeNull();

      component.showWorkspacePromoteBar = true;
      fixture.detectChanges();

      const promoteBtn = fixture.nativeElement.querySelector(
        '#lightbox-promote-btn',
      ) as HTMLButtonElement;
      expect(promoteBtn).not.toBeNull();

      let emitted: unknown = null;
      component.promoted.subscribe(r => (emitted = r));
      promoteBtn.click();

      expect(openSpy).toHaveBeenCalledWith({
        sourceWorkspaceId: 1,
        items: [{id: 12, type: 'media_item'}],
        itemLabel: 'Personal Draft',
      });
      expect(emitted).toEqual(mockPromoResult);

      component.mediaItem = {...component.mediaItem!, workspaceId: 20} as any;
      fixture.detectChanges();
      expect(
        fixture.nativeElement.querySelector('#lightbox-promote-btn'),
      ).toBeNull();
    });
  });
});
