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

import { HttpClientTestingModule } from '@angular/common/http/testing';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {of} from 'rxjs';















import { MediaTemplatesManagementComponent } from './media-templates-management.component';







import { MediaTemplatesService } from './media-templates.service';







import { MaterialModule } from '../../common/material.module';







import { MatPaginatorModule } from '@angular/material/paginator';







import { MatSortModule } from '@angular/material/sort';







import { MatSnackBarModule } from '@angular/material/snack-bar';







import { MatDialog, MatDialogModule } from '@angular/material/dialog';







import { MatSnackBar } from '@angular/material/snack-bar';















describe('MediaTemplatesManagementComponent', () => {







  let component: MediaTemplatesManagementComponent;







  let fixture: ComponentFixture<MediaTemplatesManagementComponent>;







  let mockMediaTemplatesService: jasmine.SpyObj<MediaTemplatesService>;







  let mockMatDialog: jasmine.SpyObj<MatDialog>;







  let mockMatSnackBar: jasmine.SpyObj<MatSnackBar>;















  beforeEach(async () => {







    mockMediaTemplatesService = jasmine.createSpyObj('MediaTemplatesService', [







      'getMediaTemplates',







      'createMediaTemplate',







      'updateMediaTemplate',







      'deleteMediaTemplate'







    ]);







    mockMediaTemplatesService.getMediaTemplates.and.returnValue(







      of({ data: [], count: 0, page: 0, pageSize: 0, totalPages: 0 }),







    );







    mockMatDialog = jasmine.createSpyObj('MatDialog', ['open']);







    mockMatSnackBar = jasmine.createSpyObj('MatSnackBar', ['open']);















    await TestBed.configureTestingModule({







      declarations: [MediaTemplatesManagementComponent],







      imports: [







        NoopAnimationsModule,







        HttpClientTestingModule,







        MaterialModule,







        MatPaginatorModule,







        MatSortModule,







        MatSnackBarModule,







        MatDialogModule







      ],







      providers: [







        { provide: MediaTemplatesService, useValue: mockMediaTemplatesService },







        { provide: MatDialog, useValue: mockMatDialog },







        { provide: MatSnackBar, useValue: mockMatSnackBar },







      ],







    }).compileComponents();















    fixture = TestBed.createComponent(MediaTemplatesManagementComponent);







    component = fixture.componentInstance;







    fixture.detectChanges();







  });















  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
