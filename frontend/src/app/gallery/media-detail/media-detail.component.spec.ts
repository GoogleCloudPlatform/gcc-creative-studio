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
});
