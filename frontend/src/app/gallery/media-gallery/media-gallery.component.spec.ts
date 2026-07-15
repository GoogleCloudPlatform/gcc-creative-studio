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
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {ElementRef, NO_ERRORS_SCHEMA} from '@angular/core';
import {DomSanitizer} from '@angular/platform-browser';
import {MatIconModule} from '@angular/material/icon';
import {MatMenuModule} from '@angular/material/menu';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {of} from 'rxjs';
import {MediaGalleryComponent} from './media-gallery.component';
import {GalleryService} from '../gallery.service';
import {UserService} from '../../common/services/user.service';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {TagsService} from '../../common/services/tags.service';
import {MediaUploadService} from '../../common/services/media-upload/media-upload.service';
import {GoogleDriveService} from '../../common/services/google-drive/google-drive.service';

describe('MediaGalleryComponent', () => {
  let component: MediaGalleryComponent;
  let fixture: ComponentFixture<MediaGalleryComponent>;
  let uploadService: MediaUploadService;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [MediaGalleryComponent],
      imports: [
        HttpClientTestingModule,
        MatIconModule,
        MatMenuModule,
        NoopAnimationsModule,
      ],
      schemas: [NO_ERRORS_SCHEMA],
      providers: [
        MediaUploadService,
        {
          provide: GoogleDriveService,
          useValue: {
            openPicker: () => of([]),
          },
        },
        {
          provide: GalleryService,
          useValue: {
            isLoading$: of(false),
            images$: of([]),
            allImagesLoaded: of(true),
            searchTerm: () => {},
            filtersState: null,
            setFiltersState: () => {},
            setFilters: () => {},
            bulkDelete: () => of({deleted_count: 1}),
            bulkDownload: () => of(new Blob()),
            bulkCopy: () => of({}),
          },
        },
        {
          provide: DomSanitizer,
          useValue: {
            bypassSecurityTrustResourceUrl: (url: string) => url,
            bypassSecurityTrustUrl: (url: string) => url,
            sanitize: (context: unknown, value: unknown) => value,
          },
        },
        {
          provide: UserService,
          useValue: {
            getUserDetails: () => ({
              email: 'test@google.com',
              roles: ['ADMIN'],
            }),
          },
        },
        {
          provide: WorkspaceStateService,
          useValue: {
            activeWorkspaceId$: of(1),
            getActiveWorkspaceId: () => 1,
          },
        },
        {
          provide: TagsService,
          useValue: {
            getTags: () => of({data: []}),
            deleteTag: () => of(null),
            bulkAssign: () => of(null),
          },
        },
        {
          provide: ElementRef,
          useValue: {nativeElement: {querySelectorAll: () => []}},
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(MediaGalleryComponent);
    component = fixture.componentInstance;
    uploadService = TestBed.inject(MediaUploadService);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should trigger MediaUploadService.uploadFiles when files are selected', () => {
    spyOn(uploadService, 'uploadFiles');

    const dummyFile = new File(['test'], 'demo.png', {type: 'image/png'});
    const mockEvent = {
      target: {
        files: [dummyFile],
        value: 'demo.png',
      },
    } as unknown as Event;

    component.onFilesSelected(mockEvent);
    expect(uploadService.uploadFiles).toHaveBeenCalledWith(1, [dummyFile]);
  });

  it('should trigger MediaUploadService.uploadFiles when files are selected from Google Drive', () => {
    const driveService = TestBed.inject(GoogleDriveService);
    const dummyFile = new File(['test'], 'drive-demo.png', {type: 'image/png'});
    spyOn(driveService, 'openPicker').and.returnValue(of([dummyFile]));
    spyOn(uploadService, 'uploadFiles');

    component.openGoogleDrivePicker();
    expect(driveService.openPicker).toHaveBeenCalled();
    expect(uploadService.uploadFiles).toHaveBeenCalledWith(1, [dummyFile]);
  });

  describe('ngOnInit filters restoration', () => {
    it('should restore filters from GalleryService on init', () => {
      const mockState = {
        query: 'test query',
        mimeType: 'image/*',
        model: 'test-model',
        itemType: 'media_item',
        tags: ['tag1', 'tag2'],
        onlyMyMedia: true,
        startDate: new Date('2026-01-01T00:00:00.000Z'),
        endDate: new Date('2026-01-02T00:00:00.000Z'),
      };

      const galleryService = TestBed.inject(GalleryService);
      (galleryService as unknown as {filtersState: unknown}).filtersState =
        mockState;

      component.ngOnInit();

      expect(component.queryFilter).toBe('test query');
      expect(component.mediaTypeFilter).toBe('image/*');
      expect(component.generationModelFilter).toBe('test-model');
      expect(component.assetTypeFilter).toBe('media_item');
      expect(component.tagsFilter).toEqual(['tag1', 'tag2']);
      expect(component.onlyMyMedia).toBeTrue();
      expect(component.startDateFilter).toEqual(
        new Date('2026-01-01T00:00:00.000Z'),
      );
      expect(component.endDateFilter).toEqual(
        new Date('2026-01-02T00:00:00.000Z'),
      );
    });

    it('should use default values when no filtersState is stored', () => {
      const galleryService = TestBed.inject(GalleryService);
      (galleryService as unknown as {filtersState: unknown}).filtersState =
        null;

      component.ngOnInit();

      expect(component.queryFilter).toBe('');
      expect(component.mediaTypeFilter).toBe('');
      expect(component.generationModelFilter).toBe('');
      expect(component.assetTypeFilter).toBe('');
      expect(component.tagsFilter).toEqual([]);
      expect(component.onlyMyMedia).toBeFalse();
      expect(component.startDateFilter).toBeNull();
      expect(component.endDateFilter).toBeNull();
    });
  });
});
