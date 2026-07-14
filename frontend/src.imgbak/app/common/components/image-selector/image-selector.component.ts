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

import {Component, Inject, OnInit, ViewChild} from '@angular/core';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {finalize, Observable} from 'rxjs';
import {UserService} from '../../services/user.service';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../../services/source-asset.service';
import {AssetTypeEnum} from '../../../admin/source-assets-management/source-asset.model';
import {MediaItem} from '../../models/media-item.model';
import {MediaGalleryComponent} from '../../../gallery/media-gallery/media-gallery.component';
import {ImageCropperDialogComponent} from '../image-cropper-dialog/image-cropper-dialog.component';

export interface MediaItemSelection {
  mediaItem: MediaItem;
  selectedIndex: number;
}

@Component({
  selector: 'app-image-selector',
  templateUrl: './image-selector.component.html',
  styleUrls: ['./image-selector.component.scss'],
})
export class ImageSelectorComponent implements OnInit {
  isUploading = false;
  isDragging = false;
  selectedMediaItems = new Map<string, any>();
  shouldCrop = false;
  currentUserEmail: string | null = null;

  @ViewChild(MediaGalleryComponent) mediaGallery!: MediaGalleryComponent;

  constructor(
    public dialogRef: MatDialogRef<ImageSelectorComponent>,
    private sourceAssetService: SourceAssetService,
    private dialog: MatDialog,
    private userService: UserService,
    @Inject(MAT_DIALOG_DATA)
    public data: {
      mimeType:
        | 'image/*'
        | 'image/png'
        | 'video/mp4'
        | 'video/*'
        | 'audio/*'
        | 'audio/mpeg'
        | null;
      assetType: AssetTypeEnum;
      enableUpscale?: boolean;
      multiSelect?: boolean;
      showFooter?: boolean;
      maxSelection?: number;
    },
  ) {
    this.dialogRef.addPanelClass('image-selector-dialog');
  }

  ngOnInit(): void {
    const userDetails = this.userService.getUserDetails();
    this.currentUserEmail = userDetails?.email || null;
  }

  // This method is called by the file input or drop event inside this component
  handleFileSelect(file: File): void {
    if (file.type.startsWith('image/')) {
      if (this.shouldCrop) {
        // If shouldCrop is true, open the cropper dialog
        const cropperDialogRef = this.dialog.open(ImageCropperDialogComponent, {
          data: {
            imageFile: file,
            assetType: this.data.assetType,
            enableUpscale: this.data.enableUpscale,
          },
          width: '600px',
        });

        cropperDialogRef
          .afterClosed()
          .subscribe((asset: SourceAssetResponseDto) => {
            if (asset) {
              this.dialogRef.close(asset);
            }
          });
      } else {
        // If shouldCrop is false, upload directly
        this.isUploading = true;
        this.sourceAssetService
          .uploadAsset(file, {assetType: this.data.assetType})
          .pipe(finalize(() => (this.isUploading = false)))
          .subscribe(asset => {
            if (asset) {
              this.dialogRef.close(asset);
            }
          });
      }
    } else if (
      file.type.startsWith('video/') ||
      file.type.startsWith('audio/')
    ) {
      // If it's a video or audio, upload it directly from here
      this.isUploading = true;
      this.uploadMediaDirectly(file)
        .pipe(finalize(() => (this.isUploading = false)))
        .subscribe(asset => {
          this.dialogRef.close(asset);
        });
    } else {
      console.error('Unsupported file type selected.');
    }
  }

  private uploadMediaDirectly(file: File): Observable<SourceAssetResponseDto> {
    // No options needed; backend handles video/audio aspect ratio
    return this.sourceAssetService.uploadAsset(file);
  }

  // Keep for backwards compatibility
  private uploadVideoDirectly(file: File): Observable<SourceAssetResponseDto> {
    return this.uploadMediaDirectly(file);
  }

  // Update onFileSelected and onDrop to use the new handler
  onFileSelected(event: Event): void {
    const element = event.currentTarget as HTMLInputElement;
    const fileList: FileList | null = element.files;
    if (fileList && fileList[0]) {
      this.handleFileSelect(fileList[0]);
    }
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = false;
    if (event.dataTransfer?.files[0]) {
      this.handleFileSelect(event.dataTransfer.files[0]);
    }
  }

  openCropperDialog(file: File): void {
    if (file.type.startsWith('image/')) {
      this.dialogRef.close();

      this.dialog.open(ImageCropperDialogComponent, {
        data: {
          imageFile: file,
          assetType: this.data.assetType,
        },
        width: '600px',
      });
    } else {
      console.log('File is not an image, cannot open cropper.');
    }
  }

  onMediaSelected(selection: MediaItemSelection): void {
    const item = selection.mediaItem as any;
    const id = `${item.itemType || 'media_item'}:${item.id}`;
    if (this.selectedMediaItems.has(id)) {
      this.selectedMediaItems.delete(id);
    } else {
      if (this.data.maxSelection === 1) {
        this.selectedMediaItems.clear();
      } else if (
        this.data.maxSelection &&
        this.selectedMediaItems.size >= this.data.maxSelection
      ) {
        return;
      }
      this.selectedMediaItems.set(id, selection);
    }
    // Recreate Map to trigger change detection
    this.selectedMediaItems = new Map(this.selectedMediaItems);
  }

  onMediaItemSelected(selection: MediaItemSelection): void {
    if (this.data.multiSelect || this.data.showFooter) {
      // In multi-select mode or when footer is shown, we don't close on single item selection
      // Instead, we just let MediaGalleryComponent handle the toggle and wait for Select btn
      return;
    }
    const item = selection.mediaItem as any;
    if (item.itemType === 'source_asset') {
      // Map back to SourceAssetResponseDto for backwards compatibility
      const asset: SourceAssetResponseDto = {
        id: item.id,
        userId: String(item.userId || ''),
        gcsUri: item.gcsUris?.[0] || '',
        originalFilename: item.prompt || '',
        mimeType: item.mimeType || '',
        aspectRatio: item.aspectRatio || '',
        fileHash: '',
        createdAt: item.createdAt,
        updatedAt: item.createdAt,
        presignedUrl: item.presignedUrls?.[0] || '',
        presignedThumbnailUrl: item.presignedThumbnailUrls?.[0],
        presignedOriginalUrl: item.originalPresignedUrls?.[0] || '',
      };
      this.dialogRef.close(asset);
    } else {
      this.dialogRef.close(selection);
    }
  }

  closeWithSelection(): void {
    const totalSelected = this.selectedMediaItems.size;
    if (totalSelected === 0) return;

    const results = Array.from(this.selectedMediaItems.values()).map(
      selection => {
        const item = (selection as any).mediaItem as any;
        if (item.itemType === 'source_asset') {
          return {
            id: item.id,
            userId: String(item.userId || ''),
            gcsUri: item.gcsUris?.[0] || '',
            originalFilename: item.prompt || '',
            mimeType: item.mimeType || '',
            aspectRatio: item.aspectRatio || '',
            fileHash: '',
            createdAt: item.createdAt,
            updatedAt: item.createdAt,
            presignedUrl: item.presignedUrls?.[0] || '',
            presignedThumbnailUrl: item.presignedThumbnailUrls?.[0],
            presignedOriginalUrl: item.originalPresignedUrls?.[0] || '',
          } as SourceAssetResponseDto;
        }
        return selection as unknown as MediaItemSelection;
      },
    );

    // If multiSelect is false but we somehow got here, return just the first item
    if (!this.data.multiSelect && results.length > 0) {
      this.dialogRef.close(results[0]);
    } else {
      this.dialogRef.close(results);
    }
  }

  onAssetSelected(asset: SourceAssetResponseDto): void {
    this.dialogRef.close(asset);
  }

  onDragOver(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = true;
  }

  onDragLeave(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = false;
  }

  /**
   * Returns the accept types for the file input.
   * Uses explicit file extensions for better browser/OS compatibility.
   */
  getAcceptTypes(): string {
    if (!this.data.mimeType) {
      return 'image/*,video/*,audio/*,.mp3,.wav,.ogg,.m4a,.aac,.flac,.wma';
    }

    if (
      this.data.mimeType === 'audio/*' ||
      this.data.mimeType === 'audio/mpeg'
    ) {
      // Include explicit audio extensions for better compatibility
      return 'audio/*,.mp3,.wav,.ogg,.m4a,.aac,.flac,.wma,.webm';
    }

    if (
      this.data.mimeType === 'video/*' ||
      this.data.mimeType === 'video/mp4'
    ) {
      return 'video/*,.mp4,.webm,.mov,.avi,.mkv';
    }

    return this.data.mimeType;
  }
}
