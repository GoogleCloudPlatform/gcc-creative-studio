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
import {
  ActivatedRoute,
  convertToParamMap,
  ParamMap,
  Router,
} from '@angular/router';
import {BehaviorSubject, of, throwError} from 'rxjs';
import {MediaGalleryComponent} from './media-gallery.component';
import {GalleryService} from '../gallery.service';
import {UserService} from '../../common/services/user.service';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';
import {TagsService} from '../../common/services/tags.service';
import {MediaUploadService} from '../../common/services/media-upload/media-upload.service';
import {GoogleDriveService} from '../../common/services/google-drive/google-drive.service';
import {FolderService} from '../../common/services/folder.service';
import {Folder} from '../../common/models/folder.model';
import {FolderConflictDialogComponent} from '../../common/components/folder-conflict-dialog/folder-conflict-dialog.component';
import {MatSnackBar} from '@angular/material/snack-bar';

describe('MediaGalleryComponent', () => {
  let component: MediaGalleryComponent;
  let fixture: ComponentFixture<MediaGalleryComponent>;
  let uploadService: MediaUploadService;
  let folderService: jasmine.SpyObj<FolderService>;
  let galleryService: GalleryService;
  let routerSpy: jasmine.SpyObj<Router>;
  let paramMapSubject: BehaviorSubject<ParamMap>;
  let activeWorkspaceIdSubject: BehaviorSubject<number | null>;

  beforeEach(async () => {
    paramMapSubject = new BehaviorSubject<ParamMap>(convertToParamMap({}));
    activeWorkspaceIdSubject = new BehaviorSubject<number | null>(1);
    routerSpy = jasmine.createSpyObj('Router', ['navigate', 'navigateByUrl'], {
      events: of(),
    });
    const folderServiceSpy = jasmine.createSpyObj('FolderService', [
      'getFolders',
      'getBreadcrumbs',
      'getFolderById',
      'moveItems',
      'copyItems',
      'createFolder',
      'updateFolder',
      'deleteFolder',
    ]);
    folderServiceSpy.getFolders.and.returnValue(of([]));
    folderServiceSpy.getBreadcrumbs.and.returnValue(of([]));
    folderServiceSpy.getFolderById.and.returnValue(of({} as Folder));
    folderServiceSpy.moveItems.and.returnValue(of({total_moved: 1}));
    folderServiceSpy.copyItems.and.returnValue(
      of({
        total_copied: 1,
        media_items_copied: 1,
        source_assets_copied: 0,
        folders_copied: 0,
      }),
    );

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
          provide: FolderService,
          useValue: folderServiceSpy,
        },
        {
          provide: MatSnackBar,
          useValue: {
            open: jasmine.createSpy('open'),
          },
        },
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
            bulkMove: () => of({moved_count: 1}),
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
            activeWorkspaceId$: activeWorkspaceIdSubject.asObservable(),
            getActiveWorkspaceId: () => activeWorkspaceIdSubject.value,
            setActiveWorkspaceId: (id: number | null) =>
              activeWorkspaceIdSubject.next(id),
          },
        },
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: paramMapSubject.asObservable(),
          },
        },
        {
          provide: Router,
          useValue: routerSpy,
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
    folderService = TestBed.inject(
      FolderService,
    ) as jasmine.SpyObj<FolderService>;
    galleryService = TestBed.inject(GalleryService);
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

  describe('Drag and Drop moving', () => {
    it('should move items to a target folder on onItemDroppedOnFolder', () => {
      const targetFolder = {
        id: 5,
        workspaceId: 1,
        userEmail: 'test@google.com',
        name: 'Target Folder',
        itemCount: 0,
        subfolderCount: 0,
      };

      const payload = {
        mediaItemIds: [101, 102],
        sourceAssetIds: [201],
        itemCount: 3,
      };

      component.images = [
        {
          id: 101,
          itemType: 'media_item',
          workspaceId: 1,
          createdAt: '',
          metadata: {},
        },
        {
          id: 102,
          itemType: 'media_item',
          workspaceId: 1,
          createdAt: '',
          metadata: {},
        },
        {
          id: 999,
          itemType: 'media_item',
          workspaceId: 1,
          createdAt: '',
          metadata: {},
        },
      ];

      component.onItemDroppedOnFolder(targetFolder, payload);

      expect(folderService.moveItems).toHaveBeenCalledWith(
        jasmine.objectContaining({
          workspaceId: 1,
          mediaItemIds: [101, 102],
          sourceAssetIds: [201],
          folderIds: [],
          destinationFolderId: 5,
        }),
      );
      expect(component.images.length).toBe(1);
      expect(component.images[0].id).toBe(999);
    });

    it('should move items to root on onBreadcrumbDrop with null folderId', () => {
      component.currentFolderId = 5;
      const payload = {
        mediaItemIds: [101],
        sourceAssetIds: [],
        itemCount: 1,
      };

      const mockEvent = {
        preventDefault: jasmine.createSpy('preventDefault'),
        dataTransfer: {
          getData: (type: string) =>
            type === 'application/json' ? JSON.stringify(payload) : '',
        },
      } as unknown as DragEvent;

      component.onBreadcrumbDrop(mockEvent, null);

      expect(folderService.moveItems).toHaveBeenCalledWith(
        jasmine.objectContaining({
          workspaceId: 1,
          mediaItemIds: [101],
          sourceAssetIds: [],
          folderIds: [],
          destinationFolderId: null,
        }),
      );
    });

    it('should update dragOverBreadcrumbId on onBreadcrumbDragOver', () => {
      const mockEvent = {
        preventDefault: jasmine.createSpy('preventDefault'),
        dataTransfer: {
          types: ['application/json'],
          dropEffect: '',
        },
      } as unknown as DragEvent;

      component.currentFolderId = 5;
      component.onBreadcrumbDragOver(mockEvent, null);
      expect(component.dragOverBreadcrumbId).toBe('root');

      component.onBreadcrumbDragOver(mockEvent, 2);
      expect(component.dragOverBreadcrumbId).toBe(2);
    });

    it('should call galleryService.bulkMove when moving items across workspaces', () => {
      spyOn(galleryService, 'bulkMove').and.returnValue(of({moved_count: 2}));
      spyOn(component, 'searchTerm');
      component.images = [
        {id: 1, itemType: 'media_item'} as any,
        {id: 2, itemType: 'source_asset'} as any,
        {id: 3, itemType: 'media_item'} as any,
      ];
      component.selectedItems.add('media_item:1');
      component.selectedItems.add('source_asset:2');

      (component as any).executeMoveToWorkspace(
        [1],
        [2],
        [],
        88,
        'Target Workspace',
      );

      expect(galleryService.bulkMove).toHaveBeenCalledWith(
        [
          {id: 1, type: 'media_item'},
          {id: 2, type: 'source_asset'},
        ],
        88,
        undefined,
      );
      expect(component.images.length).toBe(1);
      expect(component.images[0].id).toBe(3);
      expect(component.selectedItems.size).toBe(0);
    });

    it('should call galleryService.bulkMove when moving folder across workspaces', () => {
      spyOn(galleryService, 'bulkMove').and.returnValue(of({moved_count: 1}));
      spyOn(component, 'loadFolders');
      component.folders = [
        {id: 10, name: 'Folder 1', workspace_id: 1, parent_id: null} as any,
        {id: 20, name: 'Folder 2', workspace_id: 1, parent_id: null} as any,
      ];

      (component as any).executeMoveToWorkspace(
        [],
        [],
        [10],
        88,
        'Target Workspace',
      );

      expect(galleryService.bulkMove).toHaveBeenCalledWith(
        [{id: 10, type: 'folder'}],
        88,
        undefined,
      );
      expect(component.folders.length).toBe(1);
      expect(component.folders[0].id).toBe(20);
      expect(component.loadFolders).toHaveBeenCalled();
    });

    it('should handle openMoveFolderDialog when destination workspace is chosen', () => {
      const mockDialogRef = {
        afterClosed: () =>
          of({destinationWorkspaceId: 88, destinationName: 'Target Workspace'}),
      };
      spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);
      const executeSpy = spyOn(
        component as any,
        'executeMoveToWorkspace',
      ).and.callThrough();
      spyOn(galleryService, 'bulkMove').and.returnValue(of({moved_count: 1}));

      const folder = {
        id: 10,
        name: 'Folder 1',
        workspace_id: 1,
        parent_id: null,
      } as any;
      component.openMoveFolderDialog(folder);

      expect(executeSpy).toHaveBeenCalledWith(
        [],
        [],
        [10],
        88,
        'Target Workspace',
      );
    });

    it('should handle openCopyFolderDialog when destination workspace is chosen', () => {
      const mockDialogRef = {
        afterClosed: () =>
          of({destinationWorkspaceId: 88, destinationName: 'Target Workspace'}),
      };
      spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);
      const executeSpy = spyOn(
        component as any,
        'executeCopyFolderToWorkspace',
      ).and.callThrough();
      spyOn(galleryService, 'bulkCopy').and.returnValue(of({copied_count: 1}));

      const folder = {
        id: 10,
        name: 'Folder 1',
        workspace_id: 1,
        parent_id: null,
      } as any;
      component.openCopyFolderDialog(folder);

      expect(executeSpy).toHaveBeenCalledWith(
        folder,
        88,
        null,
        'Target Workspace',
      );
      expect(galleryService.bulkCopy).toHaveBeenCalledWith(
        [{id: 10, type: 'folder'}],
        88,
        null,
      );
    });

    it('should handle openCopyFolderDialog when destination folder is chosen', () => {
      const mockDialogRef = {
        afterClosed: () =>
          of({destinationFolderId: 25, destinationName: 'Subfolder'}),
      };
      spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);
      const executeSpy = spyOn(
        component as any,
        'executeCopy',
      ).and.callThrough();

      const folder = {
        id: 10,
        name: 'Folder 1',
        workspace_id: 1,
        parent_id: null,
      } as any;
      component.openCopyFolderDialog(folder);

      expect(executeSpy).toHaveBeenCalledWith([], [], [10], 25, 'Subfolder');
      expect(folderService.copyItems).toHaveBeenCalledWith({
        workspaceId: 1,
        mediaItemIds: [],
        sourceAssetIds: [],
        folderIds: [10],
        destinationFolderId: 25,
        conflictStrategy: undefined,
      });
    });

    it('should handle copySelected when destination folder is chosen', () => {
      component.selectedItems.add('media_item:101');
      component.selectedItems.add('source_asset:202');
      const mockDialogRef = {
        afterClosed: () =>
          of({destinationFolderId: 5, destinationName: 'Destination'}),
      };
      spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);
      const executeSpy = spyOn(
        component as any,
        'executeCopy',
      ).and.callThrough();

      component.copySelected();

      expect(executeSpy).toHaveBeenCalledWith(
        [101],
        [202],
        [],
        5,
        'Destination',
      );
      expect(folderService.copyItems).toHaveBeenCalledWith({
        workspaceId: 1,
        mediaItemIds: [101],
        sourceAssetIds: [202],
        folderIds: [],
        destinationFolderId: 5,
        conflictStrategy: undefined,
      });
    });

    it('should handle copySelected when destination workspace is chosen', () => {
      component.selectedItems.add('media_item:101');
      const mockDialogRef = {
        afterClosed: () =>
          of({destinationWorkspaceId: 99, destinationName: 'Other Workspace'}),
      };
      spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);
      spyOn(galleryService, 'bulkCopy').and.returnValue(of({copied_count: 1}));

      component.copySelected();

      expect(galleryService.bulkCopy).toHaveBeenCalledWith(
        [{id: 101, type: 'media_item'}],
        99,
        null,
      );
    });

    it('should open conflict dialog and retry copy with merge when 409 occurs during copyItems', () => {
      const conflictErr = {
        status: 409,
        error: {
          detail: {
            code: 'FOLDER_COLLISION',
            conflicts: [{folder_id: 10, folder_name: 'Folder A'}],
          },
        },
      };

      folderService.copyItems.and.returnValues(
        throwError(() => conflictErr),
        of({
          total_copied: 1,
          media_items_copied: 0,
          source_assets_copied: 0,
          folders_copied: 1,
        }),
      );

      const mockDialogRef = {
        afterClosed: () => of('merge'),
      };
      spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);

      (component as any).executeCopy([], [], [10], 5, 'Destination');

      expect(component.dialog.open).toHaveBeenCalledWith(
        FolderConflictDialogComponent,
        jasmine.objectContaining({
          data: jasmine.objectContaining({
            folderNames: ['Folder A'],
            destinationName: 'Destination',
            isMove: false,
          }),
        }),
      );
      expect(folderService.copyItems).toHaveBeenCalledTimes(2);
      expect(folderService.copyItems).toHaveBeenCalledWith({
        workspaceId: 1,
        mediaItemIds: [],
        sourceAssetIds: [],
        folderIds: [10],
        destinationFolderId: 5,
        conflictStrategy: 'merge',
      });
    });

    describe('Folder Conflict Handling', () => {
      it('should open conflict dialog and retry move with keep_both when 409 FOLDER_COLLISION occurs', () => {
        const conflictErr = {
          status: 409,
          error: {
            detail: {
              code: 'FOLDER_COLLISION',
              conflicts: [{folder_id: 10, folder_name: 'Campaigns'}],
            },
          },
        };

        folderService.moveItems.and.returnValues(
          throwError(() => conflictErr),
          of({total_moved: 1}),
        );

        const mockDialogRef = {
          afterClosed: () => of('keep_both'),
        };
        spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);

        component.folders = [{id: 10, name: 'Campaigns'} as any];
        (component as any).executeMove([], [], [10], 5, 'Destination');

        expect(component.dialog.open).toHaveBeenCalledWith(
          FolderConflictDialogComponent,
          jasmine.objectContaining({
            data: jasmine.objectContaining({
              folderNames: ['Campaigns'],
              destinationName: 'Destination',
              isMove: true,
            }),
          }),
        );
        expect(folderService.moveItems).toHaveBeenCalledTimes(2);
        expect(folderService.moveItems).toHaveBeenCalledWith(
          jasmine.objectContaining({
            folderIds: [10],
            destinationFolderId: 5,
            conflictStrategy: 'keep_both',
          }),
        );
      });

      it('should open conflict dialog and retry move with merge when 409 FOLDER_COLLISION occurs', () => {
        const conflictErr = {
          status: 409,
          error: {
            detail: {
              code: 'FOLDER_COLLISION',
              conflicts: [{folder_id: 10, folder_name: 'Campaigns'}],
            },
          },
        };

        folderService.moveItems.and.returnValues(
          throwError(() => conflictErr),
          of({total_moved: 1}),
        );

        const mockDialogRef = {
          afterClosed: () => of('merge'),
        };
        spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);

        (component as any).executeMove([], [], [10], 5, 'Destination');

        expect(folderService.moveItems).toHaveBeenCalledTimes(2);
        expect(folderService.moveItems).toHaveBeenCalledWith(
          jasmine.objectContaining({
            folderIds: [10],
            destinationFolderId: 5,
            conflictStrategy: 'merge',
          }),
        );
      });

      it('should restore items and not retry when user cancels conflict dialog with stop', () => {
        const conflictErr = {
          status: 409,
          error: {
            detail: {
              code: 'FOLDER_COLLISION',
              conflicts: [{folder_id: 10, folder_name: 'Campaigns'}],
            },
          },
        };

        folderService.moveItems.and.returnValue(throwError(() => conflictErr));

        const mockDialogRef = {
          afterClosed: () => of('stop'),
        };
        spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);

        component.folders = [{id: 10, name: 'Campaigns'} as any];
        (component as any).executeMove([], [], [10], 5, 'Destination');

        expect(folderService.moveItems).toHaveBeenCalledTimes(1);
        expect(component.folders.length).toBe(1);
      });

      it('should open conflict dialog and retry bulkMove with merge on 409 FOLDER_COLLISION', () => {
        const conflictErr = {
          status: 409,
          error: {
            detail: {
              code: 'FOLDER_COLLISION',
              conflicts: [{folder_id: 10, folder_name: 'Campaigns'}],
            },
          },
        };

        spyOn(galleryService, 'bulkMove').and.returnValues(
          throwError(() => conflictErr),
          of({moved_count: 1}),
        );

        const mockDialogRef = {
          afterClosed: () => of('merge'),
        };
        spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);

        (component as any).executeMoveToWorkspace(
          [],
          [],
          [10],
          88,
          'Workspace',
        );

        expect(component.dialog.open).toHaveBeenCalledWith(
          FolderConflictDialogComponent,
          jasmine.objectContaining({
            data: jasmine.objectContaining({
              folderNames: ['Campaigns'],
              destinationName: 'Workspace',
              isMove: true,
            }),
          }),
        );
        expect(galleryService.bulkMove).toHaveBeenCalledTimes(2);
        expect(galleryService.bulkMove).toHaveBeenCalledWith(
          [{id: 10, type: 'folder'}],
          88,
          'merge',
        );
      });

      it('should open conflict dialog and retry bulkCopy with merge on 409 FOLDER_COLLISION', () => {
        const conflictErr = {
          status: 409,
          error: {
            detail: {
              code: 'FOLDER_COLLISION',
              conflicts: [{folder_id: 10, folder_name: 'Campaigns'}],
            },
          },
        };

        spyOn(galleryService, 'bulkCopy').and.returnValues(
          throwError(() => conflictErr),
          of({copied_count: 1}),
        );

        const mockDialogRef = {
          afterClosed: () => of('merge'),
        };
        spyOn(component.dialog, 'open').and.returnValue(mockDialogRef as any);

        const folder = {id: 10, name: 'Campaigns'} as any;
        (component as any).executeCopyFolderToWorkspace(folder, 88);

        expect(component.dialog.open).toHaveBeenCalledWith(
          FolderConflictDialogComponent,
          jasmine.objectContaining({
            data: jasmine.objectContaining({
              folderNames: ['Campaigns'],
              destinationName: 'target workspace',
              isMove: false,
            }),
          }),
        );
        expect(galleryService.bulkCopy).toHaveBeenCalledTimes(2);
        expect(galleryService.bulkCopy).toHaveBeenCalledWith(
          [{id: 10, type: 'folder'}],
          88,
          'merge',
        );
      });
    });
  });

  describe('Route-driven Folder Navigation', () => {
    it('should initialize at root when no folderId param is present', () => {
      expect(component.currentFolderId).toBeNull();
      expect(folderService.getFolders).toHaveBeenCalledWith(1, null);
    });

    it('should update currentFolderId and load folders/breadcrumbs when folderId route param changes', () => {
      spyOn(component, 'loadFolders').and.callThrough();
      spyOn(component, 'loadBreadcrumbs').and.callThrough();
      spyOn(component, 'searchTerm').and.callThrough();

      paramMapSubject.next(convertToParamMap({folderId: '42'}));

      expect(component.currentFolderId).toBe(42);
      expect(component.loadFolders).toHaveBeenCalled();
      expect(component.loadBreadcrumbs).toHaveBeenCalled();
      expect(folderService.getBreadcrumbs).toHaveBeenCalledWith(42, 1);
      expect(component.searchTerm).toHaveBeenCalled();
    });

    it('should default currentFolderId to null and redirect to /gallery when folderId is non-numeric', () => {
      routerSpy.navigate.calls.reset();
      spyOn(component, 'loadFolders').and.callThrough();
      spyOn(component, 'loadBreadcrumbs').and.callThrough();

      paramMapSubject.next(convertToParamMap({folderId: 'abc'}));

      expect(component.currentFolderId).toBeNull();
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);
      expect(component.loadFolders).not.toHaveBeenCalled();
      expect(component.loadBreadcrumbs).not.toHaveBeenCalled();
    });

    it('should default currentFolderId to null and redirect to /gallery when folderId is not a positive integer', () => {
      routerSpy.navigate.calls.reset();

      paramMapSubject.next(convertToParamMap({folderId: '-5'}));
      expect(component.currentFolderId).toBeNull();
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);

      routerSpy.navigate.calls.reset();
      paramMapSubject.next(convertToParamMap({folderId: '0'}));
      expect(component.currentFolderId).toBeNull();
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);

      routerSpy.navigate.calls.reset();
      paramMapSubject.next(convertToParamMap({folderId: '1.5'}));
      expect(component.currentFolderId).toBeNull();
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);
    });

    it('should navigate via router when navigateToFolder is called in standalone mode', () => {
      component.isSelectorMode = false;
      component.isSelectionMode = false;

      const folder = {id: 15, name: 'Subfolder', workspaceId: 1} as any;
      component.navigateToFolder(folder);

      expect(routerSpy.navigate).toHaveBeenCalledWith(['/folders', 15]);
    });

    it('should update in-place without router when navigateToFolder is called in selector mode', () => {
      component.isSelectorMode = true;
      spyOn(component, 'loadFolders');
      spyOn(component, 'loadBreadcrumbs');
      spyOn(component, 'searchTerm');

      const folder = {id: 15, name: 'Subfolder', workspaceId: 1} as any;
      component.navigateToFolder(folder);

      expect(routerSpy.navigate).not.toHaveBeenCalled();
      expect(component.currentFolderId).toBe(15);
      expect(component.loadFolders).toHaveBeenCalled();
      expect(component.loadBreadcrumbs).toHaveBeenCalled();
      expect(component.searchTerm).toHaveBeenCalled();
    });

    it('should navigate to root /gallery when navigateToBreadcrumb is called with null', () => {
      component.isSelectorMode = false;
      component.isSelectionMode = false;

      component.navigateToBreadcrumb(null);

      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);
    });

    it('should navigate to /folders/:id when navigateToBreadcrumb is called with a breadcrumb', () => {
      component.isSelectorMode = false;
      component.isSelectionMode = false;

      const crumb = {id: 7, name: 'Crumb Folder'};
      component.navigateToBreadcrumb(crumb);

      expect(routerSpy.navigate).toHaveBeenCalledWith(['/folders', 7]);
    });

    it('should update in-place without router when navigateToBreadcrumb is called in selector mode', () => {
      component.isSelectorMode = true;
      spyOn(component, 'loadFolders');
      spyOn(component, 'loadBreadcrumbs');
      spyOn(component, 'searchTerm');

      const crumb = {id: 7, name: 'Crumb Folder'};
      component.navigateToBreadcrumb(crumb);

      expect(routerSpy.navigate).not.toHaveBeenCalled();
      expect(component.currentFolderId).toBe(7);
      expect(component.loadFolders).toHaveBeenCalled();
      expect(component.loadBreadcrumbs).toHaveBeenCalled();
      expect(component.searchTerm).toHaveBeenCalled();
    });

    it('should redirect to /gallery and show snackbar when breadcrumbs fail to load in standalone mode', () => {
      const snackBar = TestBed.inject(MatSnackBar);
      folderService.getBreadcrumbs.and.returnValue(
        throwError(() => ({
          error: {detail: 'Folder with ID 999 not found in this workspace.'},
        })),
      );

      component.currentFolderId = 999;
      component.loadBreadcrumbs();

      expect(folderService.getBreadcrumbs).toHaveBeenCalledWith(999, 1);
      expect(snackBar.open).toHaveBeenCalledWith(
        'Folder with ID 999 not found in this workspace.',
        'Close',
        {duration: 3000},
      );
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);
    });

    it('should show fallback snackbar message when breadcrumb error has no detail', () => {
      const snackBar = TestBed.inject(MatSnackBar);
      folderService.getBreadcrumbs.and.returnValue(
        throwError(() => new Error('Network error')),
      );

      component.currentFolderId = 999;
      component.loadBreadcrumbs();

      expect(snackBar.open).toHaveBeenCalledWith(
        'Folder not found in this workspace.',
        'Close',
        {duration: 3000},
      );
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);
    });

    it('should navigate to /gallery on workspace change if inside a folder in standalone mode', () => {
      component.isSelectorMode = false;
      component.isSelectionMode = false;
      component.currentFolderId = 5;

      activeWorkspaceIdSubject.next(2);

      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);
    });

    it('should automatically switch workspace and show toast when folder belongs to another accessible workspace', () => {
      const snackBar = TestBed.inject(MatSnackBar);
      component.isSelectorMode = false;
      component.isSelectionMode = false;
      component.currentFolderId = 5;

      folderService.getBreadcrumbs.and.callFake(
        (folderId: number, wsId?: number) => {
          if (wsId === 2) {
            return of([{id: 5, name: 'Folder 5', parentId: null}]);
          }
          return throwError(() => ({
            status: 404,
            error: {detail: 'Folder with ID 5 not found in this workspace.'},
          }));
        },
      );
      folderService.getFolderById.and.returnValue(
        of({
          id: 5,
          workspaceId: 2,
          name: 'Folder 5',
          userEmail: 'user@example.com',
          itemCount: 0,
          subfolderCount: 0,
        }),
      );

      component.loadBreadcrumbs();

      expect(folderService.getFolderById).toHaveBeenCalledWith(5);
      expect(snackBar.open).toHaveBeenCalledWith(
        "Switched to folder's workspace.",
        'Close',
        {duration: 3000},
      );
      expect(activeWorkspaceIdSubject.value).toBe(2);
      expect(routerSpy.navigate).not.toHaveBeenCalledWith(['/gallery']);
    });

    it('should redirect to /gallery and show error snackbar when user lacks permission to access folder workspace (403)', () => {
      const snackBar = TestBed.inject(MatSnackBar);
      component.isSelectorMode = false;
      component.isSelectionMode = false;
      component.currentFolderId = 5;

      folderService.getBreadcrumbs.and.returnValue(
        throwError(() => ({status: 404})),
      );
      folderService.getFolderById.and.returnValue(
        throwError(() => ({
          status: 403,
          error: {
            detail: 'You do not have permission to access this workspace.',
          },
        })),
      );

      component.loadBreadcrumbs();

      expect(folderService.getFolderById).toHaveBeenCalledWith(5);
      expect(snackBar.open).toHaveBeenCalledWith(
        'You do not have permission to access this workspace.',
        'Close',
        {duration: 3000},
      );
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);
    });

    it('should redirect to /gallery and show error snackbar when folder does not exist at all (404 from getFolderById)', () => {
      const snackBar = TestBed.inject(MatSnackBar);
      component.isSelectorMode = false;
      component.isSelectionMode = false;
      component.currentFolderId = 999;

      folderService.getBreadcrumbs.and.returnValue(
        throwError(() => ({status: 404})),
      );
      folderService.getFolderById.and.returnValue(
        throwError(() => ({
          status: 404,
          error: {detail: 'Folder with ID 999 not found.'},
        })),
      );

      component.loadBreadcrumbs();

      expect(folderService.getFolderById).toHaveBeenCalledWith(999);
      expect(snackBar.open).toHaveBeenCalledWith(
        'Folder with ID 999 not found.',
        'Close',
        {duration: 3000},
      );
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);
    });

    it('should redirect to /gallery when folder workspace matches current workspace but still returned 404', () => {
      const snackBar = TestBed.inject(MatSnackBar);
      component.isSelectorMode = false;
      component.isSelectionMode = false;
      component.currentFolderId = 5;

      folderService.getBreadcrumbs.and.returnValue(
        throwError(() => ({status: 404})),
      );
      folderService.getFolderById.and.returnValue(
        of({
          id: 5,
          workspaceId: 1,
          name: 'Folder 5',
          userEmail: 'user@example.com',
          itemCount: 0,
          subfolderCount: 0,
        }),
      );

      component.loadBreadcrumbs();

      expect(folderService.getFolderById).toHaveBeenCalledWith(5);
      expect(snackBar.open).toHaveBeenCalledWith(
        'Folder not found in this workspace.',
        'Close',
        {duration: 3000},
      );
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/gallery']);
    });

    it('should not navigate to /gallery on initial load when currentFolderId is set from route', () => {
      routerSpy.navigate.calls.reset();
      paramMapSubject.next(convertToParamMap({folderId: '42'}));

      expect(component.currentFolderId).toBe(42);
      expect(routerSpy.navigate).not.toHaveBeenCalledWith(['/gallery']);
    });
  });
});
