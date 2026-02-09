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

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { MatDialog, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { of } from 'rxjs';
import { MaterialModule } from '../../../common/material.module';
import { RunWorkflowModalComponent } from './run-workflow-modal.component';
//import { MaterialModule } from '../../../common/material.module';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ImageSelectorComponent } from '../../../common/components/image-selector/image-selector.component';
import { ImageCropperDialogComponent } from '../../../common/components/image-cropper-dialog/image-cropper-dialog.component';

describe('RunWorkflowModalComponent', () => {
  let component: RunWorkflowModalComponent;
  let fixture: ComponentFixture<RunWorkflowModalComponent>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<RunWorkflowModalComponent>>;
  let dialogSpy: jasmine.SpyObj<MatDialog>;

  const mockUserInputStep = {
    id: '1',
    name: 'User Input',
    type: 'user_input',
    outputs: {
      image: { type: 'image' },
      text: { type: 'text' },
    },
  };

  beforeEach(async () => {
    dialogRefSpy = jasmine.createSpyObj('MatDialogRef', ['close']);
    dialogSpy = jasmine.createSpyObj('MatDialog', ['open']);

    await TestBed.configureTestingModule({
      declarations: [RunWorkflowModalComponent],
      imports: [ReactiveFormsModule, MaterialModule, NoopAnimationsModule],
      providers: [
        { provide: MatDialogRef, useValue: dialogRefSpy },
        { provide: MatDialog, useValue: dialogSpy },
        { provide: MAT_DIALOG_DATA, useValue: { userInputStep: mockUserInputStep } },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(RunWorkflowModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create the component and initialize the form', () => {
    expect(component).toBeTruthy();
    expect(component.runForm.get('image')).toBeDefined();
    expect(component.runForm.get('text')).toBeDefined();
    expect(component.inputDefinitions.length).toBe(2);
  });

  it('should close the dialog onCancel', () => {
    component.onCancel();
    expect(dialogRefSpy.close).toHaveBeenCalled();
  });

  it('should close the dialog with form value onRun if form is valid', () => {
    component.runForm.get('text')?.setValue('test');
    component.runForm.get('image')?.setValue([{ sourceAssetId: 123 }]);
    component.onRun();
    expect(dialogRefSpy.close).toHaveBeenCalledWith({
      text: 'test',
      image: [{ sourceAssetId: 123 }],
    });
  });

  it('should not close the dialog onRun if form is invalid', () => {
    component.onRun();
    expect(dialogRefSpy.close).not.toHaveBeenCalled();
  });

  describe('openImageSelectorForReference', () => {
    it('should open the ImageSelectorComponent', () => {
      dialogSpy.open.and.returnValue({ afterClosed: () => of(null) } as MatDialogRef<ImageSelectorComponent>);
      component.openImageSelectorForReference('image');
      expect(dialogSpy.open).toHaveBeenCalledWith(ImageSelectorComponent, jasmine.any(Object));
    });

    it('should not open the dialog if there are already 3 images', () => {
      component.referenceImages['image'] = [{}, {}, {}] as any;
      component.openImageSelectorForReference('image');
      expect(dialogSpy.open).not.toHaveBeenCalled();
    });

    it('should add a GCS image to referenceImages on dialog close', () => {
      const mockImage = { id: 123, presignedUrl: 'url', gcsUri: 'gs://bucket/image.png' };
      dialogSpy.open.and.returnValue({ afterClosed: () => of(mockImage) } as MatDialogRef<ImageSelectorComponent>);
      component.openImageSelectorForReference('image');
      expect(component.referenceImages['image'].length).toBe(1);
      expect(component.referenceImages['image'][0].sourceAssetId).toBe(123);
    });

    it('should add a media item to referenceImages on dialog close', () => {
      const mockMediaItem = {
        mediaItem: { id: 456, presignedUrls: ['url1'] },
        selectedIndex: 0,
      };
      dialogSpy.open.and.returnValue({ afterClosed: () => of(mockMediaItem) } as MatDialogRef<ImageSelectorComponent>);
      component.openImageSelectorForReference('image');
      expect(component.referenceImages['image'].length).toBe(1);
      expect(component.referenceImages['image'][0].sourceMediaItem?.mediaItemId).toBe(456);
    });
  });

  describe('onReferenceImageDrop', () => {
    let dataTransfer: DataTransfer;
    beforeEach(() => {
      dataTransfer = new DataTransfer();
    });

    it('should open the ImageCropperDialogComponent for a valid image file', () => {
      const file = new File([''], 'test.png', { type: 'image/png' });
      dataTransfer.items.add(file);
      dialogSpy.open.and.returnValue({ afterClosed: () => of(null) } as MatDialogRef<ImageCropperDialogComponent>);

      const event = new DragEvent('drop', { dataTransfer });
      component.onReferenceImageDrop(event, 'image');
      expect(dialogSpy.open).toHaveBeenCalledWith(ImageCropperDialogComponent, jasmine.any(Object));
    });

    it('should not open the dialog if there are already 3 images', () => {
      component.referenceImages['image'] = [{}, {}, {}] as any;
      const file = new File([''], 'test.png', { type: 'image/png' });
      dataTransfer.items.add(file);
      const event = new DragEvent('drop', { dataTransfer });
      component.onReferenceImageDrop(event, 'image');
      expect(dialogSpy.open).not.toHaveBeenCalled();
    });

    it('should not open dialog for an invalid file type', () => {
      const file = new File([''], 'test.txt', { type: 'text/plain' });
      dataTransfer.items.add(file);
      const event = new DragEvent('drop', { dataTransfer });
      component.onReferenceImageDrop(event, 'image');
      expect(dialogSpy.open).not.toHaveBeenCalled();
    });

    it('should add an image on successful crop', () => {
      const file = new File([''], 'test.png', { type: 'image/png' });
      dataTransfer.items.add(file);
      const mockAsset = { id: 789, presignedUrl: 'cropped-url' };
      dialogSpy.open.and.returnValue({ afterClosed: () => of(mockAsset) } as MatDialogRef<ImageCropperDialogComponent>);

      const event = new DragEvent('drop', { dataTransfer });
      component.onReferenceImageDrop(event, 'image');
      expect(component.referenceImages['image'].length).toBe(1);
      expect(component.referenceImages['image'][0].sourceAssetId).toBe(789);
    });
  });

  it('should clear a reference image', () => {
    component.referenceImages['image'] = [{ sourceAssetId: 123 } as any];
    component.runForm.get('image')?.setValue(component.referenceImages['image']);

    component.clearReferenceImage('image', 0);

    expect(component.referenceImages['image'].length).toBe(0);
    expect(component.runForm.get('image')?.value.length).toBe(0);
  });
});
