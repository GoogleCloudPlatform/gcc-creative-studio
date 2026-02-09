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



import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ReactiveFormsModule } from '@angular/forms';

import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';

import { HttpClientTestingModule } from '@angular/common/http/testing';

import { MatSelectModule } from '@angular/material/select';

import { NoopAnimationsModule } from '@angular/platform-browser/animations';



import { SourceAssetFormComponent } from './source-asset-form.component';

import { MaterialModule } from '../../../common/material.module';

















describe('SourceAssetFormComponent', () => {







  let component: SourceAssetFormComponent;







  let fixture: ComponentFixture<SourceAssetFormComponent>;















  beforeEach(async () => {







    await TestBed.configureTestingModule({







      declarations: [SourceAssetFormComponent],







      imports: [







        ReactiveFormsModule,







        HttpClientTestingModule,







        MaterialModule,







        NoopAnimationsModule,







        MatSelectModule







      ],







      providers: [







        { provide: MatDialogRef, useValue: {} },







        { provide: MAT_DIALOG_DATA, useValue: { asset: {} } }







      ]







    }).compileComponents();















    fixture = TestBed.createComponent(SourceAssetFormComponent);







    component = fixture.componentInstance;







    fixture.detectChanges();







  });















  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
