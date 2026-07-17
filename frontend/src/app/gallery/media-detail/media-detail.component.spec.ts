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
import {of} from 'rxjs';
import {GalleryItem} from '../../common/models/gallery-item.model';

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
});
