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







import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';



import { SourceAssetsManagementComponent } from './source-assets-management.component';



import { MaterialModule } from '../../common/material.module';



import { NoopAnimationsModule } from '@angular/platform-browser/animations';







describe('SourceAssetsManagementComponent', () => {



  let component: SourceAssetsManagementComponent;



  let fixture: ComponentFixture<SourceAssetsManagementComponent>;







  beforeEach(async () => {



    await TestBed.configureTestingModule({



      declarations: [SourceAssetsManagementComponent],



      imports: [HttpClientTestingModule, MaterialModule, NoopAnimationsModule],



      schemas: [CUSTOM_ELEMENTS_SCHEMA],



    }).compileComponents();







    fixture = TestBed.createComponent(SourceAssetsManagementComponent);



    component = fixture.componentInstance;



    fixture.detectChanges();



  });







  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
