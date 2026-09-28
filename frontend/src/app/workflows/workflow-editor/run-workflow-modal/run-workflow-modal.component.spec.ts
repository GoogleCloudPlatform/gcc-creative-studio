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
import {ReactiveFormsModule} from '@angular/forms';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogRef,
} from '@angular/material/dialog';
import {of} from 'rxjs';
import {SourceAssetService} from '../../../common/services/source-asset.service';
import {RunWorkflowModalComponent} from './run-workflow-modal.component';

describe('RunWorkflowModalComponent', () => {
  let component: RunWorkflowModalComponent;
  let fixture: ComponentFixture<RunWorkflowModalComponent>;
  let mockSourceAssetService: jasmine.SpyObj<SourceAssetService>;
  let mockDialog: jasmine.SpyObj<MatDialog>;
  let mockDialogRef: jasmine.SpyObj<MatDialogRef<RunWorkflowModalComponent>>;

  const mockUserInputStep: any = {
    stepId: 'user_input',
    type: 'user_input',
    outputs: {
      user_prompt: {type: 'text'},
      input_image: {type: 'image'},
      input_video: {type: 'video'},
    },
    settings: {
      definitions: [
        {id: 'def-1', name: 'User Prompt', type: 'text'},
        {id: 'def-2', name: 'Input Image', type: 'image'},
        {id: 'def-3', name: 'Input Video', type: 'video'},
      ],
    },
  };

  beforeEach(async () => {
    mockSourceAssetService = jasmine.createSpyObj('SourceAssetService', [
      'uploadAsset',
    ]);
    mockDialog = jasmine.createSpyObj('MatDialog', ['open']);
    mockDialogRef = jasmine.createSpyObj('MatDialogRef', ['close']);

    await TestBed.configureTestingModule({
      declarations: [RunWorkflowModalComponent],
      imports: [ReactiveFormsModule],
      providers: [
        {provide: SourceAssetService, useValue: mockSourceAssetService},
        {provide: MatDialog, useValue: mockDialog},
        {provide: MatDialogRef, useValue: mockDialogRef},
        {
          provide: MAT_DIALOG_DATA,
          useValue: {userInputStep: mockUserInputStep},
        },
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(RunWorkflowModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create and initialize form controls', () => {
    expect(component).toBeTruthy();
    expect(component.runForm.contains('user_prompt')).toBeTrue();
    expect(component.runForm.contains('input_image')).toBeTrue();
    expect(component.runForm.contains('input_video')).toBeTrue();
  });

  it('should close dialog with form values on onRun when valid', () => {
    component.runForm.get('user_prompt')?.setValue('Test prompt');
    component.runForm.get('input_image')?.setValue({
      previewUrl: 'https://example.com/test.png',
      sourceAssetId: 1,
    });
    component.runForm.get('input_video')?.setValue({
      previewUrl: 'https://example.com/test.mp4',
      sourceAssetId: 2,
    });

    component.onRun();
    expect(mockDialogRef.close).toHaveBeenCalledWith(component.runForm.value);
  });

  it('should close dialog on onCancel', () => {
    component.onCancel();
    expect(mockDialogRef.close).toHaveBeenCalled();
  });

  it('should set referenceImage previewUrl from SourceAsset with thumbnail', () => {
    const mockAsset = {
      id: 101,
      gcsUri: 'gs://bucket/image.png',
      presignedUrl: 'https://example.com/orig.png',
      presignedThumbnailUrl: 'https://example.com/thumb.png',
    };
    mockDialog.open.and.returnValue({
      afterClosed: () => of(mockAsset),
    } as any);

    component.openImageSelectorForReference('input_image');

    expect(component.referenceImages['input_image']).toEqual({
      sourceAssetId: 101,
      previewUrl: 'https://example.com/thumb.png',
    });
    expect(component.runForm.get('input_image')?.value).toEqual({
      sourceAssetId: 101,
      previewUrl: 'https://example.com/thumb.png',
    });
  });

  it('should set referenceMedia previewUrl from MediaItem selection for video', () => {
    const mockMediaSelection = {
      mediaItem: {
        id: 202,
        presignedUrls: ['https://example.com/media.mp4'],
        presignedThumbnailUrls: ['https://example.com/media_thumb.png'],
      },
      selectedIndex: 0,
    };
    mockDialog.open.and.returnValue({
      afterClosed: () => of(mockMediaSelection),
    } as any);

    component.openImageSelectorForReference('input_video');

    expect(component.referenceImages['input_video']).toEqual({
      previewUrl: 'https://example.com/media_thumb.png',
      sourceMediaItem: {
        mediaItemId: 202,
        mediaIndex: 0,
        role: 'reference_video',
      },
    });
  });

  it('should set referenceImage previewUrl from MediaItem selection', () => {
    const mockMediaSelection = {
      mediaItem: {
        id: 202,
        presignedUrls: ['https://example.com/media.png'],
        presignedThumbnailUrls: ['https://example.com/media_thumb.png'],
      },
      selectedIndex: 0,
    };
    mockDialog.open.and.returnValue({
      afterClosed: () => of(mockMediaSelection),
    } as any);

    component.openImageSelectorForReference('input_image');

    expect(component.referenceImages['input_image']).toEqual({
      previewUrl: 'https://example.com/media_thumb.png',
      sourceMediaItem: {
        mediaItemId: 202,
        mediaIndex: 0,
        role: 'image_reference_asset',
      },
    });
  });

  it('should upload asset and set previewUrl on drag and drop', () => {
    const mockFile = new File(['image'], 'drop.png', {type: 'image/png'});
    const mockDropEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      dataTransfer: {files: [mockFile]},
    } as unknown as DragEvent;

    mockSourceAssetService.uploadAsset.and.returnValue(
      of({
        id: 303,
        presignedUrl: 'https://example.com/drop.png',
        presignedThumbnailUrl: 'https://example.com/drop_thumb.png',
      } as any),
    );

    component.onReferenceImageDrop(mockDropEvent, 'input_image');

    expect(component.referenceImages['input_image']).toEqual({
      sourceAssetId: 303,
      previewUrl: 'https://example.com/drop_thumb.png',
    });
  });

  it('should upload video asset and set previewUrl on video drag and drop', () => {
    const mockFile = new File(['video'], 'drop.mp4', {type: 'video/mp4'});
    const mockDropEvent = {
      preventDefault: jasmine.createSpy('preventDefault'),
      dataTransfer: {files: [mockFile]},
    } as unknown as DragEvent;

    mockSourceAssetService.uploadAsset.and.returnValue(
      of({
        id: 404,
        presignedUrl: 'https://example.com/drop.mp4',
        presignedThumbnailUrl: 'https://example.com/drop_video_thumb.png',
      } as any),
    );

    component.onReferenceImageDrop(mockDropEvent, 'input_video');

    expect(component.referenceImages['input_video']).toEqual({
      sourceAssetId: 404,
      previewUrl: 'https://example.com/drop_video_thumb.png',
    });
  });

  it('should clear reference image', () => {
    component.referenceImages['input_image'] = {
      previewUrl: 'https://example.com/img.png',
    };
    component.runForm.get('input_image')?.setValue({
      previewUrl: 'https://example.com/img.png',
    });

    component.clearReferenceImage('input_image');

    expect(component.referenceImages['input_image']).toBeNull();
    expect(component.runForm.get('input_image')?.value).toBeNull();
  });
});
