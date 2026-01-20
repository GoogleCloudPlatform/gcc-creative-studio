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

import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { ImageCropperComponent } from 'ngx-image-cropper';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {AssetTypeEnum} from '../../../admin/source-assets-management/source-asset.model';
import { of } from 'rxjs';
import { SourceAssetService } from '../../services/source-asset.service';

import {ImageCropperDialogComponent} from './image-cropper-dialog.component';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatDialogModule } from '@angular/material/dialog';
import { CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MaterialModule } from '../../material.module';
import { FormGroup, FormControl } from '@angular/forms';

describe('ImageCropperDialogComponent', () => {
  let component: ImageCropperDialogComponent;
  let fixture: ComponentFixture<ImageCropperDialogComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ImageCropperDialogComponent],
      imports: [ImageCropperComponent, HttpClientTestingModule, NoopAnimationsModule, MaterialModule, MatDialogModule, FormsModule, ReactiveFormsModule],
      providers: [
        { provide: MatDialogRef, useValue: {} },
        { provide: MAT_DIALOG_DATA, useValue: {
          imageFile: new File([''], 'mock.jpg', { type: 'image/jpeg' }),
          assetType: AssetTypeEnum.GENERIC_IMAGE,
          aspectRatios: [{label: '1:1 Square', value: 1 / 1, stringValue: '1:1'}],
        }},
        { provide: SourceAssetService, useValue: {
          uploadAsset: () => of({id: '123', name: 'mock.jpg'}) // Mock uploadAsset to return an observable
        }}
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ImageCropperDialogComponent);
    component = fixture.componentInstance;

    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
