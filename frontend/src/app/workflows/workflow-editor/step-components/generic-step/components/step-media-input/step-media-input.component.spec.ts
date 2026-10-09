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
import {FormControl, ReactiveFormsModule} from '@angular/forms';
import {MatDialog} from '@angular/material/dialog';
import {MatMenuModule} from '@angular/material/menu';
import {of} from 'rxjs';
import {SourceAssetService} from '../../../../../../common/services/source-asset.service';
import {StepMediaInputComponent} from './step-media-input.component';

describe('StepMediaInputComponent', () => {
  let component: StepMediaInputComponent;
  let fixture: ComponentFixture<StepMediaInputComponent>;
  let mockSourceAssetService: jasmine.SpyObj<SourceAssetService>;
  let mockDialog: jasmine.SpyObj<MatDialog>;

  const mockCompatibleOutputs = [
    {
      label: 'Step 1: Generated Image',
      value: {step: 'step_1', output: 'generated_image'},
      type: 'image',
    },
    {
      label: 'Step 2: Upscaled Image',
      value: {step: 'step_2', output: 'upscaled_image'},
      type: 'image',
    },
    {
      label: 'User Input: Initial Image',
      value: {step: 'user_input', output: 'initial_img'},
      type: 'image',
    },
  ];

  beforeEach(async () => {
    mockSourceAssetService = jasmine.createSpyObj('SourceAssetService', [
      'uploadAsset',
    ]);
    mockDialog = jasmine.createSpyObj('MatDialog', ['open']);
    mockDialog.open.and.returnValue({
      afterClosed: () => of(null),
    } as any);

    await TestBed.configureTestingModule({
      declarations: [StepMediaInputComponent],
      imports: [ReactiveFormsModule, MatMenuModule],
      providers: [
        {provide: SourceAssetService, useValue: mockSourceAssetService},
        {provide: MatDialog, useValue: mockDialog},
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(StepMediaInputComponent);
    component = fixture.componentInstance;
    component.control = new FormControl(null);
    component.inputName = 'input_images';
    component.type = 'image';
    component.maxItems = 3;
    component.compatibleOutputs = [...mockCompatibleOutputs];
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('unlinkedCompatibleOutputs', () => {
    it('should return all compatible outputs when control value is empty', () => {
      component.control.setValue(null);
      expect(component.unlinkedCompatibleOutputs.length).toBe(3);
    });

    it('should filter out output reference when linked as single object', () => {
      component.control.setValue({
        step: 'step_1',
        output: 'generated_image',
      });

      const unlinked = component.unlinkedCompatibleOutputs;
      expect(unlinked.length).toBe(2);
      expect(
        unlinked.some(
          o =>
            o.value.step === 'step_1' && o.value.output === 'generated_image',
        ),
      ).toBeFalse();
      expect(
        unlinked.some(
          o => o.value.step === 'step_2' && o.value.output === 'upscaled_image',
        ),
      ).toBeTrue();
    });

    it('should filter out already linked outputs when control value is an array', () => {
      component.control.setValue([
        {step: 'step_1', output: 'generated_image'},
        {step: 'user_input', output: 'initial_img'},
      ]);

      const unlinked = component.unlinkedCompatibleOutputs;
      expect(unlinked.length).toBe(1);
      expect(unlinked[0].value).toEqual({
        step: 'step_2',
        output: 'upscaled_image',
      });
    });

    it('should not filter out outputs when array contains only fixed images', () => {
      component.control.setValue([
        {previewUrl: 'https://example.com/1.png', sourceAssetId: 'asset-1'},
      ]);

      const unlinked = component.unlinkedCompatibleOutputs;
      expect(unlinked.length).toBe(3);
    });

    it('should return empty array if all compatible outputs are already linked', () => {
      component.control.setValue([
        {step: 'step_1', output: 'generated_image'},
        {step: 'step_2', output: 'upscaled_image'},
        {step: 'user_input', output: 'initial_img'},
      ]);

      expect(component.unlinkedCompatibleOutputs).toEqual([]);
    });

    it('should return empty array if compatibleOutputs is empty or undefined', () => {
      component.compatibleOutputs = [];
      expect(component.unlinkedCompatibleOutputs).toEqual([]);
    });
  });

  describe('addLinkedOutput', () => {
    it('should add output reference to control when not yet linked', () => {
      component.control.setValue(null);
      component.addLinkedOutput(mockCompatibleOutputs[0]);

      expect(component.control.value).toEqual([
        {step: 'step_1', output: 'generated_image'},
      ]);
    });

    it('should not add output reference if already linked in array', () => {
      component.control.setValue([{step: 'step_1', output: 'generated_image'}]);

      component.addLinkedOutput(mockCompatibleOutputs[0]);

      expect(component.control.value.length).toBe(1);
      expect(component.control.value).toEqual([
        {step: 'step_1', output: 'generated_image'},
      ]);
    });

    it('should not add output reference if items length reaches maxItems', () => {
      component.maxItems = 2;
      component.control.setValue([
        {step: 'step_1', output: 'generated_image'},
        {step: 'step_2', output: 'upscaled_image'},
      ]);

      component.addLinkedOutput(mockCompatibleOutputs[2]);

      expect(component.control.value.length).toBe(2);
    });

    it('should accept direct StepOutputReference object without wrapper', () => {
      component.control.setValue(null);
      component.addLinkedOutput({
        step: 'step_1',
        output: 'generated_image',
      });

      expect(component.control.value).toEqual([
        {step: 'step_1', output: 'generated_image'},
      ]);
    });
  });

  describe('clearReferenceImage', () => {
    it('should remove item by index and restore output in unlinkedCompatibleOutputs', () => {
      component.control.setValue([
        {step: 'step_1', output: 'generated_image'},
        {step: 'step_2', output: 'upscaled_image'},
      ]);

      expect(component.unlinkedCompatibleOutputs.length).toBe(1);

      component.clearReferenceImage(0);

      expect(component.control.value).toEqual([
        {step: 'step_2', output: 'upscaled_image'},
      ]);
      expect(component.unlinkedCompatibleOutputs.length).toBe(2);
      expect(
        component.unlinkedCompatibleOutputs.some(
          o =>
            o.value.step === 'step_1' && o.value.output === 'generated_image',
        ),
      ).toBeTrue();
    });

    it('should set control to null when last item is removed', () => {
      component.control.setValue([{step: 'step_1', output: 'generated_image'}]);

      component.clearReferenceImage(0);

      expect(component.control.value).toBeNull();
    });
  });

  describe('getLinkedOutputLabel', () => {
    it('should return the friendly label from compatibleOutputs', () => {
      const label = component.getLinkedOutputLabel({
        step: 'step_1',
        output: 'generated_image',
      });
      expect(label).toBe('Step 1: Generated Image');
    });

    it('should return fallback string if output not in compatibleOutputs', () => {
      const label = component.getLinkedOutputLabel({
        step: 'unknown_step',
        output: 'unknown_out',
      });
      expect(label).toBe('unknown_step.unknown_out');
    });
  });

  describe('isStepOutputReference', () => {
    it('should return true for StepOutputReference objects', () => {
      expect(
        component.isStepOutputReference({
          step: 'step_1',
          output: 'generated_image',
        }),
      ).toBeTrue();
    });

    it('should return false for null, undefined, primitives, or ReferenceImage', () => {
      expect(component.isStepOutputReference(null)).toBeFalse();
      expect(component.isStepOutputReference(undefined)).toBeFalse();
      expect(component.isStepOutputReference('string_val')).toBeFalse();
      expect(
        component.isStepOutputReference({
          previewUrl: 'https://example.com/1.png',
        }),
      ).toBeFalse();
    });
  });

  describe('openImageSelectorForReference with video and audio types', () => {
    it('should configure dialog for video type', () => {
      component.type = 'video';
      component.control.setValue(null);
      component.openImageSelectorForReference();

      expect(mockDialog.open).toHaveBeenCalledWith(
        jasmine.any(Function),
        jasmine.objectContaining({
          data: jasmine.objectContaining({
            mimeType: 'video/*',
            assetType: 'generic_video',
          }),
        }),
      );
    });

    it('should configure dialog for audio type', () => {
      component.type = 'audio';
      component.control.setValue(null);
      component.openImageSelectorForReference();

      expect(mockDialog.open).toHaveBeenCalledWith(
        jasmine.any(Function),
        jasmine.objectContaining({
          data: jasmine.objectContaining({
            mimeType: 'audio/*',
          }),
        }),
      );
    });

    it('should properly set previewUrl from presignedThumbnailUrl for SourceAsset video', () => {
      component.type = 'video';
      component.control.setValue(null);
      const mockAsset = {
        id: 123,
        gcsUri: 'gs://bucket/video.mp4',
        presignedUrl: 'https://example.com/video.mp4',
        presignedThumbnailUrl: 'https://example.com/thumbnail.png',
      };
      mockDialog.open.and.returnValue({
        afterClosed: () => of(mockAsset),
      } as any);

      component.openImageSelectorForReference();

      expect(component.control.value).toEqual([
        {
          sourceAssetId: 123,
          previewUrl: 'https://example.com/thumbnail.png',
        },
      ]);
    });

    it('should fallback to presignedUrl if presignedThumbnailUrl is missing for SourceAsset', () => {
      component.type = 'video';
      component.control.setValue(null);
      const mockAsset = {
        id: 123,
        gcsUri: 'gs://bucket/video.mp4',
        presignedUrl: 'https://example.com/video.mp4',
      };
      mockDialog.open.and.returnValue({
        afterClosed: () => of(mockAsset),
      } as any);

      component.openImageSelectorForReference();

      expect(component.control.value).toEqual([
        {
          sourceAssetId: 123,
          previewUrl: 'https://example.com/video.mp4',
        },
      ]);
    });

    it('should properly set previewUrl from presignedThumbnailUrls and role reference_video for MediaItem', () => {
      component.type = 'video';
      component.control.setValue(null);
      const mockMediaSelection = {
        mediaItem: {
          id: 456,
          presignedUrls: ['https://example.com/generated_video.mp4'],
          presignedThumbnailUrls: ['https://example.com/generated_thumb.png'],
        },
        selectedIndex: 0,
      };
      mockDialog.open.and.returnValue({
        afterClosed: () => of(mockMediaSelection),
      } as any);

      component.openImageSelectorForReference();

      expect(component.control.value).toEqual([
        {
          previewUrl: 'https://example.com/generated_thumb.png',
          sourceMediaItem: {
            mediaItemId: 456,
            mediaIndex: 0,
            role: 'reference_video',
          },
        },
      ]);
    });
  });

  describe('onReferenceImageDrop', () => {
    it('should upload image asset and set previewUrl when image is dropped', () => {
      component.type = 'image';
      component.control.setValue(null);
      const mockFile = new File(['image content'], 'test.png', {
        type: 'image/png',
      });
      const mockDropEvent = {
        preventDefault: jasmine.createSpy('preventDefault'),
        dataTransfer: {files: [mockFile]},
      } as unknown as DragEvent;

      mockSourceAssetService.uploadAsset.and.returnValue(
        of({
          id: 789,
          presignedUrl: 'https://example.com/img.png',
          presignedThumbnailUrl: 'https://example.com/img_thumb.png',
        } as any),
      );

      component.onReferenceImageDrop(mockDropEvent);

      expect(mockSourceAssetService.uploadAsset).toHaveBeenCalledWith(
        mockFile,
        jasmine.objectContaining({
          assetType: 'generic_image',
        }),
      );
      expect(component.control.value).toEqual([
        {
          sourceAssetId: 789,
          previewUrl: 'https://example.com/img_thumb.png',
        },
      ]);
    });

    it('should upload video asset and set previewUrl when video is dropped', () => {
      component.type = 'video';
      component.control.setValue(null);
      const mockFile = new File(['video content'], 'test.mp4', {
        type: 'video/mp4',
      });
      const mockDropEvent = {
        preventDefault: jasmine.createSpy('preventDefault'),
        dataTransfer: {files: [mockFile]},
      } as unknown as DragEvent;

      mockSourceAssetService.uploadAsset.and.returnValue(
        of({
          id: 999,
          presignedUrl: 'https://example.com/video.mp4',
          presignedThumbnailUrl: 'https://example.com/video_thumb.png',
        } as any),
      );

      component.onReferenceImageDrop(mockDropEvent);

      expect(mockSourceAssetService.uploadAsset).toHaveBeenCalledWith(
        mockFile,
        jasmine.objectContaining({
          assetType: 'generic_video',
        }),
      );
      expect(component.control.value).toEqual([
        {
          sourceAssetId: 999,
          previewUrl: 'https://example.com/video_thumb.png',
        },
      ]);
    });
  });

  describe('Loop linked_items configuration', () => {
    const galleryTile = (): HTMLElement | null =>
      fixture.nativeElement.querySelector(
        '[data-testid="step-media-add-gallery"]',
      );
    const videoPick = {
      previewUrl: 'https://example.com/clip_thumb.png',
      sourceMediaItem: {
        mediaItemId: 456,
        mediaIndex: 0,
        role: 'reference_video',
      },
    };
    const buildRefs = (count: number) =>
      Array.from({length: count}, (_, index) => ({
        step: `vid_${index}`,
        output: 'generated_video',
      }));

    beforeEach(() => {
      component.inputName = 'linked_items';
      component.type = 'video';
      component.maxItems = 100;
      component.linkedOnly = false;
    });

    it('shows the add-from-gallery tile next to the link tile', () => {
      fixture.detectChanges();
      expect(galleryTile()).not.toBeNull();
    });

    it('opens the gallery filtered to the current item type', () => {
      component.openImageSelectorForReference();

      expect(mockDialog.open).toHaveBeenCalledWith(
        jasmine.any(Function),
        jasmine.objectContaining({
          data: jasmine.objectContaining({
            mimeType: 'video/*',
            multiSelect: true,
            maxSelection: 100,
          }),
        }),
      );
    });

    it('keeps wires and gallery picks in one array, in insertion order', () => {
      const firstRef = {step: 'vid_a', output: 'generated_video'};
      const secondRef = {step: 'vid_b', output: 'generated_video'};
      component.control.setValue([firstRef]);
      mockDialog.open.and.returnValue({
        afterClosed: () =>
          of({
            mediaItem: {
              id: 456,
              presignedUrls: ['https://example.com/clip.mp4'],
              presignedThumbnailUrls: ['https://example.com/clip_thumb.png'],
            },
            selectedIndex: 0,
          }),
      } as unknown as ReturnType<MatDialog['open']>);

      component.openImageSelectorForReference();
      component.addLinkedOutput(secondRef);

      expect(component.control.value).toEqual([firstRef, videoPick, secondRef]);
    });

    it('hides the add tiles and blocks picks once 100 items are set', () => {
      component.control.setValue([...buildRefs(99), videoPick]);
      fixture.detectChanges();

      expect(galleryTile()).toBeNull();
      component.openImageSelectorForReference();
      expect(mockDialog.open).not.toHaveBeenCalled();
    });

    it('limits a multi-pick to the remaining slots', () => {
      component.control.setValue(buildRefs(98));

      component.openImageSelectorForReference();

      expect(mockDialog.open).toHaveBeenCalledWith(
        jasmine.any(Function),
        jasmine.objectContaining({
          data: jasmine.objectContaining({maxSelection: 2}),
        }),
      );
    });

    it('shows the Loop empty-state message', () => {
      component.control.setErrors({linkedItemsRequired: true});
      expect(component.emptyErrorMessage).toBe(
        'Add at least one item to the Loop.',
      );
    });
  });

  describe('linkedOnly inputs', () => {
    beforeEach(() => {
      component.linkedOnly = true;
      fixture.detectChanges();
    });

    it('hides the gallery tile and ignores picks and drops', () => {
      expect(
        fixture.nativeElement.querySelector(
          '[data-testid="step-media-add-gallery"]',
        ),
      ).toBeNull();

      component.openImageSelectorForReference();
      component.onReferenceImageDrop({
        preventDefault: jasmine.createSpy('preventDefault'),
        dataTransfer: {files: [new File(['x'], 'a.png', {type: 'image/png'})]},
      } as unknown as DragEvent);

      expect(mockDialog.open).not.toHaveBeenCalled();
      expect(mockSourceAssetService.uploadAsset).not.toHaveBeenCalled();
    });

    it('keeps the default empty-state message for other errors', () => {
      expect(component.emptyErrorMessage).toBe(
        'At least one input is required',
      );
    });
  });
});
