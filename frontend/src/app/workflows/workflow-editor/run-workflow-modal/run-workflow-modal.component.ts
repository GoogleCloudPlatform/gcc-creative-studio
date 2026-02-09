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

import { Component, Inject, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { AssetTypeEnum } from '../../../admin/source-assets-management/source-asset.model';
import { ImageCropperDialogComponent } from '../../../common/components/image-cropper-dialog/image-cropper-dialog.component';
import { ImageSelectorComponent, MediaItemSelection } from '../../../common/components/image-selector/image-selector.component';
import { ReferenceImage } from '../../../common/models/search.model';
import { SourceAssetResponseDto } from '../../../common/services/source-asset.service';
import { WorkflowStep } from '../../workflow.models';

@Component({
    selector: 'app-run-workflow-modal',
    templateUrl: './run-workflow-modal.component.html',
    styleUrls: ['./run-workflow-modal.component.scss']
})
export class RunWorkflowModalComponent implements OnInit {
    runForm!: FormGroup;
    userInputStep: WorkflowStep;
    inputDefinitions: { name: string; type: string }[] = [];
    referenceImages: { [key: string]: ReferenceImage[] } = {};

    constructor(
        private fb: FormBuilder,
        private dialogRef: MatDialogRef<RunWorkflowModalComponent>,
        private dialog: MatDialog,
        @Inject(MAT_DIALOG_DATA) public data: { userInputStep: WorkflowStep }
    ) {
        this.userInputStep = data.userInputStep;
    }

    ngOnInit(): void {
        this.runForm = this.fb.group({});

        if (this.userInputStep && this.userInputStep.outputs) {
            Object.entries(this.userInputStep.outputs).forEach(([key, value]: [string, any]) => {
                this.inputDefinitions.push({ name: key, type: value.type });

                if (value.type === 'image') {
                    this.runForm.addControl(key, this.fb.control([], Validators.required));
                    this.referenceImages[key] = [];
                } else {
                    this.runForm.addControl(key, this.fb.control('', Validators.required));
                }
            });
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

    openImageSelectorForReference(inputName: string): void {
        if ((this.referenceImages[inputName]?.length || 0) >= 3) return;
        const dialogRef = this.dialog.open(ImageSelectorComponent, {
            width: '90vw',
            height: '80vh',
            maxWidth: '90vw',
            data: {
                mimeType: 'image/*', // Only allow images for references
            },
            panelClass: 'image-selector-dialog',
        });

        dialogRef
            .afterClosed()
            .subscribe((result: MediaItemSelection | SourceAssetResponseDto) => {
                if (result && (this.referenceImages[inputName]?.length || 0) < 3) {
                    if (!this.referenceImages[inputName]) this.referenceImages[inputName] = [];

                    let newImage: ReferenceImage | null = null;

                    if ('gcsUri' in result) {
                        newImage = {
                            sourceAssetId: result.id,
                            previewUrl: result.presignedUrl || '',
                        };
                    } else {
                        const previewUrl =
                            result.mediaItem.presignedUrls?.[result.selectedIndex];
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
                        this.referenceImages[inputName].push(newImage);
                        this.updateInputControlWithError(inputName);
                    }
                }
            });
    }

    // Called when DROPPING a file on the new drop zone
    onReferenceImageDrop(event: DragEvent, inputName: string) {
        event.preventDefault();
        if ((this.referenceImages[inputName]?.length || 0) >= 3) return;
        const file = event.dataTransfer?.files[0];
        if (file && file.type.startsWith('image/')) {
            // For a direct drop, go straight to the cropper
            const dialogRef = this.dialog.open(ImageCropperDialogComponent, {
                data: {
                    imageFile: file,
                    assetType: AssetTypeEnum.GENERIC_IMAGE,
                },
                width: '600px',
            });

            dialogRef.afterClosed().subscribe((result: SourceAssetResponseDto) => {
                if (result && result.id) {
                    if (!this.referenceImages[inputName]) this.referenceImages[inputName] = [];
                    this.referenceImages[inputName].push({
                        sourceAssetId: result.id,
                        previewUrl: result.presignedUrl || '',
                    });
                    this.updateInputControlWithError(inputName);
                }
            });
        }
    }


    clearReferenceImage(inputName: string, index: number) {
        if (this.referenceImages[inputName]) {
            this.referenceImages[inputName].splice(index, 1);
            this.updateInputControlWithError(inputName);
        }
    }

    private updateInputControlWithError(inputName: string) {
        const images = this.referenceImages[inputName] || [];
        this.runForm.get(inputName)?.setValue(images);
    }
}
