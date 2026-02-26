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
import {VtoComponent} from './vto.component';
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {RouterTestingModule} from '@angular/router/testing';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatDialogModule} from '@angular/material/dialog';
import {MatChipsModule} from '@angular/material/chips';
import {NO_ERRORS_SCHEMA} from '@angular/core';

describe('VtoComponent', () => {
  let component: VtoComponent;
  let fixture: ComponentFixture<VtoComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [VtoComponent],
      imports: [
        HttpClientTestingModule,
        RouterTestingModule,
        MatSnackBarModule,
        MatDialogModule,
        MatChipsModule,
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(VtoComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
