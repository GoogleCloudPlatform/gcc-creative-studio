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

import {
  AfterViewInit,
  Component,
  ElementRef,
  HostListener,
  Inject,
  OnDestroy,
  ViewChild,
  signal,
} from '@angular/core';
import {
  MAT_DIALOG_DATA,
  MatDialogRef,
  MatDialog,
} from '@angular/material/dialog';
import {
  ImageCroppedEvent,
  ImageTransform,
  CropperOptions,
} from 'ngx-image-cropper';
import {HttpClient} from '@angular/common/http';
import {Observable, finalize} from 'rxjs';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../../services/source-asset.service';
import {
  AssetScopeEnum,
  AssetTypeEnum,
} from '../../../admin/source-assets-management/source-asset.model';
import {ReferenceImage} from '../../models/search.model';
import {environment} from '../../../../environments/environment';
import {CanvasDrawer} from './canvas-drawer';

export enum ImageEditorMode {
  CROP = 'crop',
  DRAW = 'draw',
}

export enum DrawingTool {
  BRUSH = 'brush',
  TEXT = 'text',
  RECTANGLE = 'rectangle',
}

interface AspectRatio {
  label: string;
  value: number;
  stringValue: string;
}

interface ImageCropperDialogData {
  imageFile?: File;
  imageUrl?: string;
  assetType?: AssetTypeEnum;
  aspectRatios?: AspectRatio[];
  enableUpscale?: boolean;
}

interface TextInputCanvas {
  value: string;
  position: {x: number; y: number};
  pendingTextCoords: {x: number; y: number};
}

@Component({
  selector: 'app-image-cropper-dialog',
  templateUrl: './image-cropper-dialog.component.html',
  styleUrls: ['./image-cropper-dialog.component.scss'],
})
export class ImageCropperDialogComponent implements AfterViewInit, OnDestroy {
  @ViewChild('drawingCanvas') drawingCanvas!: ElementRef<HTMLCanvasElement>;
  @ViewChild('textInput') textInputRef?: ElementRef<HTMLInputElement>;

  readonly ImageEditorMode = ImageEditorMode;
  readonly DrawingTool = DrawingTool;

  isUploading = false;
  loadingMessage: string | null = null;
  imageFile: File | null = null; // Initialize as null

  canvasDrawer: CanvasDrawer | null = null;
  textInputCanvas: TextInputCanvas | null = null;

  // Signals for drawing controls
  activeMode = signal<ImageEditorMode>(ImageEditorMode.CROP);
  isPanelOpen = signal<boolean>(true);
  activeDrawTool = signal<DrawingTool>(DrawingTool.BRUSH);
  brushColor = signal<string>('#ff3b30');
  brushSize = signal<number>(16);

  presetColors = [
    '#ffffff',
    '#000000',
    '#ff3b30',
    '#34c759',
    '#007aff',
    '#ffcc00',
    '#af52de',
  ];

  canUndo = signal<boolean>(false);
  canRedo = signal<boolean>(false);

  croppedImageBlob: Blob | null = null;
  aspectRatios: AspectRatio[] = [];
  currentAspectRatio: number;
  containWithinAspectRatio = false;
  backgroundColor = 'black';

  transform: ImageTransform = {
    translateUnit: 'px',
    scale: 1,
    rotate: 0,
    flipH: false,
    flipV: false,
  };
  canvasRotation = 0;
  options: Partial<CropperOptions>;

  static open(
    dialog: MatDialog,
    data: ImageCropperDialogData,
  ): Observable<SourceAssetResponseDto | undefined> {
    const dialogData: ImageCropperDialogData = {
      assetType: AssetTypeEnum.GENERIC_IMAGE,
      ...data,
    };
    return dialog
      .open(ImageCropperDialogComponent, {
        data: dialogData,
        width: '95vw',
        height: '95vh',
        maxWidth: '95vw',
        maxHeight: '95vh',
      })
      .afterClosed();
  }

  static openEditPromptReferenceImage(
    dialog: MatDialog,
    data: {index: number; ref: ReferenceImage},
    referenceImages: ReferenceImage[],
    saveState: () => void,
  ): void {
    const previewUrl = data.ref?.previewUrl;
    if (!previewUrl) return;

    ImageCropperDialogComponent.open(dialog, {imageUrl: previewUrl}).subscribe(
      result => {
        if (result && result.id) {
          referenceImages[data.index] = {
            ...referenceImages[data.index],
            sourceAssetId: result.id,
            sourceMediaItem: undefined,
            previewUrl:
              result.presignedUrl || result.presignedThumbnailUrl || previewUrl,
          };
          saveState();
        }
      },
    );
  }

  constructor(
    public dialogRef: MatDialogRef<ImageCropperDialogComponent>,
    private http: HttpClient,
    private sourceAssetService: SourceAssetService,
    @Inject(MAT_DIALOG_DATA)
    public data: ImageCropperDialogData,
  ) {
    this.aspectRatios = data.aspectRatios || [
      {label: '1:1 Square', value: 1 / 1, stringValue: '1:1'},
      {label: '16:9 Horizontal', value: 16 / 9, stringValue: '16:9'},
      {label: '9:16 Vertical', value: 9 / 16, stringValue: '9:16'},
      {label: '3:4 Portrait', value: 3 / 4, stringValue: '3:4'},
      {label: '4:3 Pin', value: 4 / 3, stringValue: '4:3'},
    ];
    this.currentAspectRatio = this.aspectRatios[0].value;

    // Initialize the options object
    this.options = {
      aspectRatio: this.currentAspectRatio,
      maintainAspectRatio: true,
      containWithinAspectRatio: this.containWithinAspectRatio,
      backgroundColor: this.backgroundColor,
      autoCrop: true,
    };
    this.dialogRef.addPanelClass('image-cropper-dialog');
    this.loadImage();
  }

  private loadImage(): void {
    if (this.data.imageUrl && !this.data.imageFile) {
      this.loadingMessage = 'Loading image...';
      this.http.get(this.data.imageUrl, {responseType: 'blob'}).subscribe({
        next: blob => {
          const file = new File([blob], 'remote-image.png', {
            type: blob.type || 'image/png',
          });
          this.handleFile(file);
        },
        error: err => {
          console.error('Failed to load image from URL:', err);
          this.loadingMessage = null;
          this.dialogRef.close();
        },
      });
    } else if (this.data.imageFile) {
      this.handleFile(this.data.imageFile); // Handle the file on init
    }
  }

  // --- Start: New file handling logic ---
  handleFile(file: File): void {
    const supportedTypes = [
      'image/jpeg',
      'image/jpg',
      'image/gif',
      'image/png',
      'image/webp',
    ];
    if (supportedTypes.includes(file.type)) {
      // If the format is supported, load it directly into the cropper
      this.imageFile = file;
      this.loadingMessage = null;
    } else {
      // If the format is unsupported (like AVIF), convert it via the backend
      this.loadingMessage = 'Converting image...';
      this.convertImageOnBackend(file)
        .pipe(finalize(() => (this.loadingMessage = null)))
        .subscribe({
          next: pngBlob => {
            // Create a new File from the returned PNG blob and load it
            this.imageFile = new File([pngBlob], 'converted-image.png', {
              type: 'image/png',
            });
          },
          error: err => {
            console.error('Image conversion failed:', err);
            this.dialogRef.close(); // Close dialog on conversion failure
          },
        });
    }
  }

  private convertImageOnBackend(file: File): Observable<Blob> {
    const formData = new FormData();
    formData.append('file', file);
    // Assumes you create a new backend endpoint for this
    const convertUrl = `${environment.backendURL}/source_assets/convert-to-png`;
    return this.http.post(convertUrl, formData, {responseType: 'blob'});
  }

  // --- Start: Add Event Handlers ---
  onAspectRatioChange(newRatio: number): void {
    this.currentAspectRatio = newRatio;
    this.options = {...this.options, aspectRatio: newRatio};
  }

  onBackgroundColorChange(newColor: string): void {
    this.backgroundColor = newColor;
    this.options = {...this.options, backgroundColor: newColor};
  }

  // --- Start: Add New Control Methods ---
  rotateLeft() {
    this.canvasRotation--;
  }

  rotateRight() {
    this.canvasRotation++;
  }

  moveLeft() {
    this.transform = {
      ...this.transform,
      translateH: (this.transform.translateH || 0) - 5,
    };
  }

  moveRight() {
    this.transform = {
      ...this.transform,
      translateH: (this.transform.translateH || 0) + 5,
    };
  }

  moveDown() {
    this.transform = {
      ...this.transform,
      translateV: (this.transform.translateV || 0) + 5,
    };
  }

  moveUp() {
    this.transform = {
      ...this.transform,
      translateV: (this.transform.translateV || 0) - 5,
    };
  }

  flipHorizontal() {
    this.transform = {...this.transform, flipH: !this.transform.flipH};
  }

  flipVertical() {
    this.transform = {...this.transform, flipV: !this.transform.flipV};
  }

  zoomOut() {
    this.transform = {
      ...this.transform,
      scale: (this.transform.scale || 1) - 0.1,
    };
  }

  zoomIn() {
    this.transform = {
      ...this.transform,
      scale: (this.transform.scale || 1) + 0.1,
    };
  }
  // --- End: Add New Control Methods ---

  ngAfterViewInit(): void {
    if (this.drawingCanvas?.nativeElement && !this.canvasDrawer) {
      this.initCanvasDrawer();
    }
  }

  ngOnDestroy(): void {
    if (this.canvasDrawer) {
      this.canvasDrawer.destroy();
      this.canvasDrawer = null;
    }
  }

  private initCanvasDrawer(): void {
    if (!this.drawingCanvas?.nativeElement) return;
    this.canvasDrawer = new CanvasDrawer(this.drawingCanvas.nativeElement);
    this.syncCanvasDrawerSettings();
    this.canvasDrawer.onTextRequested = (x, y, clientX, clientY) =>
      this.handleTextRequested(x, y, clientX, clientY);
    this.canvasDrawer.onHistoryChange = () => this.updateHistorySignals();
  }

  private syncCanvasDrawerSettings(): void {
    if (!this.canvasDrawer) return;
    this.canvasDrawer.mode = this.activeDrawTool();
    this.canvasDrawer.strokeColor = this.brushColor();
    this.canvasDrawer.strokeWidth = this.brushSize();
    this.canvasDrawer.fontSize = this.brushSize();
  }

  private updateHistorySignals(): void {
    if (!this.canvasDrawer) return;
    this.canUndo.set(this.canvasDrawer.canUndo());
    this.canRedo.set(this.canvasDrawer.canRedo());
  }

  handleTextRequested(
    x: number,
    y: number,
    clientX: number,
    clientY: number,
  ): void {
    this.commitText();
    const rect = this.drawingCanvas?.nativeElement?.parentElement
      ? this.drawingCanvas.nativeElement.parentElement.getBoundingClientRect()
      : {left: 0, top: 0};
    this.textInputCanvas = {
      value: '',
      position: {
        x: clientX - rect.left,
        y: clientY - rect.top,
      },
      pendingTextCoords: {x, y},
    };

    setTimeout(() => this.textInputRef?.nativeElement?.focus());
  }

  commitText(): void {
    if (!this.textInputCanvas || !this.canvasDrawer) return;
    const text = this.textInputCanvas.value.trim();
    if (text) {
      this.canvasDrawer.addText(
        text,
        this.textInputCanvas.pendingTextCoords.x,
        this.textInputCanvas.pendingTextCoords.y,
      );
    }
    this.textInputCanvas = null;
  }

  @HostListener('document:keydown', ['$event'])
  onDocumentKeydown(event: KeyboardEvent): void {
    // Only process shortcuts if we are in draw mode and have a drawer
    if (this.activeMode() !== ImageEditorMode.DRAW || !this.canvasDrawer) {
      return;
    }

    const target = event.target as HTMLElement;
    // Do not trigger undo/redo if the user is typing in an input or text area
    if (
      target &&
      (target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable)
    ) {
      return;
    }

    if (event.ctrlKey || event.metaKey) {
      if (event.key.toLowerCase() === 'z') {
        if (event.shiftKey) {
          // Ctrl + Shift + Z = Redo
          if (this.canRedo()) {
            this.redo();
            event.preventDefault();
          }
        } else {
          // Ctrl + Z = Undo
          if (this.canUndo()) {
            this.undo();
            event.preventDefault();
          }
        }
      } else if (event.key.toLowerCase() === 'y') {
        // Ctrl + Y = Redo
        if (this.canRedo()) {
          this.redo();
          event.preventDefault();
        }
      }
    }
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.isPanelOpen()) return;
    const target = event.target as HTMLElement;
    if (!target) return;

    const isInsidePanel =
      target.closest('.crop-panel') || target.closest('.drawing-panel');
    const isInsideDock = target.closest('.vertical-toolbar');
    const isInsideMatOverlay = target.closest('.cdk-overlay-container');

    if (!isInsidePanel && !isInsideDock && !isInsideMatOverlay) {
      this.isPanelOpen.set(false);
    }
  }

  // Drawing control methods
  setMode(mode: ImageEditorMode): void {
    const currentMode = this.activeMode();
    if (currentMode === mode) {
      this.isPanelOpen.set(!this.isPanelOpen());
      return;
    }
    this.isPanelOpen.set(true);
    let canvaChangesPending = false;
    if (mode === ImageEditorMode.DRAW) {
      const blobToLoad = this.croppedImageBlob || this.imageFile;
      if (blobToLoad) {
        const img = new Image();
        const url = window.URL.createObjectURL(blobToLoad);
        img.onload = () => {
          if (!this.canvasDrawer && this.drawingCanvas?.nativeElement) {
            this.initCanvasDrawer();
          }
          if (this.canvasDrawer) {
            this.canvasDrawer.setBackgroundImage(img);
            this.syncCanvasDrawerSettings();
            this.updateHistorySignals();
          }
          window.URL.revokeObjectURL(url);
        };
        img.src = url;
      }
    } else if (currentMode === ImageEditorMode.DRAW) {
      canvaChangesPending = this.canvasToImage(croppedFile => {
        this.imageFile = croppedFile;
        this.activeMode.set(ImageEditorMode.CROP);
      });
    }
    if (!canvaChangesPending) this.activeMode.set(mode);
  }

  private canvasToImage(callback: (croppedFile: File) => void): boolean {
    let canvaChangesPending = false;
    this.commitText();
    if (this.canvasDrawer) {
      canvaChangesPending = true;
      this.canvasDrawer.canvas.toBlob(blob => {
        if (blob) {
          const croppedFile = new File(
            [blob],
            this.imageFile?.name || 'edited-image.png',
            {type: 'image/png'},
          );
          callback(croppedFile);
        }
      }, 'image/png');
    }
    return canvaChangesPending;
  }

  setDrawTool(tool: DrawingTool): void {
    this.activeDrawTool.set(tool);
    this.canvasDrawer!.mode = tool;
  }

  setBrushColor(color: string): void {
    this.brushColor.set(color);
    this.canvasDrawer!.strokeColor = color;
  }

  onBrushColorPickerChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input && input.value) {
      this.brushColor.set(input.value);
      this.canvasDrawer!.strokeColor = input.value;
    }
  }

  onBrushSizeChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input && input.value) {
      const size = Number(input.value);
      this.brushSize.set(size);
      this.canvasDrawer!.strokeWidth = size;
      this.canvasDrawer!.fontSize = size;
    }
  }

  undo(): void {
    this.canvasDrawer!.undo();
    this.updateHistorySignals();
  }

  redo(): void {
    this.canvasDrawer!.redo();
    this.updateHistorySignals();
  }

  clearDrawing(): void {
    this.canvasDrawer!.clear();
    this.updateHistorySignals();
  }

  imageCropped(event: ImageCroppedEvent) {
    if (event.blob) {
      this.croppedImageBlob = event.blob;
    }
  }

  uploadCroppedImage() {
    if (this.activeMode() === ImageEditorMode.DRAW) {
      this.canvasToImage(croppedFile => {
        this.isUploading = true;
        const selectedRatio = this.aspectRatios.find(
          r => r.value === this.currentAspectRatio,
        );
        const aspectRatioString = selectedRatio
          ? selectedRatio.stringValue
          : '1:1';

        this.uploadAsset(croppedFile, aspectRatioString)
          .pipe(finalize(() => (this.isUploading = false)))
          .subscribe(asset => {
            this.sourceAssetService.addAsset(asset);
            this.dialogRef.close(asset);
          });
      });
    } else if (this.croppedImageBlob) {
      const croppedFile = new File(
        [this.croppedImageBlob],
        this.imageFile?.name || 'untitled',
        {
          type: 'image/png',
        },
      );

      // 3. Find the string value of the current aspect ratio
      const selectedRatio = this.aspectRatios.find(
        r => r.value === this.currentAspectRatio,
      );
      const aspectRatioString = selectedRatio
        ? selectedRatio.stringValue
        : '1:1';

      this.isUploading = true;
      this.uploadAsset(croppedFile, aspectRatioString)
        .pipe(finalize(() => (this.isUploading = false)))
        .subscribe(asset => {
          this.sourceAssetService.addAsset(asset);
          this.dialogRef.close(asset); // Close and return the final asset
        });
    }
  }

  uploadOriginalImage() {
    if (this.imageFile) {
      this.isUploading = true;
      this.uploadAsset(this.imageFile, 'other')
        .pipe(finalize(() => (this.isUploading = false)))
        .subscribe(asset => {
          this.sourceAssetService.addAsset(asset);
          this.dialogRef.close(asset);
        });
    }
  }

  private uploadAsset(
    file: File,
    aspectRatio: string,
  ): Observable<SourceAssetResponseDto> {
    return this.sourceAssetService.uploadAsset(file, {
      aspectRatio: aspectRatio,
      scope: AssetScopeEnum.PRIVATE,
      assetType: this.data.assetType || AssetTypeEnum.GENERIC_IMAGE,
    });
  }
}
