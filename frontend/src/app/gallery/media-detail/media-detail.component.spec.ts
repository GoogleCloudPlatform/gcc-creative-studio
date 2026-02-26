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
import {MediaDetailComponent} from './media-detail.component';
import {HttpClientTestingModule} from '@angular/common/http/testing';
import {RouterTestingModule} from '@angular/router/testing';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatIconModule} from '@angular/material/icon';
import {NO_ERRORS_SCHEMA} from '@angular/core';
import {ActivatedRoute} from '@angular/router';
import {of} from 'rxjs';
import {AuthService} from '../../common/services/auth.service';

describe('MediaDetailComponent', () => {
  let component: MediaDetailComponent;
  let fixture: ComponentFixture<MediaDetailComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [MediaDetailComponent],
      imports: [
        HttpClientTestingModule,
        RouterTestingModule,
        MatSnackBarModule,
        MatIconModule,
      ],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: {
            params: of({id: '1'}),
            snapshot: {params: {id: '1'}},
          },
        },
        {
          provide: AuthService,
          useValue: {
            user$: of(null),
            isLoggedIn$: of(false),
          },
        },
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(MediaDetailComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
