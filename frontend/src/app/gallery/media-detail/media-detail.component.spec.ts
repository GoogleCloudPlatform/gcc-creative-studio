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
import {MediaDetailComponent} from './media-detail.component';
import {ActivatedRoute, Router} from '@angular/router';
import {GalleryService} from '../gallery.service';
import {LoadingService} from '../../common/services/loading.service';
import {MatSnackBar} from '@angular/material/snack-bar';
import {AuthService} from '../../common/services/auth.service';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {MatDialog} from '@angular/material/dialog';
import {DomSanitizer} from '@angular/platform-browser';
import {NO_ERRORS_SCHEMA} from '@angular/core';
import {of, throwError} from 'rxjs';
import {GalleryItem} from '../../common/models/gallery-item.model';
import {FolderService} from '../../common/services/folder.service';
import {FolderBreadcrumb} from '../../common/models/folder.model';

describe('MediaDetailComponent', () => {
  let component: MediaDetailComponent;
  let fixture: ComponentFixture<MediaDetailComponent>;
  let mockActivatedRoute: any;
  let mockRouter: any;
  let mockGalleryService: any;
  let mockLoadingService: any;
  let mockSnackBar: any;
  let mockAuthService: any;
  let mockWorkspaceStateService: any;
  let mockDialog: any;
  let mockDomSanitizer: any;
  let mockFolderService: any;

  const mockParamMap = {
    get: (key: string) => {
      if (key === 'id') return '123';
      return null;
    },
  };

  const mockQueryParamMap = {
    get: (key: string) => null,
  };

  beforeEach(async () => {
    mockActivatedRoute = {
      paramMap: of(mockParamMap),
      snapshot: {
        queryParamMap: mockQueryParamMap,
      },
    };

    mockRouter = {
      url: '/gallery/123',
      navigate: jasmine.createSpy('navigate'),
    };

    mockGalleryService = {
      getMedia: jasmine.createSpy('getMedia').and.returnValue(
        of({
          id: 123,
          workspaceId: 1,
          createdAt: '2026-07-08T22:20:10Z',
          itemType: 'media_item',
          status: 'COMPLETED',
          mimeType: 'image/png',
          titles: ['Test Media Title'],
          descriptions: ['Test Media Description'],
          prompt: 'Test Prompt',
          gcsUris: [],
          presignedUrls: ['http://example.com/image.png'],
          presignedThumbnailUrls: ['http://example.com/thumb.png'],
          metadata: {},
        } as GalleryItem),
      ),
      getAsset: jasmine
        .createSpy('getAsset')
        .and.returnValue(of({} as GalleryItem)),
      createTemplateFromMediaItem: jasmine
        .createSpy('createTemplateFromMediaItem')
        .and.returnValue(of({id: 'new-template-id'})),
      bulkDelete: jasmine
        .createSpy('bulkDelete')
        .and.returnValue(of({deleted_count: 1})),
    };

    mockLoadingService = {
      show: jasmine.createSpy('show'),
      hide: jasmine.createSpy('hide'),
    };

    mockSnackBar = {
      open: jasmine.createSpy('open'),
    };

    mockAuthService = {
      isUserAdmin: jasmine.createSpy('isUserAdmin').and.returnValue(false),
    };

    mockWorkspaceStateService = {
      getActiveWorkspaceId: jasmine
        .createSpy('getActiveWorkspaceId')
        .and.returnValue(1),
    };

    mockDialog = {
      open: jasmine.createSpy('open').and.returnValue({
        afterClosed: () => of(true),
      }),
    };

    mockDomSanitizer = {
      bypassSecurityTrustHtml: (html: string) => html,
      bypassSecurityTrustResourceUrl: (url: string) => url,
      bypassSecurityTrustUrl: (url: string) => url,
      sanitize: (context: any, value: any) => value,
    };

    mockFolderService = {
      getBreadcrumbs: jasmine
        .createSpy('getBreadcrumbs')
        .and.returnValue(of([] as FolderBreadcrumb[])),
    };

    await TestBed.configureTestingModule({
      declarations: [MediaDetailComponent],
      schemas: [NO_ERRORS_SCHEMA],
      providers: [
        {provide: ActivatedRoute, useValue: mockActivatedRoute},
        {provide: Router, useValue: mockRouter},
        {provide: GalleryService, useValue: mockGalleryService},
        {provide: LoadingService, useValue: mockLoadingService},
        {provide: MatSnackBar, useValue: mockSnackBar},
        {provide: AuthService, useValue: mockAuthService},
        {provide: WorkspaceStateService, useValue: mockWorkspaceStateService},
        {provide: MatDialog, useValue: mockDialog},
        {provide: DomSanitizer, useValue: mockDomSanitizer},
        {provide: FolderService, useValue: mockFolderService},
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(MediaDetailComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should render the media title and description in the DOM', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const titleElement = compiled.querySelector('h2');
    expect(titleElement?.textContent?.trim()).toBe('Test Media Title');

    const descElement = compiled.querySelector('p.text-gray-400');
    expect(descElement?.textContent?.trim()).toBe('Test Media Description');
  });

  it('should render Details as title fallback when title is not provided', () => {
    mockGalleryService.getMedia.and.returnValue(
      of({
        id: 123,
        workspaceId: 1,
        createdAt: '2026-07-08T22:20:10Z',
        itemType: 'media_item',
        status: 'COMPLETED',
        mimeType: 'image/png',
        prompt: 'Test Prompt',
        gcsUris: [],
        presignedUrls: ['http://example.com/image.png'],
        presignedThumbnailUrls: ['http://example.com/thumb.png'],
        metadata: {},
      } as GalleryItem),
    );

    component.fetchMediaDetails(123, false);
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    const titleElement = compiled.querySelector('h2');
    expect(titleElement?.textContent?.trim()).toBe('Details');

    const descElement = compiled.querySelector('p.text-gray-400');
    expect(descElement).toBeNull();
  });

  describe('location trail', () => {
    const itemInFolder = (folderId: number | undefined): GalleryItem =>
      ({
        id: 123,
        workspaceId: 7,
        folderId,
        createdAt: '2026-07-08T22:20:10Z',
        itemType: 'media_item',
        status: 'COMPLETED',
        mimeType: 'image/png',
        titles: ['Cymbal hero shot'],
        gcsUris: [],
        presignedUrls: ['http://example.com/image.png'],
        presignedThumbnailUrls: ['http://example.com/thumb.png'],
        metadata: {},
      }) as GalleryItem;

    const crumbTexts = () =>
      Array.from(
        (fixture.nativeElement as HTMLElement).querySelectorAll(
          '.media-location__crumb, .media-location__ellipsis',
        ),
      ).map(el => {
        // Ignore the (stubbed) <mat-icon> ligature text; only labels matter.
        const clone = el.cloneNode(true) as HTMLElement;
        clone.querySelectorAll('mat-icon').forEach(icon => icon.remove());
        return clone.textContent?.replace(/\s+/g, ' ').trim();
      });

    it('renders only "All Media" and skips the lookup for items in the root', () => {
      // Default mock item has no folderId.
      expect(mockFolderService.getBreadcrumbs).not.toHaveBeenCalled();
      expect(component.folderBreadcrumbs).toEqual([]);
      expect(crumbTexts()).toEqual(['All Media']);

      // The trail lives in the details column right above the title, not in
      // the page header (which the fixed workspace switcher overlaps on
      // laptop widths).
      const host = fixture.nativeElement as HTMLElement;
      const nav = host.querySelector('nav.media-location') as HTMLElement;
      const title = host.querySelector('h2') as HTMLElement;
      expect(nav.parentElement).toBe(title.parentElement);
      expect(
        nav.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(
        nav.querySelector('button.media-location__crumb')?.classList,
      ).toContain('is-current');
    });

    it('loads the folder path scoped to the item workspace and renders clickable crumbs', () => {
      mockGalleryService.getMedia.and.returnValue(of(itemInFolder(42)));
      mockFolderService.getBreadcrumbs.and.returnValue(
        of([
          {id: 10, name: 'Izumi Agent', parentId: null},
          {id: 42, name: 'mauro@example.com', parentId: 10},
        ] as FolderBreadcrumb[]),
      );

      component.fetchMediaDetails(123, false);
      fixture.detectChanges();

      expect(mockFolderService.getBreadcrumbs).toHaveBeenCalledWith(42, 7);
      expect(crumbTexts()).toEqual([
        'All Media',
        'Izumi Agent',
        'mauro@example.com',
      ]);

      const buttons = (fixture.nativeElement as HTMLElement).querySelectorAll(
        'button.media-location__crumb',
      );
      (buttons[1] as HTMLButtonElement).click();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/folders', 10]);
      (buttons[0] as HTMLButtonElement).click();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/gallery']);
    });

    it('keeps crumb DOM nodes stable across change detection (regression: clicks were swallowed)', () => {
      mockGalleryService.getMedia.and.returnValue(of(itemInFolder(42)));
      mockFolderService.getBreadcrumbs.and.returnValue(
        of([
          {id: 10, name: 'Izumi Agent', parentId: null},
          {id: 42, name: 'mauro@example.com', parentId: 10},
        ] as FolderBreadcrumb[]),
      );
      component.fetchMediaDetails(123, false);
      fixture.detectChanges();

      // Memoised: the same array instance is handed to *ngFor every cycle.
      const crumbsRef = component.locationCrumbs;
      expect(component.locationCrumbs).toBe(crumbsRef);

      const host = fixture.nativeElement as HTMLElement;
      const before = host.querySelectorAll('button.media-location__crumb')[1];

      // A mousedown triggers change detection before mouseup fires; the
      // element under the pointer must still be the same node afterwards.
      before.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      fixture.detectChanges();
      fixture.detectChanges();
      const after = host.querySelectorAll('button.media-location__crumb')[1];

      expect(after).toBe(before);
      expect(before.isConnected).toBeTrue();

      before.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      before.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/folders', 10]);
    });

    it('degrades to "All Media" when the breadcrumb lookup fails', () => {
      spyOn(console, 'warn');
      mockGalleryService.getMedia.and.returnValue(of(itemInFolder(42)));
      mockFolderService.getBreadcrumbs.and.returnValue(
        throwError(() => new Error('403')),
      );

      component.fetchMediaDetails(123, false);
      fixture.detectChanges();

      expect(component.mediaItem).toBeDefined();
      expect(component.folderBreadcrumbs).toEqual([]);
      expect(crumbTexts()).toEqual(['All Media']);
      expect(console.warn).toHaveBeenCalled();
    });

    it('refreshes the trail after the lightbox reports a move', () => {
      mockGalleryService.getMedia.and.returnValue(of(itemInFolder(undefined)));
      component.fetchMediaDetails(123, false);
      fixture.detectChanges();
      expect(mockFolderService.getBreadcrumbs).not.toHaveBeenCalled();

      mockFolderService.getBreadcrumbs.and.returnValue(
        of([{id: 5, name: 'Campaigns', parentId: null}] as FolderBreadcrumb[]),
      );
      component.onMediaMoved(5);
      fixture.detectChanges();

      expect(mockFolderService.getBreadcrumbs).toHaveBeenCalledWith(5, 7);
      expect(component.mediaItem?.folderId).toBe(5);
      expect(crumbTexts()).toEqual(['All Media', 'Campaigns']);

      // Moving back to the root clears the trail without another lookup.
      mockFolderService.getBreadcrumbs.calls.reset();
      component.onMediaMoved(null);
      fixture.detectChanges();
      expect(mockFolderService.getBreadcrumbs).not.toHaveBeenCalled();
      expect(component.mediaItem?.folderId).toBeUndefined();
      expect(crumbTexts()).toEqual(['All Media']);
    });

    it('collapses the middle of deep paths into an ellipsis with the hidden names as tooltip', () => {
      component.folderBreadcrumbs = [
        {id: 1, name: 'A'},
        {id: 2, name: 'B'},
        {id: 3, name: 'C'},
        {id: 4, name: 'D'},
        {id: 5, name: 'E'},
      ];

      const crumbs = component.locationCrumbs;
      expect(crumbs.map(c => c.name)).toEqual(['A', '…', 'D', 'E']);
      expect(crumbs[1].id).toBeNull();
      expect(crumbs[1].tooltip).toBe('B › C');

      // The ellipsis is not navigable.
      component.navigateToFolder(crumbs[1]);
      expect(mockRouter.navigate).not.toHaveBeenCalled();

      // Exactly three folders are shown in full.
      component.folderBreadcrumbs = component.folderBreadcrumbs.slice(0, 3);
      expect(component.locationCrumbs.map(c => c.name)).toEqual([
        'A',
        'B',
        'C',
      ]);
    });
  });

  const loadItem = (
    overrides: Partial<GalleryItem>,
    detect = true,
  ): HTMLElement => {
    const item = {
      id: 500,
      workspaceId: 1,
      createdAt: '2026-07-08T22:20:10Z',
      itemType: 'media_item',
      status: 'COMPLETED',
      mimeType: 'audio/mpeg',
      gcsUris: ['gs://b/0.mp3'],
      presignedUrls: ['https://example.com/0.mp3'],
      presignedThumbnailUrls: [],
      metadata: {},
      ...overrides,
    } as GalleryItem;
    mockGalleryService.getMedia.and.returnValue(of(item));
    component.fetchMediaDetails(item.id, false);
    if (detect) fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  describe('audio details & iteration actions', () => {
    it('does not duplicate Lyrics & Song Structure in the right-hand Details tab (rendered in lightbox)', () => {
      const host = loadItem({
        id: 500,
        prompt: 'Dream pop ballad',
        gcsUris: ['gs://b/0.mp3', 'gs://b/1.mp3'],
        presignedUrls: [
          'https://example.com/0.mp3',
          'https://example.com/1.mp3',
        ],
        audioAnalysis: {
          tracks: [
            {
              raw_text: '[Chorus]\nStarlight fading',
              lyrics: '[Chorus]\nStarlight fading',
              structure: {
                key: 'F major',
                sections: [{name: 'Chorus', bars: 8}],
              },
            },
            {raw_text: '[Verse]\nSecond take', lyrics: '[Verse]\nSecond take'},
          ],
        },
      });

      const lightboxDebug = fixture.debugElement.query(
        el => el.name === 'app-media-lightbox',
      );
      const detailsTab = host.querySelector(
        'mat-tab[label="Details"]',
      ) as HTMLElement;
      expect(lightboxDebug).not.toBeNull();
      expect(
        lightboxDebug.properties['mediaItem']?.audioAnalysis?.tracks?.[0]
          ?.lyrics,
      ).toContain('Starlight fading');
      expect(detailsTab).not.toBeNull();
      expect(detailsTab.textContent).toContain('Dream pop ballad');
      expect(detailsTab.textContent).not.toContain('Starlight fading');
      expect(detailsTab.textContent).not.toContain('Lyrics');
      expect(detailsTab.textContent).not.toContain('Song Structure');
    });

    it('renders seed parameter when seed is 0 and switches per-take seed on slide change', () => {
      const host = loadItem({
        id: 501,
        mimeType: 'audio/wav',
        prompt: 'Deterministic instrumental',
        seed: 0,
        gcsUris: ['gs://b/0.wav', 'gs://b/1.wav'],
        presignedUrls: [
          'https://example.com/0.wav',
          'https://example.com/1.wav',
        ],
        audioAnalysis: {tracks: [{seed: 0}, {seed: 1}]},
      });

      const seedEl = () =>
        host.querySelector('[data-testid="media-detail-seed"]');
      expect(seedEl()?.textContent?.trim()).toBe('0');

      component.currentImageIndex = 1;
      fixture.detectChanges();
      expect(seedEl()?.textContent?.trim()).toBe('1');
    });

    it('navigates to /audio with referenceAudio remixState on handleIterateAudio and ignores audio in handleEditWithOmni', () => {
      loadItem(
        {
          id: 502,
          model: 'lyria-3-pro-preview',
          titles: ['Midnight Drive', 'Midnight Drive Alt'],
          presignedUrls: [
            'https://example.com/0.mp3',
            'https://example.com/1.mp3',
          ],
        },
        false,
      );

      component.handleEditWithOmni({
        mediaItem: component.mediaItem,
        selectedIndex: 1,
      });
      expect(mockRouter.navigate).not.toHaveBeenCalled();

      component.handleIterateAudio({
        mediaItem: component.mediaItem as any,
        selectedIndex: 1,
      });
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/audio'], {
        state: {
          remixState: {
            lyriaModel: 'lyria-3-pro-preview',
            referenceAudio: {
              id: 502,
              type: 'media_item',
              index: 1,
              name: 'Midnight Drive Alt (Track 2)',
            },
          },
        },
      });
    });

    it('renders per-take musical profile and updates when currentImageIndex changes', () => {
      const host = loadItem({
        id: 700,
        originalPrompt: ' Indie synthwave track ',
        gcsUris: ['gs://b/0.mp3', 'gs://b/1.mp3'],
        presignedUrls: [
          'https://example.com/0.mp3',
          'https://example.com/1.mp3',
        ],
        audioAnalysis: {
          tracks: [
            {
              musical_profile: {
                bpm: 118,
                key_signature: 'A minor',
                time_signature: '4/4',
                vocal_profile: 'breathy female alto lead',
                instrumentation: ['Analog Juno pad', 'Punchy gated snare'],
                chord_progression: 'Am - F - C - G',
                groove: 'Driving sixteenth-note arpeggio pulse',
              },
            },
            {
              musical_profile: {
                bpm: 124,
                key_signature: 'D minor',
                instrumentation: ['Distorted bass'],
              },
            },
          ],
        },
      });

      const profileText = () =>
        host.querySelector('[data-testid="track-musical-profile-section"]')
          ?.textContent ?? '';
      for (const expected of [
        'BPM:',
        '118',
        'Key:',
        'A minor',
        'Meter:',
        '4/4',
        'Vocals:',
        'breathy female alto lead',
        'Analog Juno pad',
        'Punchy gated snare',
        'Am - F - C - G',
        'Driving sixteenth-note arpeggio pulse',
      ]) {
        expect(profileText()).toContain(expected);
      }

      component.currentImageIndex = 1;
      fixture.detectChanges();

      expect(profileText()).toContain('124');
      expect(profileText()).toContain('D minor');
      expect(profileText()).not.toContain('Analog Juno pad');
    });

    it('renders Iteration History only when multi-step or derived from an Audio Ref', () => {
      const host = loadItem({
        id: 701,
        originalPrompt: 'Warm acoustic folk intro',
        audioAnalysis: {
          iteration_steps: ['Warm acoustic folk intro'],
          tracks: [null],
        },
      });
      expect(
        host.querySelector('[data-testid="audio-iteration-history-section"]'),
      ).toBeNull();

      loadItem({
        id: 702,
        originalPrompt: 'Add upright bass and brushed snare in chorus',
        audioAnalysis: {
          iteration_steps: [
            'Warm acoustic folk intro',
            'Add upright bass and brushed snare in chorus',
          ],
          tracks: [null],
        },
      });

      const historySection = host.querySelector(
        '[data-testid="audio-iteration-history-section"]',
      );
      expect(historySection).not.toBeNull();
      const items = historySection?.querySelectorAll('li') ?? [];
      expect(items.length).toBe(2);
      expect(items[0].textContent).toContain('Warm acoustic folk intro');
      expect(items[1].textContent).toContain(
        'Add upright bass and brushed snare in chorus',
      );
    });

    it('separates originalPrompt, synthesizedPrompt, and negativePrompt for non-JSON audio items', () => {
      const host = loadItem({
        id: 703,
        originalPrompt: 'Make the chorus heavier with brass',
        prompt:
          '120 BPM cinematic funk.\n[0:00 - 0:15] Verse groove.\n[0:15 - 0:30] Heavy brass chorus.',
        negativePrompt: 'muddy low-end, clipping',
      });

      const origBox = host.querySelector('[data-testid="original-prompt-box"]');
      const synthBox = host.querySelector(
        '[data-testid="synthesized-prompt-box"]',
      );
      const negBox = host.querySelector('[data-testid="negative-prompt-box"]');

      expect(origBox?.textContent).toContain(
        'Make the chorus heavier with brass',
      );
      expect(origBox?.textContent).not.toContain('[0:15 - 0:30]');
      expect(synthBox?.textContent).toContain(
        '[0:15 - 0:30] Heavy brass chorus.',
      );
      expect(negBox?.textContent).toContain('muddy low-end, clipping');
    });

    it('renders Audio Ref and Track N badges on referenced assets and resolves assetId or sourceAssetId', () => {
      const host = loadItem({
        id: 704,
        originalPrompt: 'Add strings over uploaded demo',
        enrichedSourceAssets: [
          {
            assetId: 88,
            gcsUri: 'gs://b/demo.wav',
            presignedUrl: 'https://example.com/demo.wav',
            presignedThumbnailUrl: '',
            role: 'audio_reference',
            mimeType: 'audio/wav',
          },
        ],
        enrichedSourceMediaItems: [
          {
            mediaItemId: 650,
            mediaIndex: 1,
            gcsUri: 'gs://b/parent_1.mp3',
            presignedUrl: 'https://example.com/parent_1.mp3',
            presignedThumbnailUrl: '',
            role: 'audio_reference',
            mimeType: 'audio/mpeg',
          },
        ],
        audioAnalysis: {
          iteration_steps: ['Add strings over uploaded demo'],
        },
      });

      const refSection = host.querySelector(
        '[data-testid="referenced-assets-section"]',
      );
      expect(refSection).not.toBeNull();
      expect(refSection?.textContent).toContain('Audio Ref');
      expect(refSection?.textContent).toContain('Track 2');
      expect(
        host.querySelector('[data-testid="audio-iteration-history-section"]'),
      ).not.toBeNull();

      expect(component.getSourceAssetRouteId({assetId: 88})).toBe(88);
      expect(
        component.getSourceAssetRouteId({sourceAssetId: 'legacy-99'}),
      ).toBe('legacy-99');
    });

    it('hides irrelevant TTS/image default fields on Lyria music items while keeping Voice and Language on TTS items', () => {
      const host = loadItem({
        id: 705,
        model: 'lyria-3-pro-preview',
        originalPrompt: 'Lush orchestral overture',
        voiceName: 'Puck',
        languageCode: 'en-US',
        aspectRatio: '16:9',
        resolution: '1080p',
        googleSearch: null as any,
        numMedia: 2,
        generationTime: 14.5,
      });

      expect(host.textContent).toContain('lyria-3-pro-preview');
      expect(host.textContent).toContain('Number of Media:');
      for (const hidden of [
        'Voice:',
        'Puck',
        'Language:',
        'en-US',
        'Aspect Ratio:',
        '16:9',
        'Resolution:',
        'Google Search:',
        'Watermark:',
      ]) {
        expect(host.textContent).not.toContain(hidden);
      }

      loadItem({
        id: 706,
        mimeType: 'audio/wav',
        model: 'chirp_3',
        originalPrompt: 'Welcome to Creative Studio',
        voiceName: 'Puck',
        languageCode: 'en-US',
        aspectRatio: '16:9',
        googleSearch: null as any,
      });

      expect(host.textContent).toContain('Voice:');
      expect(host.textContent).toContain('Puck');
      expect(host.textContent).toContain('Language:');
      expect(host.textContent).toContain('en-US');
      expect(host.textContent).not.toContain('Aspect Ratio:');
      expect(host.textContent).not.toContain('Google Search:');
      expect(host.textContent).not.toContain('Watermark:');
    });
  });
});
