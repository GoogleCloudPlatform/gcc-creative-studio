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



import { MatSnackBar } from '@angular/material/snack-bar';



import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';



import { HttpClientTestingModule } from '@angular/common/http/testing';



import { MatProgressBarModule } from '@angular/material/progress-bar';



import { MatSelectModule } from '@angular/material/select';



import { NoopAnimationsModule } from '@angular/platform-browser/animations';







import { SourceAssetUploadFormComponent } from './source-asset-upload-form.component';



import { MaterialModule } from '../../../common/material.module';



import { SourceAssetsService } from '../source-assets.service';







describe('SourceAssetUploadFormComponent', () => {



  let component: SourceAssetUploadFormComponent;



  let fixture: ComponentFixture<SourceAssetUploadFormComponent>;







  beforeEach(async () => {



    const sourceAssetsServiceSpy = jasmine.createSpyObj('SourceAssetsService', ['uploadSourceAsset']);



    const matSnackBarSpy = jasmine.createSpyObj('MatSnackBar', ['open']);







    await TestBed.configureTestingModule({



      declarations: [SourceAssetUploadFormComponent],



      imports: [



        HttpClientTestingModule,



        MaterialModule,



        NoopAnimationsModule,



        ReactiveFormsModule,



        MatProgressBarModule,



        MatSelectModule,



        MatDialogModule



      ],



      providers: [



        { provide: MatDialogRef, useValue: {} },



        { provide: MAT_DIALOG_DATA, useValue: {} },



        { provide: SourceAssetsService, useValue: sourceAssetsServiceSpy },



        { provide: MatSnackBar, useValue: matSnackBarSpy }



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
