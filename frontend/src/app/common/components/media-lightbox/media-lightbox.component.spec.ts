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

  describe('audio lyrics & song structure', () => {
    beforeEach(() => {
      mountAudioItem({
        prompt: 'Synthwave song',
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
