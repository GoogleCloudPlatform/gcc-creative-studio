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

import {
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
} from '@angular/core/testing';
import {Clipboard} from '@angular/cdk/clipboard';
import {provideRouter} from '@angular/router';
import {provideHttpClient} from '@angular/common/http';
import {provideHttpClientTesting} from '@angular/common/http/testing';
import {MatDialogModule} from '@angular/material/dialog';
import {MatMenuModule} from '@angular/material/menu';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatTooltipModule} from '@angular/material/tooltip';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {
  CUSTOM_ELEMENTS_SCHEMA,
  NO_ERRORS_SCHEMA,
  NgZone,
  SimpleChange,
} from '@angular/core';

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
      schemas: [CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA],
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

  const mountAudioItem = (
    overrides: Record<string, any>,
    triggerOnChanges = false,
  ): HTMLElement => {
    component.mediaItem = {
      id: 44,
      workspaceId: 1,
      mimeType: 'audio/mpeg',
      presignedUrls: ['https://example.com/a.mp3'],
      ...overrides,
    } as any;
    component.selectedIndex = 0;
    if (triggerOnChanges) {
      component.ngOnChanges({
        mediaItem: new SimpleChange(null, component.mediaItem, true),
      });
    }
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  describe('audio lyrics, song structure & iterate action', () => {
    beforeEach(() => {
      mountAudioItem({
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
      });
    });

    it('displays lyrics and structure for the selected track and updates on track switch', () => {
      expect(component.hasCurrentTrackText()).toBeTrue();
      expect(component.currentTrackLyrics()).toBe('[Verse 1]\nNeon skyline');
      expect(component.currentTrackStructureEntries()).toEqual([
        {label: 'Tempo', value: '124 BPM'},
        {label: 'Verse 1', value: '0:00-0:15'},
      ]);

      const host = fixture.nativeElement as HTMLElement;
      expect(host.querySelector('.audio-lyrics-panel')?.textContent).toContain(
        'Neon skyline',
      );

      component.selectedIndex = 1;
      fixture.detectChanges();
      expect(component.hasCurrentTrackText()).toBeFalse();
      expect(host.querySelector('.audio-lyrics-panel')).toBeNull();
    });

    it('copies formatted structure and lyrics to the clipboard', () => {
      const copySpy = spyOn(TestBed.inject(Clipboard), 'copy');
      component.copyCurrentTrackText();
      expect(copySpy).toHaveBeenCalledWith(
        'Tempo: 124 BPM\nVerse 1: 0:00-0:15\n\n[Verse 1]\nNeon skyline',
      );
    });

    it('keeps structure chip DOM nodes stable across change detection', () => {
      const host = fixture.nativeElement as HTMLElement;
      const before = Array.from(host.querySelectorAll('.structure-chip'));
      expect(before.length).toBe(2);

      fixture.detectChanges();
      fixture.detectChanges();

      const after = Array.from(host.querySelectorAll('.structure-chip'));
      expect(after.length).toBe(2);
      after.forEach((chip, i) => expect(chip).toBe(before[i]));
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
      const host = mountAudioItem({
        id: 45,
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
      });

      expect(component.currentTrackLyrics()).toBe(
        '[0.0:5.3] Darkness descends',
      );
      expect(component.currentTrackCaption()).toBe(
        'Maximalist Symphonic Metal wall of sound.',
      );
      expect(component.currentTrackStructureEntries()).toEqual([
        {label: 'Mosic', value: '4.5'},
        {label: 'BPM', value: '90'},
      ]);
      expect(host.querySelector('.lyrics-text')?.textContent).toBe(
        '[0.0:5.3] Darkness descends',
      );
      expect(host.querySelector('.structure-caption')?.textContent).toContain(
        'Maximalist Symphonic Metal wall of sound.',
      );
    });

    it('shows raw_text verbatim instead of parsing it when the backend sent no lyrics or structure', () => {
      const rawText = '[0.0:5.3] Darkness descends\n\nBPM: 90.0';
      mountAudioItem({
        id: 46,
        presignedUrls: ['https://example.com/raw.mp3'],
        audioAnalysis: {tracks: [{raw_text: rawText}]},
      });

      expect(component.currentTrackLyrics()).toBe(rawText);
      expect(component.currentTrackStructureEntries()).toEqual([]);
      expect(component.currentTrackCaption()).toBeNull();
    });

    it('renders collapsible song-structure blocks with vocals, captions, timestamp seeking, and formatted copy', () => {
      const host = mountAudioItem({
        id: 215,
        prompt: 'Slide Drift',
        presignedUrls: ['https://example.com/slide-drift.mp3'],
        audioAnalysis: {
          tracks: [
            {
              lyrics: '[Intro 0]\n(yeah, slide, drift)',
              duration_seconds: 168.9,
              structure: {
                bpm: 125,
                mosic: 4.5,
                duration_secs: 184,
                good_crop: 1,
                sections: [
                  {
                    id: 'A0',
                    letter: 'A',
                    index: 0,
                    role: 'Intro',
                    name: 'Intro 0',
                    start_seconds: 0,
                    lyrics: '(yeah, slide, drift)',
                    caption: 'A dark Drift Phonk intro.',
                  },
                  {
                    id: 'B1',
                    letter: 'B',
                    index: 1,
                    role: 'Chorus',
                    name: 'Chorus 1',
                    start_seconds: 15.4,
                    caption: 'An explosive Drift Phonk chorus.',
                  },
                ],
              },
            },
          ],
        },
      });

      // Internal flags (duration_secs, good_crop) and collapsible sections stay out of top chips
      expect(component.currentTrackStructureEntries()).toEqual([
        {label: 'BPM', value: '125'},
        {label: 'Mosic', value: '4.5'},
      ]);
      expect(host.querySelector('.lyrics-text')).toBeNull();

      const blocks = host.querySelectorAll('.section-block');
      expect(blocks.length).toBe(2);
      expect(
        blocks[0].querySelector('.section-index-badge')?.textContent?.trim(),
      ).toBe('0');
      expect(
        blocks[0].querySelector('.section-role-title')?.textContent?.trim(),
      ).toBe('Intro');
      expect(
        blocks[0].querySelector('.section-motif-badge')?.textContent?.trim(),
      ).toBe('A');
      expect(
        blocks[0].querySelector('.section-time-pill')?.textContent?.trim(),
      ).toBe('0:00 – 0:15');
      expect(blocks[0].querySelector('.section-block-body')).toBeNull();

      // Expand first block: shows vocals + caption
      (
        blocks[0].querySelector('.section-toggle-btn') as HTMLButtonElement
      ).click();
      fixture.detectChanges();
      expect(blocks[0].querySelector('.section-vocals-text')?.textContent).toBe(
        '(yeah, slide, drift)',
      );
      expect(
        blocks[0].querySelector('.section-caption-text')?.textContent,
      ).toBe('A dark Drift Phonk intro.');

      // Expand all button opens remaining instrumental section, then collapses all
      const toggleAllBtn = host.querySelector(
        '.toggle-all-sections-btn',
      ) as HTMLButtonElement;
      expect(toggleAllBtn).toBeTruthy();
      toggleAllBtn.click();
      fixture.detectChanges();
      expect(component.areAllSectionsExpanded()).toBeTrue();
      expect(
        blocks[1].querySelector('.section-instrumental-text')?.textContent,
      ).toContain('Instrumental');

      toggleAllBtn.click();
      fixture.detectChanges();
      expect(component.expandedSections().size).toBe(0);

      // Clicking timestamp pill seeks audio without expanding section
      const fakeAudio = {
        duration: 168.9,
        currentTime: 0,
        paused: false,
      } as unknown as HTMLAudioElement;
      component.audioPlayerRef = {
        nativeElement: fakeAudio,
      } as typeof component.audioPlayerRef;
      component.isPlaying = true;

      const chorusTimeBtn = blocks[1].querySelector(
        '.section-time-pill',
      ) as HTMLButtonElement;
      expect(chorusTimeBtn.textContent?.trim()).toBe('0:15 – 2:48');
      chorusTimeBtn.click();
      fixture.detectChanges();
      expect(fakeAudio.currentTime).toBe(15.4);
      expect(component.isSectionExpanded(1)).toBeFalse();
      expect(blocks[1].classList.contains('is-playing')).toBeTrue();

      const copySpy = spyOn(TestBed.inject(Clipboard), 'copy');
      component.copyCurrentTrackText();
      expect(copySpy).toHaveBeenCalledWith(
        'BPM: 125\nMosic: 4.5\n\n' +
          '[Intro 0] (0:00 – 0:15)\nVocals:\n(yeah, slide, drift)\nCaption: A dark Drift Phonk intro.\n\n' +
          '[Chorus 1] (0:15 – 2:48)\nCaption: An explosive Drift Phonk chorus.',
      );
    });

    it('should hide Iterate button for Chirp and Gemini TTS audio items', () => {
      const sub = component.iterateAudioClicked.subscribe();
      const host = fixture.nativeElement as HTMLElement;

      for (const ttsModel of [
        'chirp_3',
        'gemini-2.5-flash-tts',
        'gemini-3.1-flash-tts-preview',
      ]) {
        component.mediaItem = {
          ...(component.mediaItem as any),
          model: ttsModel,
        };
        fixture.detectChanges();
        expect(component.canIterateAudio).toBeFalse();
        expect(host.querySelector('.iterate-audio-btn')).toBeNull();
      }

      for (const musicModel of ['lyria-3-clip-preview', 'htdemucs-6s']) {
        component.mediaItem = {
          ...(component.mediaItem as any),
          model: musicModel,
        };
        fixture.detectChanges();
        expect(component.canIterateAudio).toBeTrue();
        expect(host.querySelector('.iterate-audio-btn')).not.toBeNull();
      }

      sub.unsubscribe();
    });

    it('should hide Iterate button when iterateAudioClicked output has no subscribers', () => {
      component.mediaItem = {
        ...(component.mediaItem as any),
        model: 'lyria-3-pro-preview',
      };
      fixture.detectChanges();

      const host = fixture.nativeElement as HTMLElement;
      expect(component.iterateAudioClicked.observers.length).toBe(0);
      expect(component.canIterateAudio).toBeFalse();
      expect(host.querySelector('.iterate-audio-btn')).toBeNull();
    });

    it('clears pending selectMedia audio timer on ngOnDestroy and resets isPlaying if audio.play() rejects', fakeAsync(() => {
      spyOn(console, 'warn');
      component.selectedUrl = 'https://example.com/a.mp3';
      fixture.detectChanges();
      const audioEl = component.audioPlayerRef.nativeElement;
      const loadSpy = spyOn(audioEl, 'load');
      const playSpy = spyOn(audioEl, 'play').and.returnValue(
        Promise.reject(new DOMException('Interrupted', 'AbortError')),
      );

      component.togglePlay();
      expect(component.isPlaying).toBeTrue();
      tick();
      expect(component.isPlaying).toBeFalse();

      loadSpy.calls.reset();
      playSpy.calls.reset();

      component.selectMedia(1);
      component.ngOnDestroy();
      tick(60);

      expect(loadSpy).not.toHaveBeenCalled();
      expect(playSpy).not.toHaveBeenCalled();
    }));

    it('renders Stems button for audio items, opens AudioStemMixerDialogComponent, and emits stemmedMediaCreated', () => {
      mountAudioItem({
        id: 55,
        folderId: 8,
        titles: ['Take One', 'Take Two'],
        presignedUrls: [
          'https://example.com/1.mp3',
          'https://example.com/2.mp3',
        ],
      });
      component.selectedIndex = 1;
      fixture.detectChanges();

      const stemmedResult = {
        action: 'use_as_reference' as const,
        mediaItem: {id: 777, titles: ['Take Two (Instrumental)']} as any,
      };
      const openSpy = spyOn(component.dialog, 'open').and.returnValue({
        afterClosed: () => of(stemmedResult),
      } as any);

      const emitted: any[] = [];
      component.stemmedMediaCreated.subscribe(ev => emitted.push(ev));

      const stemBtn = (fixture.nativeElement as HTMLElement).querySelector(
        '.stem-audio-btn',
      ) as HTMLElement | null;
      expect(stemBtn).toBeTruthy();
      stemBtn!.click();

      expect(openSpy).toHaveBeenCalled();
      const dialogConfig = openSpy.calls.mostRecent().args[1] as any;
      expect(dialogConfig.data).toEqual({
        workspaceId: 1,
        source: {id: 55, type: 'media_item', index: 1},
        sourceTitle: 'Take Two',
        folderId: 8,
        allowUseAsReference: true,
      });
      expect(emitted).toEqual([stemmedResult]);
    });
  });

  describe('interactive audio waveform scrubber', () => {
    it('renders backend waveform bars when present and falls back to mat-slider line when absent', () => {
      const host = mountAudioItem(
        {
          id: 80,
          prompt: 'Ambient pulse',
          presignedUrls: [
            'https://example.com/with-waveform.mp3',
            'https://example.com/legacy-no-waveform.mp3',
          ],
          audioAnalysis: {
            tracks: [
              {waveform: [0.1, 0.5, 1.0, 0.4]},
              {raw_text: 'No waveform'},
            ],
          },
        },
        true,
      );

      expect(
        host
          .querySelector('.main-media-container')
          ?.classList.contains('audio-stage-container'),
      ).toBeTrue();
      expect(component.currentTrackWaveform()).toEqual([0.1, 0.5, 1.0, 0.4]);
      expect(host.querySelector('.waveform-scrubber')).toBeTruthy();
      expect(host.querySelectorAll('.waveform-bar').length).toBe(4);
      expect(host.querySelector('mat-slider')).toBeNull();

      component.selectMedia(1);
      fixture.detectChanges();

      expect(component.currentTrackWaveform()).toBeNull();
      expect(host.querySelector('.waveform-scrubber')).toBeNull();
      expect(host.querySelector('mat-slider.custom-slider')).toBeTruthy();
    });

    it('scrubs audio position on pointer down/move and supports keyboard arrow seeking', () => {
      const host = mountAudioItem(
        {
          id: 82,
          presignedUrls: ['https://example.com/scrub.mp3'],
          audioAnalysis: {tracks: [{waveform: [0.2, 0.4, 0.8, 1.0, 0.6, 0.3]}]},
        },
        true,
      );

      const fakeAudio = {
        duration: 60,
        currentTime: 0,
        paused: true,
        play: () => Promise.resolve(),
        pause: () => {},
        load: () => {},
      } as unknown as HTMLAudioElement;
      component.audioPlayerRef = {nativeElement: fakeAudio} as any;
      component.onAudioLoaded();

      const scrubber = host.querySelector('.waveform-scrubber') as HTMLElement;
      expect(scrubber).toBeTruthy();

      spyOn(scrubber, 'getBoundingClientRect').and.returnValue({
        left: 100,
        width: 200,
        top: 0,
        right: 300,
        bottom: 40,
        height: 40,
        x: 100,
        y: 0,
        toJSON: () => ({}),
      } as DOMRect);

      scrubber.dispatchEvent(
        new PointerEvent('pointerdown', {clientX: 200, pointerId: 1}),
      );
      fixture.detectChanges();

      expect(component.isScrubbing()).toBeTrue();
      expect(component.progressValue).toBeCloseTo(50, 1);
      expect(fakeAudio.currentTime).toBeCloseTo(30, 1);
      expect(component.hoverTimeLabel()).toBe('0:30');

      scrubber.dispatchEvent(
        new PointerEvent('pointermove', {clientX: 250, pointerId: 1}),
      );
      expect(component.progressValue).toBeCloseTo(75, 1);
      expect(fakeAudio.currentTime).toBeCloseTo(45, 1);

      scrubber.dispatchEvent(
        new PointerEvent('pointerup', {clientX: 250, pointerId: 1}),
      );
      expect(component.isScrubbing()).toBeFalse();

      scrubber.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowLeft'}));
      expect(component.progressValue).toBeCloseTo(70, 1);
      expect(fakeAudio.currentTime).toBeCloseTo(42, 1);
    });

    it('keeps 120 waveform bars strictly inside the scrubber bounds and aligned with the playhead', () => {
      const bars120 = Array.from(
        {length: 120},
        (_, idx) => 0.1 + ((idx % 10) / 10) * 0.9,
      );
      const host = mountAudioItem(
        {
          id: 83,
          presignedUrls: ['https://example.com/120bars.mp3'],
          audioAnalysis: {tracks: [{waveform: bars120}]},
        },
        true,
      );
      component.progressValue = 50;
      const player = host.querySelector('.custom-audio-player') as HTMLElement;
      player.style.width = '520px';
      fixture.detectChanges();

      const scrubberRect = (
        host.querySelector('.waveform-scrubber') as HTMLElement
      ).getBoundingClientRect();
      const barsRect = (
        host.querySelector('.waveform-bars') as HTMLElement
      ).getBoundingClientRect();
      const playheadRect = (
        host.querySelector('.waveform-playhead') as HTMLElement
      ).getBoundingClientRect();
      const barEls = host.querySelectorAll('.waveform-bar');

      expect(barEls.length).toBe(120);
      expect(barsRect.right).toBeLessThanOrEqual(scrubberRect.right + 0.5);
      expect(barEls[119].getBoundingClientRect().right).toBeLessThanOrEqual(
        scrubberRect.right + 0.5,
      );

      const playheadCenter = playheadRect.left + playheadRect.width / 2;
      expect(
        Math.abs(playheadCenter - barEls[59].getBoundingClientRect().right),
      ).toBeLessThan(3);
    });

    it('animates the playhead outside Angular without touching change-detected state', () => {
      const host = mountAudioItem(
        {
          id: 84,
          presignedUrls: ['https://example.com/smooth.mp3'],
          audioAnalysis: {tracks: [{waveform: [0.2, 0.6, 1.0, 0.4]}]},
        },
        true,
      );

      component.audioPlayerRef = {
        nativeElement: {duration: 60, currentTime: 15, paused: false},
      } as any;

      const scheduledInAngularZone: boolean[] = [];
      let step: FrameRequestCallback | undefined;
      spyOn(window, 'requestAnimationFrame').and.callFake(cb => {
        scheduledInAngularZone.push(NgZone.isInAngularZone());
        step = cb;
        return 1;
      });
      const cancelSpy = spyOn(window, 'cancelAnimationFrame');

      TestBed.inject(NgZone).run(() => component.onAudioPlay());
      expect(scheduledInAngularZone).toEqual([false]);

      step!(0);

      const playhead = host.querySelector('.waveform-playhead') as HTMLElement;
      expect(playhead.style.left).toBe('25%');
      expect(component.progressValue).toBe(0);
      expect(component.currentTime).toBe('0:00');

      component.onAudioPause();
      expect(cancelSpy).toHaveBeenCalledWith(1);
    });
  });
});
