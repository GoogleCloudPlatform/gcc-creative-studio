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

import {ComponentFixture, TestBed} from '@angular/core/testing';
import {ReactiveFormsModule, FormsModule} from '@angular/forms';
import {
  MatDialogRef,
  MAT_DIALOG_DATA,
  MatDialogModule,
} from '@angular/material/dialog';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatSelectModule} from '@angular/material/select';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {SourceAssetFormComponent} from './source-asset-form.component';
import {AssetScopeEnum, AssetTypeEnum} from '../source-asset.model';

describe('SourceAssetFormComponent', () => {
  let component: SourceAssetFormComponent;
  let fixture: ComponentFixture<SourceAssetFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [SourceAssetFormComponent],
      imports: [
        ReactiveFormsModule,
        FormsModule,
        MatDialogModule,
        MatFormFieldModule,
        MatInputModule,
        MatSelectModule,
        NoopAnimationsModule,
      ],
      providers: [
        {
          provide: MatDialogRef,
          useValue: {close: jasmine.createSpy('close')},
        },
        {
          provide: MAT_DIALOG_DATA,
          useValue: {
            asset: {
              id: '1',
              originalFilename: 'test.png',
              scope: AssetScopeEnum.SYSTEM,
              assetType: AssetTypeEnum.GENERIC_IMAGE,
              gcsUri: 'gs://bucket/test.png',
            },
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(SourceAssetFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
