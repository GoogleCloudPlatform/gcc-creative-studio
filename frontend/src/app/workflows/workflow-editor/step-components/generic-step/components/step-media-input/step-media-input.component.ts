import { Component, Input, OnInit } from '@angular/core';
import { AbstractControl } from '@angular/forms';
import { MatDialog } from '@angular/material/dialog';
import { AssetTypeEnum } from '../../../../../../admin/source-assets-management/source-asset.model';
import { ImageCropperDialogComponent } from '../../../../../../common/components/image-cropper-dialog/image-cropper-dialog.component';
import { ImageSelectorComponent, MediaItemSelection } from '../../../../../../common/components/image-selector/image-selector.component';
import { ReferenceImage } from '../../../../../../common/models/search.model';
import { SourceAssetResponseDto } from '../../../../../../common/services/source-asset.service';
import { StepOutputReference } from '../../../../../workflow.models';

@Component({
  selector: 'app-step-media-input',
  templateUrl: './step-media-input.component.html',
  styleUrls: ['./step-media-input.component.scss']
})
export class StepMediaInputComponent implements OnInit {
  @Input() control!: AbstractControl;
  @Input() inputName!: string;
  @Input() type: 'image' | 'video' = 'image';
  @Input() maxItems: number = 1;
  @Input() compatibleOutputs: any[] = [];
  @Input() showValidationErrors = false;

  // Helpers
  get items(): (ReferenceImage | StepOutputReference)[] {
    const val = this.control.value;
    if (Array.isArray(val)) return val;
    // If it's single item but we want to treat it as array for rendering
    // Actually, fixed mode can be single object or array?
    // In GenericStepComponent:
    // Mixed -> array
    // Fixed -> handled as single item usually, but for Image input it uses `referenceImages[input.name]` which is an array.
    // So standardized: Always work with array for internal display.
    // If control value is null, return empty array.
    // Wait, if it's FIXED mode and we only allow 1, the control value might be just the object? 
    // In GenericStepComponent, `referenceImages` was the source of truth for display, and `updateInputControlWithError` synced it to control.
    // We should probably maintain a local `referenceImages` array and sync to control.
    if (!val) return [];
    return Array.isArray(val) ? val : [val];
  }

  constructor(public dialog: MatDialog) { }

  ngOnInit(): void {
  }

  get isMixedMode(): boolean {
    return this.maxItems > 1; // Or check if control value is array?
  }

  isStepOutputReference(item: any): item is StepOutputReference {
    return item && 'step' in item && 'output' in item;
  }

  getLinkedOutputLabel(item: StepOutputReference): string {
    const found = this.compatibleOutputs.find(o => o.value.step === item.step && o.value.output === item.output);
    return found ? found.label : `${item.step}.${item.output}`;
  }

  openImageSelectorForReference(): void {
    if (this.items.length >= this.maxItems) return;

    let mimeType: string = 'image/*';
    if (this.type === 'video') mimeType = 'video/mp4';

    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: mimeType,
        assetType: this.type === 'video' ? AssetTypeEnum.GENERIC_VIDEO : AssetTypeEnum.GENERIC_IMAGE,
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef.afterClosed().subscribe((result: MediaItemSelection | SourceAssetResponseDto) => {
      if (result && this.items.length < this.maxItems) {
        let newImage: ReferenceImage | null = null;

        if ('gcsUri' in result) {
          newImage = {
            sourceAssetId: result.id,
            previewUrl: result.presignedUrl || '',
          };
        } else {
          const previewUrl = result.mediaItem.presignedUrls?.[result.selectedIndex];
          if (previewUrl) {
            newImage = {
              previewUrl: previewUrl,
              sourceMediaItem: {
                mediaItemId: result.mediaItem.id,
                mediaIndex: result.selectedIndex,
                role: 'image_reference_asset',
              },
            };
          }
        }

        if (newImage) {
          this.addItem(newImage);
        }
      }
    });
  }

  onReferenceImageDrop(event: DragEvent) {
    event.preventDefault();
    if (this.items.length >= this.maxItems) return;

    // Only support image drop for now as per original code `input.type === 'image' && ...`
    // If this component handles video too, we should check type.
    if (this.type !== 'image') return;

    const file = event.dataTransfer?.files[0];
    if (file && file.type.startsWith('image/')) {
      const dialogRef = this.dialog.open(ImageCropperDialogComponent, {
        data: {
          imageFile: file,
          assetType: AssetTypeEnum.GENERIC_IMAGE,
        },
        width: '600px',
      });

      dialogRef.afterClosed().subscribe((result: SourceAssetResponseDto) => {
        if (result && result.id) {
          this.addItem({
            sourceAssetId: result.id,
            previewUrl: result.presignedUrl || '',
          });
        }
      });
    }
  }

  addLinkedOutput(outputValue: any) {
    if (this.items.length >= this.maxItems) return;
    this.addItem(outputValue.value);
  }

  clearReferenceImage(index: number) {
    const currentItems = [...this.items];
    currentItems.splice(index, 1);
    this.updateValue(currentItems);
  }

  private addItem(item: ReferenceImage | StepOutputReference) {
    const currentItems = [...this.items, item];
    this.updateValue(currentItems);
  }

  private updateValue(items: (ReferenceImage | StepOutputReference)[]) {
    // If maxItems is 1, maybe we want to set logic to value directly?
    // Standardize GenericStepComponent to always use array for mixed?
    // In GenericStep:
    // Mixed -> array
    // Fixed image -> array in referenceImages map, but logic might differ.
    // Let's check GenericStepComponent `updateInputControlWithError`:
    // `control.setValue(images.length > 0 ? [...images] : null);`
    // So it ALWAYS sets an array if length > 0, or null?
    // The original code says `this.referenceImages[input.name]` which is an array.
    // So I will stick to array.
    if (items.length > 0) {
      this.control.setValue(items);
    } else {
      this.control.setValue(null);
    }
    this.control.markAsDirty();
    this.control.updateValueAndValidity();
  }
}
