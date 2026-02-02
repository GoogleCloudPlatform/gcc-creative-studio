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

import { Component, Inject } from '@angular/core';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import { finalize, Observable } from 'rxjs';
import { AssetTypeEnum } from '../../../admin/source-assets-management/source-asset.model';
import { MediaItem } from '../../models/media-item.model';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../../services/source-asset.service';
import { ImageCropperDialogComponent } from '../image-cropper-dialog/image-cropper-dialog.component';

export interface MediaItemSelection {
  mediaItem: MediaItem;
  selectedIndex: number;
}

@Component({
  selector: 'app-image-selector',
  templateUrl: './image-selector.component.html',
  styleUrls: ['./image-selector.component.scss'],
})
export class ImageSelectorComponent {
  isUploading = false;

  constructor(
    public dialogRef: MatDialogRef<ImageSelectorComponent>,
    private sourceAssetService: SourceAssetService,
    private dialog: MatDialog, // Inject MatDialog to open the new dialog
    @Inject(MAT_DIALOG_DATA)
    public data: {
      mimeType: 'image/*' | 'image/png' | 'video/mp4' | 'video/*' | 'audio/*' | 'audio/mpeg' | null;
      assetType: AssetTypeEnum;
    },
  ) { }

  // This method is called by the file input or drop event inside this component
  handleFileSelect(file: File): void {
    if (file.type.startsWith('image/')) {
      // If it's an image, open the cropper dialog
      const cropperDialogRef = this.dialog.open(ImageCropperDialogComponent, {
        data: {
          imageFile: file,
          assetType: this.data.assetType,
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
    } else if (file.type.startsWith('video/') || file.type.startsWith('audio/')) {
      // If it's a video or audio, upload it directly from here
      this.isUploading = true;
      this.uploadMediaDirectly(file)
        .pipe(finalize(() => (this.isUploading = false)))
        .subscribe(asset => {
          this.dialogRef.close(asset);
        });
    } else if (file.type.startsWith('audio/')) {
      this.isUploading = true;
      this.uploadVideoDirectly(file) // Reusing upload logic as it's just a file upload
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

  onMediaItemSelected(selection: MediaItemSelection): void {
    this.dialogRef.close(selection);
  }

  onAssetSelected(asset: SourceAssetResponseDto): void {
    this.dialogRef.close(asset);
  }

  onDragOver(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
  }

  /**
   * Returns the accept types for the file input.
   * Uses explicit file extensions for better browser/OS compatibility.
   */
  getAcceptTypes(): string {
    if (!this.data.mimeType) {
      return 'image/*,video/*,audio/*,.mp3,.wav,.ogg,.m4a,.aac,.flac,.wma';
    }
    
    if (this.data.mimeType === 'audio/*' || this.data.mimeType === 'audio/mpeg') {
      // Include explicit audio extensions for better compatibility
      return 'audio/*,.mp3,.wav,.ogg,.m4a,.aac,.flac,.wma,.webm';
    }
    
    if (this.data.mimeType === 'video/*' || this.data.mimeType === 'video/mp4') {
      return 'video/*,.mp4,.webm,.mov,.avi,.mkv';
    }
    
    return this.data.mimeType;
  }
}
