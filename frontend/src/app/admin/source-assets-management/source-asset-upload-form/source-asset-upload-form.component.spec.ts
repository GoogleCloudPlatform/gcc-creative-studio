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
import {MatDialogRef, MatDialogModule} from '@angular/material/dialog';
import {MatSnackBar, MatSnackBarModule} from '@angular/material/snack-bar';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatSelectModule} from '@angular/material/select';
import {MatInputModule} from '@angular/material/input';
import {MatIconModule} from '@angular/material/icon';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {provideHttpClient} from '@angular/common/http';
import {provideHttpClientTesting} from '@angular/common/http/testing';
import {SourceAssetUploadFormComponent} from './source-asset-upload-form.component';
import {SourceAssetsService} from '../source-assets.service';

describe('SourceAssetUploadFormComponent', () => {
  let component: SourceAssetUploadFormComponent;
  let fixture: ComponentFixture<SourceAssetUploadFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [SourceAssetUploadFormComponent],
      imports: [
        ReactiveFormsModule,
        FormsModule,
        MatDialogModule,
        MatSnackBarModule,
        MatFormFieldModule,
        MatSelectModule,
        MatInputModule,
        MatIconModule,
        MatProgressSpinnerModule,
        NoopAnimationsModule,
      ],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: MatDialogRef,
          useValue: {close: jasmine.createSpy('close')},
        },
        {
          provide: MatSnackBar,
          useValue: {open: jasmine.createSpy('open')},
        },
        {
          provide: SourceAssetsService,
          useValue: {uploadSourceAsset: jasmine.createSpy('uploadSourceAsset')},
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(SourceAssetUploadFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
