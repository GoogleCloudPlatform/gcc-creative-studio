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
      getItemLineage: jasmine
        .createSpy('getItemLineage')
        .and.returnValue(of({spine: [], derivatives: []})),
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

  describe('cross-modal item lineage', () => {
    const loadItem = (overrides: Partial<GalleryItem>): HTMLElement => {
      mockGalleryService.getMedia.and.returnValue(
        of({
          id: 40,
          workspaceId: 1,
          createdAt: '2026-07-08T22:20:10Z',
          itemType: 'media_item',
          status: 'COMPLETED',
          mimeType: 'image/png',
          gcsUris: [],
          presignedUrls: ['https://example.com/item.png'],
          presignedThumbnailUrls: ['https://example.com/thumb.png'],
          metadata: {},
          ...overrides,
        } as GalleryItem),
      );
      component.fetchMediaDetails(overrides.id ?? 40, false);
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    };

    it('renders descending Iteration History spine, deleted tombstones, and Derived Items', () => {
      mockGalleryService.getItemLineage.and.returnValue(
        of({
          spine: [
            {
              itemType: 'source_asset',
              id: 10,
              mediaIndex: 0,
              mimeType: 'image/jpeg',
              prompt: 'Uploaded: bottle.jpg',
              thumbnailUrl: 'https://example.com/a10.jpg',
              deleted: false,
            },
            {
              itemType: 'media_item',
              id: 20,
              mediaIndex: 2,
              mimeType: 'image/png',
              role: 'image_edit_source',
              prompt: 'Place bottle on wet slate rock',
              thumbnailUrl: 'https://example.com/m20_2.jpg',
              deleted: false,
            },
            {
              itemType: 'media_item',
              id: 30,
              mediaIndex: 0,
              mimeType: 'video/mp4',
              role: 'start_frame',
              prompt: 'Removed intermediate video',
              deleted: true,
            },
            {
              itemType: 'media_item',
              id: 40,
              mediaIndex: 0,
              mimeType: 'video/mp4',
              role: 'omni_edit_source',
              prompt: 'Add golden hour light rays',
              thumbnailUrl: 'https://example.com/m40.jpg',
              deleted: false,
            },
          ],
          derivatives: [
            {
              itemType: 'media_item',
              id: 55,
              mediaIndex: 0,
              mimeType: 'video/mp4',
              role: 'omni_edit_source',
              prompt: 'Add rain reflections',
              thumbnailUrl: 'https://example.com/m55.jpg',
              deleted: false,
            },
          ],
        }),
      );

      const host = loadItem({
        id: 40,
        mimeType: 'video/mp4',
        originalPrompt: 'Add golden hour light rays',
      });

      expect(mockGalleryService.getItemLineage).toHaveBeenCalledWith(
        'media_item',
        40,
      );

      const steps = host.querySelectorAll('[data-testid="lineage-spine-step"]');
      expect(steps.length).toBe(4);

      // Step 4 (top): Current version has no self-link and displays "Current"
      expect(steps[0].textContent).toContain('4');
      expect(steps[0].textContent).toContain('Omni Edit');
      expect(steps[0].textContent).toContain('Current');
      expect(
        steps[0].querySelector('[data-testid="lineage-step-link"]'),
      ).toBeNull();

      // Step 3: Soft-deleted step renders tombstone instead of link
      expect(steps[1].textContent).toContain('3');
      expect(
        steps[1].querySelector('[data-testid="lineage-step-deleted"]'),
      ).not.toBeNull();
      expect(
        steps[1].querySelector('[data-testid="lineage-step-link"]'),
      ).toBeNull();
      expect(steps[1].textContent).toContain('Removed intermediate video');

      // Step 2: Intermediate variation with clickable link & img_index query param
      expect(steps[2].textContent).toContain('2');
      expect(steps[2].textContent).toContain('Edited');
      expect(steps[2].textContent).toContain('Image #20 · Var 3');
      expect(
        component.getLineageNodeQueryParams(
          component.lineageSpineDescending()[2],
        ),
      ).toEqual({img_index: 2});

      // Step 1 (bottom): Uploaded root asset
      expect(steps[3].textContent).toContain('1');
      expect(steps[3].textContent).toContain('Uploaded');
      expect(steps[3].textContent).toContain('Asset #10');
      expect(steps[3].textContent).toContain('Uploaded: bottle.jpg');

      // Derived Items section renders active downstream child
      const derivedSection = host.querySelector(
        '[data-testid="derived-items-section"]',
      );
      expect(derivedSection).not.toBeNull();
      const derivedTiles = host.querySelectorAll(
        '[data-testid="derived-item-tile"]',
      );
      expect(derivedTiles.length).toBe(1);
      expect(derivedTiles[0].textContent).toContain('Omni Edit');
    });

    it('deduplicates immediate primary parent from Referenced Assets while keeping secondary ingredients', () => {
      mockGalleryService.getItemLineage.and.returnValue(
        of({
          spine: [
            {
              itemType: 'media_item',
              id: 200,
              mediaIndex: 1,
              mimeType: 'video/mp4',
              prompt: 'Original hero shot',
              deleted: false,
            },
            {
              itemType: 'media_item',
              id: 300,
              mediaIndex: 0,
              mimeType: 'video/mp4',
              role: 'omni_edit_source',
              prompt: 'Add logo overlay',
              deleted: false,
            },
          ],
          derivatives: [],
        }),
      );

      const host = loadItem({
        id: 300,
        mimeType: 'video/mp4',
        enrichedSourceAssets: [
          {
            assetId: 91,
            gcsUri: 'gs://b/logo.png',
            presignedUrl: 'https://example.com/logo.png',
            presignedThumbnailUrl: 'https://example.com/logo.png',
            role: 'image_reference_asset',
            mimeType: 'image/png',
          },
        ],
        enrichedSourceMediaItems: [
          {
            mediaItemId: 200,
            mediaIndex: 1,
            gcsUri: 'gs://b/200_1.mp4',
            presignedUrl: 'https://example.com/200_1.mp4',
            presignedThumbnailUrl: 'https://example.com/200_1.jpg',
            role: 'video_reference',
            mimeType: 'video/mp4',
          },
        ],
      });

      expect(component.compositionSourceMediaItems().length).toBe(0);
      expect(component.compositionSourceAssets().length).toBe(1);
      const refSection = host.querySelector(
        '[data-testid="referenced-assets-section"]',
      );
      expect(refSection).not.toBeNull();
      expect(refSection?.textContent).toContain('Image Ref');
      expect(refSection?.textContent).not.toContain('Video Ref');
    });

    it('falls back cleanly to legacy audioIterationSteps when getItemLineage errors', () => {
      spyOn(console, 'warn');
      mockGalleryService.getItemLineage.and.returnValue(
        throwError(() => new Error('Network error')),
      );

      const host = loadItem({
        id: 800,
        originalPrompt: 'Add cello solo',
        audioAnalysis: {
          iteration_steps: ['Acoustic guitar intro', 'Add cello solo'],
          tracks: [null],
        },
      });

      const historySection = host.querySelector(
        '[data-testid="audio-iteration-history-section"]',
      );
      expect(historySection).not.toBeNull();
      expect(historySection?.getAttribute('data-lineage-mode')).toBe('legacy');
      expect(historySection?.textContent).toContain('Acoustic guitar intro');
      expect(historySection?.textContent).toContain('Add cello solo');
    });
  });
});
