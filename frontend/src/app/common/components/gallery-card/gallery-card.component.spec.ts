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
import {RouterTestingModule} from '@angular/router/testing';
import {MatDialogModule} from '@angular/material/dialog';
import {MatIconModule} from '@angular/material/icon';
import {MatChipsModule} from '@angular/material/chips';
import {NO_ERRORS_SCHEMA} from '@angular/core';
import {of} from 'rxjs';

import {GalleryCardComponent} from './gallery-card.component';
import {UserService} from '../../services/user.service';
import {GalleryItem} from '../../models/gallery-item.model';
import {GalleryService} from '../../../gallery/gallery.service';

describe('GalleryCardComponent', () => {
  let component: GalleryCardComponent;
  let fixture: ComponentFixture<GalleryCardComponent>;
  let mockGalleryService: jasmine.SpyObj<GalleryService>;

  const mockItem: GalleryItem = {
    id: 42,
    workspaceId: 1,
    itemType: 'media_item',
    createdAt: '2026-01-01',
    metadata: {
      prompt: 'A futuristic city in the clouds',
    },
    presignedUrls: ['https://example.com/image.png'],
    presignedThumbnailUrls: ['https://example.com/thumb.png'],
    mimeType: 'image/png',
  };

  beforeEach(async () => {
    mockGalleryService = jasmine.createSpyObj('GalleryService', [
      'getAudioAnalysis',
    ]);
    mockGalleryService.getAudioAnalysis.and.returnValue(of(null));

    await TestBed.configureTestingModule({
      declarations: [GalleryCardComponent],
      imports: [
        RouterTestingModule,
        MatDialogModule,
        MatIconModule,
        MatChipsModule,
      ],
      schemas: [NO_ERRORS_SCHEMA],
      providers: [
        {
          provide: UserService,
          useValue: {
            getUserDetails: () => ({email: 'user@example.com', roles: []}),
          },
        },
        {
          provide: GalleryService,
          useValue: mockGalleryService,
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(GalleryCardComponent);
    component = fixture.componentInstance;
    component.item = mockItem;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should set drag data on onDragStart for single item', () => {
    let setDataCall: {type: string; data: string} | null = null;
    const mockEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      stopPropagation: jasmine.createSpy('stopPropagation'),
      dataTransfer: {
        setData: (type: string, data: string) => {
          setDataCall = {type, data};
        },
        setDragImage: jasmine.createSpy('setDragImage'),
        effectAllowed: '',
      },
    } as unknown as DragEvent;

    component.onDragStart(mockEvent);

    expect(component.isDragging).toBeTrue();
    expect(setDataCall).not.toBeNull();
    expect(setDataCall!.type).toBe('application/json');
    const parsed = JSON.parse(setDataCall!.data);
    expect(parsed.mediaItemIds).toEqual([42]);
    expect(parsed.itemCount).toBe(1);
  });

  it('should set drag data for multi-selected items if item is selected', () => {
    component.isSelected = true;
    component.selectedItems = new Set([
      'media_item:42',
      'media_item:43',
      'source_asset:10',
    ]);

    let setDataCall: {type: string; data: string} | null = null;
    const mockEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      stopPropagation: jasmine.createSpy('stopPropagation'),
      dataTransfer: {
        setData: (type: string, data: string) => {
          setDataCall = {type, data};
        },
        setDragImage: jasmine.createSpy('setDragImage'),
        effectAllowed: '',
      },
    } as unknown as DragEvent;

    component.onDragStart(mockEvent);

    expect(component.isDragging).toBeTrue();
    expect(setDataCall).not.toBeNull();
    const parsed = JSON.parse(setDataCall!.data);
    expect(parsed.mediaItemIds).toContain(42);
    expect(parsed.mediaItemIds).toContain(43);
    expect(parsed.sourceAssetIds).toContain(10);
    expect(parsed.itemCount).toBe(3);
  });

  it('should reset isDragging on onDragEnd', () => {
    component.isDragging = true;
    component.onDragEnd({} as DragEvent);
    expect(component.isDragging).toBeFalse();
  });

  it('lazily loads backend waveform, track length, and BPM only on hover and hides them on mouse leave', () => {
    mockGalleryService.getAudioAnalysis.and.returnValue(
      of({
        tracks: [
          {
            waveform: [0.25, 0.5, 0.9, 0.4],
            duration_seconds: 29.8,
            structure: {bpm: 90},
          },
          {
            musical_profile: {bpm: 124},
          },
        ],
      }),
    );

    component.item = {
      id: 99,
      workspaceId: 1,
      itemType: 'media_item',
      createdAt: '2026-01-01',
      mimeType: 'audio/mpeg',
      presignedUrls: [
        'https://example.com/take1.mp3',
        'https://example.com/take2.mp3',
      ],
      metadata: {
        isAudio: true,
        mimeType: 'audio/mpeg',
      },
    };
    component.currentImageIndex = 0;
    fixture.detectChanges();

    const host: HTMLElement = fixture.nativeElement;
    // Before hover: no API call, shows graphic_eq icon, no hover meta pill
    expect(mockGalleryService.getAudioAnalysis).not.toHaveBeenCalled();
    expect(host.querySelector('.audio-card-waveform')).toBeNull();
    expect(host.querySelector('.audio-hover-meta')).toBeNull();
    expect(
      host.querySelector('.audio-card-preview mat-icon')?.textContent?.trim(),
    ).toBe('graphic_eq');

    // Hover: fetches once and renders waveform bars + duration + BPM
    component.onMouseEnter();
    fixture.detectChanges();

    expect(mockGalleryService.getAudioAnalysis).toHaveBeenCalledOnceWith(99);
    expect(host.querySelectorAll('.audio-card-waveform-bar').length).toBe(4);
    expect(host.querySelector('.audio-card-preview mat-icon')).toBeNull();
    const metaText = host.querySelector('.audio-hover-meta')?.textContent ?? '';
    expect(metaText).toContain('0:30');
    expect(metaText).toContain('90 BPM');

    // Advance to take 2 (no waveform, musical_profile BPM 124) while hovered
    component.nextImageItem(new MouseEvent('click'));
    fixture.detectChanges();
    expect(host.querySelector('.audio-card-waveform')).toBeNull();
    expect(
      host.querySelector('.audio-card-preview mat-icon')?.textContent?.trim(),
    ).toBe('graphic_eq');
    expect(host.querySelector('.audio-hover-meta')?.textContent).toContain(
      '124 BPM',
    );

    // Switch back to take 1, then leave hover -> hides waveform and meta without re-fetching
    component.prevImageItem(new MouseEvent('click'));
    fixture.detectChanges();
    expect(host.querySelectorAll('.audio-card-waveform-bar').length).toBe(4);

    component.onMouseLeave();
    fixture.detectChanges();
    expect(host.querySelector('.audio-card-waveform')).toBeNull();
    expect(host.querySelector('.audio-hover-meta')).toBeNull();
    expect(
      host.querySelector('.audio-card-preview mat-icon')?.textContent?.trim(),
    ).toBe('graphic_eq');

    // Re-hover: uses cached signal without calling API again and never mutates @Input item
    component.onMouseEnter();
    fixture.detectChanges();
    expect(mockGalleryService.getAudioAnalysis).toHaveBeenCalledTimes(1);
    expect(component.item.audioAnalysis).toBeUndefined();
    expect(host.querySelectorAll('.audio-card-waveform-bar').length).toBe(4);
  });

  it('does not fetch audioAnalysis for source_asset audio and supports probed metadata duration on hover', () => {
    component.item = {
      id: 100,
      workspaceId: 1,
      itemType: 'source_asset',
      createdAt: '2026-01-01',
      mimeType: 'audio/wav',
      presignedUrls: ['https://example.com/upload.wav'],
      metadata: {
        isAudio: true,
        mimeType: 'audio/wav',
      },
    };
    fixture.detectChanges();

    component.onMouseEnter();
    // Simulate browser loadedmetadata callback resolving track duration
    component.probedTrackDurations.set({0: 83.2});
    fixture.detectChanges();

    const host: HTMLElement = fixture.nativeElement;
    expect(mockGalleryService.getAudioAnalysis).not.toHaveBeenCalled();
    expect(host.querySelector('.audio-card-waveform')).toBeNull();
    const fallbackIcon = host.querySelector('.audio-card-preview mat-icon');
    expect(fallbackIcon?.textContent?.trim()).toBe('graphic_eq');
    expect(host.querySelector('.audio-hover-meta')?.textContent?.trim()).toBe(
      '1:23',
    );
  });

  it('retries getAudioAnalysis on subsequent hover after null response and cancels unresolved metadata probe on mouse leave', () => {
    const createdAudios: Array<{
      preload: string;
      src: string;
      duration: number;
      onloadedmetadata: (() => void) | null;
      onerror: (() => void) | null;
      removeAttribute: jasmine.Spy;
      load: jasmine.Spy;
    }> = [];
    const OriginalAudio = (window as any).Audio;
    (window as any).Audio = function MockAudio() {
      const mock = {
        preload: '',
        src: '',
        duration: 45,
        onloadedmetadata: null,
        onerror: null,
        removeAttribute: jasmine.createSpy('removeAttribute'),
        load: jasmine.createSpy('load'),
      };
      createdAudios.push(mock);
      return mock;
    };

    try {
      mockGalleryService.getAudioAnalysis.and.returnValues(
        of(null),
        of({tracks: [{waveform: [0.3, 0.7], duration_seconds: 12}]}),
      );

      component.item = {
        id: 101,
        workspaceId: 1,
        itemType: 'media_item',
        createdAt: '2026-01-01',
        mimeType: 'audio/mpeg',
        presignedUrls: ['https://example.com/tts.mp3'],
        metadata: {isAudio: true, mimeType: 'audio/mpeg'},
      };
      fixture.detectChanges();

      // First hover: getAudioAnalysis emits null -> probes metadata duration
      component.onMouseEnter();
      expect(mockGalleryService.getAudioAnalysis).toHaveBeenCalledTimes(1);
      expect(createdAudios.length).toBe(1);

      // Leave before metadata loads -> cancels probe and clears probed index
      component.onMouseLeave();
      expect(createdAudios[0].removeAttribute).toHaveBeenCalledWith('src');
      expect(createdAudios[0].load).toHaveBeenCalled();

      // Second hover: retries getAudioAnalysis and renders recovered waveform
      component.onMouseEnter();
      fixture.detectChanges();
      expect(mockGalleryService.getAudioAnalysis).toHaveBeenCalledTimes(2);
      expect(
        fixture.nativeElement.querySelectorAll('.audio-card-waveform-bar')
          .length,
      ).toBe(2);
    } finally {
      (window as any).Audio = OriginalAudio;
    }
  });
});
