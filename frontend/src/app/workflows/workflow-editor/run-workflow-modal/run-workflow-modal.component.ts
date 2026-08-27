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

import {Component, Inject, OnInit} from '@angular/core';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {AssetTypeEnum} from '../../../admin/source-assets-management/source-asset.model';
import {
  ImageSelectorComponent,
  MediaItemSelection,
} from '../../../common/components/image-selector/image-selector.component';
import {ReferenceImage} from '../../../common/models/search.model';
import {
  SourceAssetResponseDto,
  SourceAssetService,
} from '../../../common/services/source-asset.service';
import {
  getPreviewUrl,
  isVideoUrl,
  labelToName,
  nameToLabel,
} from '../../utils/workflow-step.util';
import {WorkflowStep} from '../../workflow.models';

@Component({
  selector: 'app-run-workflow-modal',
  templateUrl: './run-workflow-modal.component.html',
  styleUrls: ['./run-workflow-modal.component.scss'],
})
export class RunWorkflowModalComponent implements OnInit {
  runForm!: FormGroup;
  userInputStep: WorkflowStep;
  inputDefinitions: {name: string; label: string; type: string}[] = [];
  referenceImages: {[key: string]: ReferenceImage | null} = {};
  readonly isVideoUrl = isVideoUrl;

  constructor(
    private fb: FormBuilder,
    private dialogRef: MatDialogRef<RunWorkflowModalComponent>,
    private dialog: MatDialog,
    private sourceAssetService: SourceAssetService,
    @Inject(MAT_DIALOG_DATA) public data: {userInputStep: WorkflowStep},
  ) {
    this.userInputStep = data.userInputStep;
  }

  ngOnInit(): void {
    this.runForm = this.fb.group({});

    if (this.userInputStep && this.userInputStep.outputs) {
      const definitions = this.userInputStep.settings['definitions'] || [];
      const defMap = new Map<string, string>();
      definitions.forEach((def: any) => {
        if (def && def.name) {
          defMap.set(labelToName(def.name), def.name);
          defMap.set(def.name, def.name);
        }
      });

      Object.entries(this.userInputStep.outputs).forEach(
        ([key, value]: [string, any]) => {
          const rawLabel = defMap.get(key) || key;
          this.inputDefinitions.push({
            name: key,
            label: nameToLabel(rawLabel),
            type: value.type,
          });

          if (value.type === 'image' || value.type === 'video') {
            this.runForm.addControl(
              key,
              this.fb.control(null, Validators.required),
            );
            this.referenceImages[key] = null;
          } else {
            this.runForm.addControl(
              key,
              this.fb.control('', Validators.required),
            );
          }
        },
      );
    }
  }

  onCancel(): void {
    this.dialogRef.close();
  }

  onRun(): void {
    if (this.runForm.valid) {
      this.dialogRef.close(this.runForm.value);
    }
  }

  openMediaSelectorForReference(inputName: string, inputType = 'image'): void {
    if (this.referenceImages[inputName]) return;

    let mimeType = 'image/*';
    let assetType = AssetTypeEnum.GENERIC_IMAGE;
    let role = 'image_reference_asset';

    if (inputType === 'video') {
      mimeType = 'video/*';
      assetType = AssetTypeEnum.GENERIC_VIDEO;
      role = 'reference_video';
    }

    const dialogRef = this.dialog.open(ImageSelectorComponent, {
      width: '90vw',
      height: '80vh',
      maxWidth: '90vw',
      data: {
        mimeType: mimeType,
        assetType: assetType,
        showFooter: true,
        maxSelection: 1,
      },
      panelClass: 'image-selector-dialog',
    });

    dialogRef
      .afterClosed()
      .subscribe((result: MediaItemSelection | SourceAssetResponseDto) => {
        if (result && !this.referenceImages[inputName]) {
          let newImage: ReferenceImage | null = null;

          if ('id' in result) {
            newImage = {
              sourceAssetId: result.id,
              previewUrl: getPreviewUrl(result),
            };
          } else {
            const previewUrl = getPreviewUrl(result);
            if (previewUrl) {
              newImage = {
                previewUrl: previewUrl,
                sourceMediaItem: {
                  mediaItemId: result.mediaItem.id,
                  mediaIndex: result.selectedIndex,
                  role: role,
                },
              };
            }
          }

          if (newImage) {
            this.referenceImages[inputName] = newImage;
            this.updateInputControlWithError(inputName);
          }
        }
      });
  }

  openImageSelectorForReference(inputName: string): void {
    const def = this.inputDefinitions.find(d => d.name === inputName);
    this.openMediaSelectorForReference(inputName, def?.type || 'image');
  }

  // Called when DROPPING a file on the new drop zone
  onReferenceMediaDrop(
    event: DragEvent,
    inputName: string,
    inputType = 'image',
  ) {
    event.preventDefault();
    if (this.referenceImages[inputName]) return;
    const file = event.dataTransfer?.files[0];
    if (!file) return;

    const isImage = inputType === 'image' && file.type.startsWith('image/');
    const isVideo = inputType === 'video' && file.type.startsWith('video/');

    if (!isImage && !isVideo) return;

    const uploadOptions = isImage
      ? {assetType: AssetTypeEnum.GENERIC_IMAGE}
      : {assetType: AssetTypeEnum.GENERIC_VIDEO};

    this.sourceAssetService
      .uploadAsset(file, uploadOptions)
      .subscribe((result: SourceAssetResponseDto) => {
        if (result && result.id) {
          this.referenceImages[inputName] = {
            sourceAssetId: result.id,
            previewUrl: getPreviewUrl(result),
          };
          this.updateInputControlWithError(inputName);
        }
      });
  }

  onReferenceImageDrop(event: DragEvent, inputName: string) {
    const def = this.inputDefinitions.find(d => d.name === inputName);
    this.onReferenceMediaDrop(event, inputName, def?.type || 'image');
  }

  clearReferenceImage(inputName: string) {
    this.referenceImages[inputName] = null;
    this.updateInputControlWithError(inputName);
  }

  private updateInputControlWithError(inputName: string) {
    const image = this.referenceImages[inputName] || null;
    this.runForm.get(inputName)?.setValue(image);
  }
}
