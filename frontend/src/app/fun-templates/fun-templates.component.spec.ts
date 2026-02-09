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



import { FunTemplatesComponent } from './fun-templates.component';

import { MatIconModule } from '@angular/material/icon';

import { MatIconTestingModule } from '@angular/material/icon/testing';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';


describe('FunTemplatesComponent', () => {

  let component: FunTemplatesComponent;

  let fixture: ComponentFixture<FunTemplatesComponent>;



  beforeEach(async () => {

    await TestBed.configureTestingModule({

      declarations: [FunTemplatesComponent],

      imports: [HttpClientTestingModule, MatIconModule, MatIconTestingModule, MatProgressSpinnerModule],

    }).compileComponents();



    fixture = TestBed.createComponent(FunTemplatesComponent);

    component = fixture.componentInstance;

    fixture.detectChanges();

  });



  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
