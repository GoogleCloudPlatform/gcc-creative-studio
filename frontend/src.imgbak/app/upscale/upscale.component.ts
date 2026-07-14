/**
 * Copyright 2025 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {Component, ChangeDetectorRef, OnInit, OnDestroy} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Subject, Observable} from 'rxjs';
import {takeUntil, distinctUntilChanged} from 'rxjs/operators';
import {Router} from '@angular/router'; // Added Router
import {ImageSelectorComponent} from '../common/components/image-selector/image-selector.component';
import {
  SourceAssetService,
  SourceAssetResponseDto,
} from '../common/services/source-asset.service';
import {GalleryService} from '../gallery/gallery.service';
import {AssetTypeEnum} from '../admin/source-assets-management/source-asset.model';
import {MediaItem, JobStatus} from '../common/models/media-item.model';
import {handleErrorSnackbar} from '../utils/handleMessageSnackbar';
import {MatIconRegistry} from '@angular/material/icon';
import {DomSanitizer, SafeResourceUrl} from '@angular/platform-browser';

interface UploadedAsset {
  name: string;
  url: string;
}
interface AssetPair {
  original: UploadedAsset | null;
  upscaled: UploadedAsset | null;
  aspectRatio?: string;
}

@Component({
  selector: 'app-upscale',
  templateUrl: './upscale.component.html',
  styleUrls: ['./upscale.component.scss'],
})
export class UpscaleComponent implements OnInit, OnDestroy {
  assetPair: AssetPair = {original: null, upscaled: null};
  isLoadingUpscale = false;
  sliderValue = 50;
  showErrorOverlay = true; // Controls visibility of the error overlay
  readonly assetType = AssetTypeEnum.GENERIC_IMAGE;
  public readonly JobStatus = JobStatus;

  // New properties for selection
  upscaleFactor = '2x';
  upscaleFactors: string[] = ['2x', '3x', '4x'];

  enhanceInputImage = false;
  imagePreservationFactor: number | null = null;

  selectedAsset: SourceAssetResponseDto | null = null;
  completedJobId: number | null = null; // Track completed job ID

  private destroy$ = new Subject<void>();

  // 1. Unified job stream for the full-screen overlay
  activeUpscaleJob$: Observable<MediaItem | null>;

  constructor(
    private dialog: MatDialog,
    private cdr: ChangeDetectorRef,
    private sourceAssetService: SourceAssetService,
    private galleryService: GalleryService,
    private _snackBar: MatSnackBar,
    private router: Router,
    public matIconRegistry: MatIconRegistry,
    private sanitizer: DomSanitizer,
  ) {
    this.matIconRegistry.addSvgIcon(
      'mobile-white-gemini-spark-icon',
      this.setPath(`${this.path}/mobile-white-gemini-spark-icon.svg`),
    );

    // Initialize the combined job stream
    this.activeUpscaleJob$ = this.sourceAssetService.activeUpscaleJob$;
  }

  private path = '../../assets/images';

  private setPath(url: string): SafeResourceUrl {
    return this.sanitizer.bypassSecurityTrustResourceUrl(url);
  }

  ngOnInit(): void {
    /**
     * 2. Subscribe to job changes to update the local component state
     * This handles the image comparison view logic.
     */
    this.activeUpscaleJob$
      .pipe(
        takeUntil(this.destroy$),
        distinctUntilChanged(
          (prev, curr) =>
            prev?.id === curr?.id && prev?.status === curr?.status,
        ),
      )
      .subscribe(activeJob => {
        if (activeJob) {
          // Sync local loading state
          this.isLoadingUpscale = activeJob.status === JobStatus.PROCESSING;

          if (activeJob.status === JobStatus.COMPLETED) {
            // Reset error overlay for future jobs
            this.showErrorOverlay = true;
            this.completedJobId = activeJob.id; // Store job ID

            const originalUrl =
              activeJob.originalPresignedUrls &&
              activeJob.originalPresignedUrls.length > 0
                ? activeJob.originalPresignedUrls[0]
                : (activeJob as any).url; // Fallback if needed

            const upscaledUrl =
              activeJob.presignedUrls && activeJob.presignedUrls.length > 0
                ? activeJob.presignedUrls[0]
                : (activeJob as any).url;

            this.assetPair.original = {
              name: 'Original Image',
              url: originalUrl,
            };
            this.assetPair.upscaled = {
              name: 'Upscaled Image',
              url: upscaledUrl,
            };
            this.assetPair.aspectRatio = activeJob.aspectRatio;

            // Clear selected asset as we now have the result
            this.selectedAsset = null;
          } else if (activeJob.status === JobStatus.FAILED) {
            this.isLoadingUpscale = false;
            this.showErrorOverlay = false;
            this.completedJobId = null;

            if (activeJob.errorMessage) {
              handleErrorSnackbar(
                this._snackBar,
                {message: activeJob.errorMessage},
                'Upscale Failed',
              );
            }
          }

          this.cdr.detectChanges();
        }
      });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  closeErrorOverlay(): void {
    this.showErrorOverlay = false;
    this.isLoadingUpscale = false;
  }

  setUpscaleFactor(factor: string): void {
    this.upscaleFactor = factor;
  }

  openUploaderDialog(event?: MouseEvent): void {
    if (event) event.stopPropagation();

    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: 'image/*',
        assetType: this.assetType,
        enableUpscale: false,
        showFooter: true,
        maxSelection: 1,
      },
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        // Handle the result which could be a SourceAssetResponseDto or an object wrapper
        let asset: SourceAssetResponseDto | null = null;

        // Check if it's the object wrapper from ImageCropperDialogComponent
        if (result.asset) {
          asset = result.asset;
        } else if (result.id) {
          // It's likely the SourceAssetResponseDto directly
          asset = result as SourceAssetResponseDto;
        }

        if (asset) {
          this.selectedAsset = asset;
          this.assetPair.original = {
            name: asset.originalFilename,
            url: asset.presignedUrl || asset.gcsUri,
          };
          this.assetPair.aspectRatio = asset.aspectRatio;
          this.assetPair.upscaled = null; // Reset upscaled
          this.completedJobId = null; // Reset previous job ID
          this.cdr.detectChanges();
        }
      }
    });
  }

  startUpscale(): void {
    if (!this.selectedAsset) return;

    this.isLoadingUpscale = true;
    // Use the service to start the upscale job
    this.sourceAssetService
      .upscaleExistingAsset(this.selectedAsset, {
        upscaleFactor: 'x' + this.upscaleFactor.replace('x', ''), // Ensure format "x2", "x4"
        enhance_input_image: this.enhanceInputImage,
        image_preservation_factor: this.imagePreservationFactor,
      })
      .subscribe({
        next: job => {
          console.log('Upscale job started:', job);
          // The subscription to activeUpscaleJob$ will handle the rest
        },
        error: err => {
          console.error('Failed to start upscale:', err);
          this.isLoadingUpscale = false;
          handleErrorSnackbar(this._snackBar, err, 'Upscale Start Failed');
        },
      });
  }

  async downloadUpscaled(): Promise<void> {
    if (!this.assetPair.upscaled) return;
    const imageUrl = this.assetPair.upscaled.url;

    try {
      const response = await fetch(imageUrl);
      const blob = await response.blob();
      const blobUrl = window.URL.createObjectURL(blob);

      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = `upscaled-image-${Date.now()}.png`;

      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(blobUrl);
    } catch (error) {
      console.error(
        'Download failed. Falling back to default link behavior.',
        error,
      );
      window.open(imageUrl, '_blank');
    }
  }

  navigateToDetails(): void {
    if (this.completedJobId) {
      void this.router.navigate(['/gallery', this.completedJobId]);
    }
  }

  clearImage(event: MouseEvent): void {
    event.stopPropagation();
    this.assetPair = {original: null, upscaled: null};
    this.isLoadingUpscale = false;
    this.selectedAsset = null;
    this.completedJobId = null;
    // Notify services to clear status to allow new uploads
    (this.sourceAssetService as any).activeUpscaleJob.next(null);
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.openUploaderDialog();
  }

  get aspectRatioValue(): number {
    if (!this.assetPair.aspectRatio) return 1;
    const parts = this.assetPair.aspectRatio.split(':');
    if (parts.length !== 2) return 1;
    return parseFloat(parts[0]) / parseFloat(parts[1]);
  }
}
