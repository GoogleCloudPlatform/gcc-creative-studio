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
import {CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA} from '@angular/core';
import {Clipboard} from '@angular/cdk/clipboard';

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
          useValue: {},
        },
        {
          provide: WorkspaceStateService,
          useValue: {
            getActiveWorkspaceId: () => 1,
          },
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA],
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

  describe('audio lyrics, song structure & iterate action', () => {
    beforeEach(() => {
      component.mediaItem = {
        id: 44,
        workspaceId: 1,
        mimeType: 'audio/mpeg',
        prompt: 'Synthwave anthem',
        presignedUrls: [
          'https://example.com/a.mp3',
          'https://example.com/b.mp3',
        ],
        audioAnalysis: {
          tracks: [
            {
              raw_text: '[Verse 1]\nNeon skyline',
              lyrics: '[Verse 1]\nNeon skyline',
              structure: {
                tempo: '124 BPM',
                sections: [{name: 'Verse 1', duration: '0:00-0:15'}],
              },
            },
            null,
          ],
        },
      } as any;
      component.selectedIndex = 0;
      fixture.detectChanges();
    });

    it('displays lyrics and structure for the selected track and updates on track switch', () => {
      expect(component.hasCurrentTrackText).toBeTrue();
      expect(component.currentTrackLyrics).toBe('[Verse 1]\nNeon skyline');
      expect(component.currentTrackStructureEntries).toEqual([
        {label: 'Tempo', value: '124 BPM'},
        {label: 'Verse 1', value: '0:00-0:15'},
      ]);

      const host = fixture.nativeElement as HTMLElement;
      expect(host.querySelector('.audio-lyrics-panel')?.textContent).toContain(
        'Neon skyline',
      );

      component.selectedIndex = 1;
      fixture.detectChanges();
      expect(component.hasCurrentTrackText).toBeFalse();
      expect(host.querySelector('.audio-lyrics-panel')).toBeNull();
    });

    it('copies formatted structure and lyrics to the clipboard', () => {
      const copySpy = spyOn(TestBed.inject(Clipboard), 'copy');
      component.copyCurrentTrackText();
      expect(copySpy).toHaveBeenCalledWith(
        'Tempo: 124 BPM\nVerse 1: 0:00-0:15\n\n[Verse 1]\nNeon skyline',
      );
    });

    it('renders Iterate action for audio clips without rendering Omni video button', () => {
      const emitted: Array<{mediaItem: any; selectedIndex: number}> = [];
      component.iterateAudioClicked.subscribe(evt => emitted.push(evt));

      component.selectedIndex = 1;
      fixture.detectChanges();

      const host = fixture.nativeElement as HTMLElement;
      const iterateBtn = host.querySelector(
        '.iterate-audio-btn',
      ) as HTMLElement | null;
      expect(iterateBtn).not.toBeNull();

      const omniBtn = Array.from(host.querySelectorAll('studio-button')).find(
        btn => btn.textContent?.includes('Omni'),
      );
      expect(omniBtn).toBeUndefined();

      iterateBtn!.click();
      expect(emitted).toEqual([
        {mediaItem: component.mediaItem, selectedIndex: 1},
      ]);

      component.showIterateAudio = false;
      fixture.detectChanges();
      expect(host.querySelector('.iterate-audio-btn')).toBeNull();
    });

    it('renders backend-parsed Caption, Mosic and BPM separately from timestamped lyrics', () => {
      component.mediaItem = {
        id: 45,
        workspaceId: 1,
        mimeType: 'audio/mpeg',
        prompt: 'Stormy symphonic metal',
        presignedUrls: ['https://example.com/storm.mp3'],
        audioAnalysis: {
          tracks: [
            {
              raw_text:
                '[0.0:5.3] Darkness descends\n\nCaption: Maximalist Symphonic Metal wall of sound.\nMosic: 4.5\nBPM: 90.0',
              lyrics: '[0.0:5.3] Darkness descends',
              structure: {
                caption: 'Maximalist Symphonic Metal wall of sound.',
                mosic: 4.5,
                bpm: 90,
              },
            },
          ],
        },
      } as any;
      component.selectedIndex = 0;
      fixture.detectChanges();

      const host = fixture.nativeElement as HTMLElement;
      expect(component.currentTrackCaption).toBe(
        'Maximalist Symphonic Metal wall of sound.',
      );
      expect(component.currentTrackStructureEntries).toEqual([
        {label: 'Mosic', value: '4.5'},
        {label: 'BPM', value: '90'},
      ]);
      expect(host.querySelector('.structure-caption')?.textContent).toContain(
        'Maximalist Symphonic Metal wall of sound.',
      );
    });
  });
});
