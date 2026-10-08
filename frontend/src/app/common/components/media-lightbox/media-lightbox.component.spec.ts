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
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';

import {MediaLightboxComponent} from './media-lightbox.component';
import {TagsService} from '../../services/tags.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {FolderService} from '../../services/folder.service';
import {of, throwError} from 'rxjs';

describe('MediaLightboxComponent', () => {
  let component: MediaLightboxComponent;
  let fixture: ComponentFixture<MediaLightboxComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [MediaLightboxComponent],
      imports: [MatDialogModule, MatSnackBarModule, NoopAnimationsModule],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: TagsService,
          useValue: {},
        },
        {
          provide: WorkspaceStateService,
          useValue: {
            getActiveWorkspaceId: () => 1,
          },
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

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
  });
});
