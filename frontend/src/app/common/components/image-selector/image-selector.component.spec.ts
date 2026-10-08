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

import {NO_ERRORS_SCHEMA} from '@angular/core';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {By} from '@angular/platform-browser';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {of, throwError} from 'rxjs';
import {AssetTypeEnum} from '../../../admin/source-assets-management/source-asset.model';
import {
  FolderSelectionResult,
  GalleryFolderLocation,
} from '../../models/folder.model';
import {MediaItem} from '../../models/media-item.model';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../../services/source-asset.service';
import {UserService} from '../../services/user.service';
import {ImageCropperDialogComponent} from '../image-cropper-dialog/image-cropper-dialog.component';
import {StudioButtonComponent} from '../studio-button/studio-button.component';
import {
  ImageSelectorComponent,
  ImageSelectorDialogData,
  MediaItemSelection,
} from './image-selector.component';

const UPLOADED_ASSET: SourceAssetResponseDto = {
  id: 11,
  userId: '3',
  gcsUri: 'gs://bucket/a.png',
  originalFilename: 'a.png',
  mimeType: 'image/png',
  aspectRatio: '1:1',
  fileHash: 'hash',
  createdAt: '2026-01-01',
  updatedAt: '2026-01-01',
  presignedUrl: 'https://signed/a.png',
  presignedOriginalUrl: 'https://signed/a-original.png',
};

const SUMMER_LOCATION: GalleryFolderLocation = {
  folderId: 2,
  breadcrumbs: [
    {id: 1, name: 'Marketing', parentId: null},
    {id: 2, name: 'Summer', parentId: 1},
  ],
};

function buildSelection(
  mediaItem: Partial<MediaItem> & {itemType?: string},
): MediaItemSelection {
  return {mediaItem: mediaItem as MediaItem, selectedIndex: 0};
}

function buildDropEvent(dataTransfer: Partial<DataTransfer>): DragEvent {
  return {
    preventDefault: jasmine.createSpy('preventDefault'),
    stopPropagation: jasmine.createSpy('stopPropagation'),
    dataTransfer,
  } as unknown as DragEvent;
}

describe('ImageSelectorComponent', () => {
  let fixture: ComponentFixture<ImageSelectorComponent>;
  let component: ImageSelectorComponent;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<ImageSelectorComponent>>;
  let sourceAssetServiceSpy: jasmine.SpyObj<SourceAssetService>;

  async function setup(data: ImageSelectorDialogData): Promise<void> {
    dialogRefSpy = jasmine.createSpyObj<MatDialogRef<ImageSelectorComponent>>(
      'MatDialogRef',
      ['close', 'addPanelClass'],
    );
    sourceAssetServiceSpy = jasmine.createSpyObj<SourceAssetService>(
      'SourceAssetService',
      ['uploadAsset', 'downloadExternalAsset'],
    );
    sourceAssetServiceSpy.uploadAsset.and.returnValue(of(UPLOADED_ASSET));

    await TestBed.configureTestingModule({
      declarations: [ImageSelectorComponent, StudioButtonComponent],
      providers: [
        {provide: MatDialogRef, useValue: dialogRefSpy},
        {provide: MAT_DIALOG_DATA, useValue: data},
        {provide: SourceAssetService, useValue: sourceAssetServiceSpy},
        {
          provide: MatDialog,
          useValue: jasmine.createSpyObj('MatDialog', ['open']),
        },
        {
          provide: UserService,
          useValue: {getUserDetails: () => ({email: 'me@example.com'})},
        },
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(ImageSelectorComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  const query = (selector: string): HTMLElement | null =>
    fixture.nativeElement.querySelector(selector);
  const buttonById = (id: string): StudioButtonComponent =>
    fixture.debugElement
      .query(By.css(`#${id}`))
      .injector.get(StudioButtonComponent);

  describe('media mode', () => {
    beforeEach(async () => {
      await setup({
        mimeType: 'image/*',
        assetType: AssetTypeEnum.GENERIC_IMAGE,
      });
    });

    it('keeps the upload controls, both tabs and the media title', () => {
      expect(component.isFolderMode).toBeFalse();
      expect(query('.selector-title')?.textContent).toContain('Select Media');
      expect(query('#image-selector-upload-btn')).not.toBeNull();
      expect(fixture.nativeElement.querySelectorAll('mat-tab').length).toBe(2);
      expect(query('.folder-footer')).toBeNull();
      expect(component.currentUserEmail).toBe('me@example.com');
    });

    it('shows the drop overlay while dragging a file', () => {
      const dragEvent = buildDropEvent({dropEffect: 'none'});
      component.onDragOver(dragEvent);
      fixture.detectChanges();
      expect(query('.drop-overlay')).not.toBeNull();

      component.onDragLeave(dragEvent);
      fixture.detectChanges();
      expect(query('.drop-overlay')).toBeNull();
    });

    it('closes with a mapped source asset on single selection', () => {
      component.onMediaItemSelected(
        buildSelection({
          id: 5,
          itemType: 'source_asset',
          userId: 3,
          gcsUris: ['gs://bucket/b.png'],
          presignedUrls: ['https://signed/b.png'],
          mimeType: 'image/png',
        } as Partial<MediaItem>),
      );
      expect(dialogRefSpy.close).toHaveBeenCalledWith(
        jasmine.objectContaining({
          id: 5,
          userId: '3',
          gcsUri: 'gs://bucket/b.png',
          presignedUrl: 'https://signed/b.png',
        }),
      );
    });

    it('closes with the raw selection for generated media', () => {
      const selection = buildSelection({id: 9});
      component.onMediaItemSelected(selection);
      expect(dialogRefSpy.close).toHaveBeenCalledWith(selection);
    });

    it('closes with the uploaded asset when uploading an image', () => {
      const file = new File(['x'], 'photo.png', {type: 'image/png'});
      component.handleFileSelect(file);
      expect(sourceAssetServiceSpy.uploadAsset).toHaveBeenCalledWith(file, {
        assetType: AssetTypeEnum.GENERIC_IMAGE,
      });
      expect(dialogRefSpy.close).toHaveBeenCalledWith(UPLOADED_ASSET);
      expect(component.isUploading).toBeFalse();
    });

    it('opens the cropper before uploading when cropping is enabled', () => {
      const cropSpy = spyOn(
        ImageCropperDialogComponent,
        'open',
      ).and.returnValue(of(UPLOADED_ASSET));
      component.shouldCrop = true;
      component.handleFileSelect(
        new File(['x'], 'photo.png', {type: 'image/png'}),
      );
      expect(cropSpy).toHaveBeenCalled();
      expect(dialogRefSpy.close).toHaveBeenCalledWith(UPLOADED_ASSET);
    });

    it('uploads videos directly', () => {
      const file = new File(['x'], 'clip.mp4', {type: 'video/mp4'});
      component.handleFileSelect(file);
      expect(sourceAssetServiceSpy.uploadAsset).toHaveBeenCalledWith(file);
      expect(dialogRefSpy.close).toHaveBeenCalledWith(UPLOADED_ASSET);
    });

    it('rejects unsupported files', () => {
      const errorSpy = spyOn(console, 'error');
      component.handleFileSelect(
        new File(['x'], 'notes.txt', {type: 'text/plain'}),
      );
      expect(errorSpy).toHaveBeenCalled();
      expect(sourceAssetServiceSpy.uploadAsset).not.toHaveBeenCalled();
    });

    it('uploads the file picked from the file input', () => {
      const handleSpy = spyOn(component, 'handleFileSelect');
      const file = new File(['x'], 'photo.png', {type: 'image/png'});
      component.onFileSelected({
        currentTarget: {files: [file]},
      } as unknown as Event);
      expect(handleSpy).toHaveBeenCalledWith(file);
    });

    it('uploads a dropped file', () => {
      const handleSpy = spyOn(component, 'handleFileSelect');
      const file = new File(['x'], 'photo.png', {type: 'image/png'});
      component.onDrop(buildDropEvent({files: [file] as unknown as FileList}));
      expect(handleSpy).toHaveBeenCalledWith(file);
    });

    it('alerts when the drop contains no readable file', () => {
      spyOn(console, 'error');
      const alertSpy = spyOn(window, 'alert');
      component.onDrop(buildDropEvent({files: [] as unknown as FileList}));
      expect(alertSpy).toHaveBeenCalled();
    });

    describe('dropping data transfer items', () => {
      function buildItem(
        kind: string,
        type: string,
        overrides: Partial<DataTransferItem> = {},
      ): DataTransferItem {
        return {kind, type, ...overrides} as DataTransferItem;
      }

      function dropItems(items: DataTransferItem[]): void {
        component.onDrop(
          buildDropEvent({
            files: [] as unknown as FileList,
            items: items as unknown as DataTransferItemList,
          }),
        );
      }

      function uriItem(uriList: string): DataTransferItem {
        return buildItem('string', 'text/uri-list', {
          getAsString: (callback: FunctionStringCallback | null) =>
            callback?.(uriList),
        });
      }

      it('uploads a file item', () => {
        const handleSpy = spyOn(component, 'handleFileSelect');
        const file = new File(['x'], 'photo.png', {type: 'image/png'});
        dropItems([buildItem('file', 'image/png', {getAsFile: () => file})]);
        expect(handleSpy).toHaveBeenCalledWith(file);
      });

      it('downloads and uploads an image dropped from another page', () => {
        const handleSpy = spyOn(component, 'handleFileSelect');
        const blob = new Blob(['x'], {type: 'image/png'});
        sourceAssetServiceSpy.downloadExternalAsset.and.returnValue(of(blob));

        dropItems([uriItem('# comment\nhttps://example.com/cat.png\n')]);

        expect(
          sourceAssetServiceSpy.downloadExternalAsset,
        ).toHaveBeenCalledWith('https://example.com/cat.png');
        const uploaded = handleSpy.calls.mostRecent().args[0];
        expect(uploaded.type).toBe('image/png');
        expect(component.isUploading).toBeFalse();
      });

      it('alerts when the dropped image cannot be downloaded', () => {
        spyOn(console, 'error');
        const alertSpy = spyOn(window, 'alert');
        sourceAssetServiceSpy.downloadExternalAsset.and.returnValue(
          throwError(() => new Error('cors')),
        );

        dropItems([uriItem('https://example.com/cat.png')]);

        expect(alertSpy).toHaveBeenCalled();
        expect(component.isUploading).toBeFalse();
      });

      it('stops uploading when the dropped link list has no url', () => {
        dropItems([uriItem('# only a comment')]);
        expect(
          sourceAssetServiceSpy.downloadExternalAsset,
        ).not.toHaveBeenCalled();
        expect(component.isUploading).toBeFalse();
      });
    });

    it('keeps the dialog open when the cropper is dismissed', () => {
      spyOn(ImageCropperDialogComponent, 'open').and.returnValue(of(undefined));
      component.shouldCrop = true;
      component.handleFileSelect(
        new File(['x'], 'photo.png', {type: 'image/png'}),
      );
      expect(dialogRefSpy.close).not.toHaveBeenCalled();
    });

    it('returns the accepted file types for each media type', () => {
      expect(component.getAcceptTypes()).toBe('image/*');
      component.data.mimeType = 'audio/*';
      expect(component.getAcceptTypes()).toContain('.mp3');
      component.data.mimeType = 'video/*';
      expect(component.getAcceptTypes()).toContain('.mp4');
      component.data.mimeType = null;
      expect(component.getAcceptTypes()).toContain('video/*');
    });

    it('closes with the picked asset', () => {
      component.onAssetSelected(UPLOADED_ASSET);
      expect(dialogRefSpy.close).toHaveBeenCalledWith(UPLOADED_ASSET);
    });
  });

  describe('media mode with multi-select', () => {
    beforeEach(async () => {
      await setup({
        mimeType: 'image/*',
        assetType: AssetTypeEnum.GENERIC_IMAGE,
        multiSelect: true,
        maxSelection: 2,
      });
    });

    it('keeps the dialog open on item click and closes with all selections', () => {
      const generated = buildSelection({id: 1});
      const uploaded = buildSelection({
        id: 2,
        itemType: 'source_asset',
      } as Partial<MediaItem>);
      const extra = buildSelection({id: 3});

      component.onMediaItemSelected(generated);
      expect(dialogRefSpy.close).not.toHaveBeenCalled();

      component.onMediaSelected(generated);
      component.onMediaSelected(uploaded);
      component.onMediaSelected(extra);
      expect(component.selectedMediaItems.size).toBe(2);
      fixture.detectChanges();
      expect(query('.selector-footer')).not.toBeNull();

      component.closeWithSelection();
      const closedWith = dialogRefSpy.close.calls.mostRecent().args[0];
      expect(Array.isArray(closedWith)).toBeTrue();
      expect((closedWith as unknown[]).length).toBe(2);
    });

    it('toggles a selected item off', () => {
      const generated = buildSelection({id: 1});
      component.onMediaSelected(generated);
      component.onMediaSelected(generated);
      expect(component.selectedMediaItems.size).toBe(0);
      component.closeWithSelection();
      expect(dialogRefSpy.close).not.toHaveBeenCalled();
    });
  });

  describe('folder mode', () => {
    beforeEach(async () => {
      await setup({
        mimeType: 'video/*',
        assetType: AssetTypeEnum.GENERIC_IMAGE,
        selectionTarget: 'folder',
        initialFolderId: 2,
      });
    });

    it('hides the upload controls, drop overlay and second tab', () => {
      component.isDragging = true;
      fixture.detectChanges();

      expect(component.isFolderMode).toBeTrue();
      expect(component.initialFolderId).toBe(2);
      expect(query('.selector-title')?.textContent).toContain(
        'Select a Folder',
      );
      expect(query('#image-selector-upload-btn')).toBeNull();
      expect(query('mat-slide-toggle')).toBeNull();
      expect(query('.drop-overlay')).toBeNull();
      expect(fixture.nativeElement.querySelectorAll('mat-tab').length).toBe(1);
    });

    it('disables "Use this folder" at the root', () => {
      expect(component.canConfirmFolder()).toBeFalse();
      expect(query('#folder-selector-location')?.textContent).toContain(
        'All Media',
      );
      expect(buttonById('folder-selector-confirm-btn').disabled).toBeTrue();

      component.confirmFolderSelection();
      expect(dialogRefSpy.close).not.toHaveBeenCalled();
    });

    it('enables "Use this folder" once a folder is open', () => {
      component.onCurrentFolderChange(SUMMER_LOCATION);
      fixture.detectChanges();

      expect(component.canConfirmFolder()).toBeTrue();
      const location = query('#folder-selector-location');
      expect(location?.textContent).toContain('Marketing / Summer');
      expect(location?.title).toBe('Marketing / Summer');
      expect(buttonById('folder-selector-confirm-btn').disabled).toBeFalse();
    });

    it('closes with the current folder on confirm', () => {
      component.onCurrentFolderChange(SUMMER_LOCATION);
      fixture.detectChanges();

      query('#folder-selector-confirm-btn')?.click();

      const expected: FolderSelectionResult = {
        folderId: 2,
        folderName: 'Summer',
        path: 'Marketing / Summer',
      };
      expect(dialogRefSpy.close).toHaveBeenCalledWith(expected);
    });

    it('closes without a result on cancel', () => {
      query('#folder-selector-cancel-btn')?.click();
      expect(dialogRefSpy.close).toHaveBeenCalledWith();
    });

    it('ignores media clicks, selections, drops and uploads', () => {
      const selection = buildSelection({id: 1});
      component.onMediaItemSelected(selection);
      component.onMediaSelected(selection);
      component.handleFileSelect(
        new File(['x'], 'photo.png', {type: 'image/png'}),
      );
      const handleSpy = spyOn(component, 'handleFileSelect');
      component.onDrop(
        buildDropEvent({
          files: [new File(['x'], 'photo.png')] as unknown as FileList,
        }),
      );

      expect(dialogRefSpy.close).not.toHaveBeenCalled();
      expect(component.selectedMediaItems.size).toBe(0);
      expect(sourceAssetServiceSpy.uploadAsset).not.toHaveBeenCalled();
      expect(handleSpy).not.toHaveBeenCalled();
      expect(component.isDragging).toBeFalse();
    });
  });
});
