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
import { ActivatedRoute } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import {Auth} from '@angular/fire/auth';
import { of } from 'rxjs'; // Import 'of'

import { MediaDetailComponent } from './media-detail.component';

import { MaterialModule } from '../../common/material.module';

import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { Firestore } from '@angular/fire/firestore';

describe('MediaDetailComponent', () => {

  let component: MediaDetailComponent;

  let fixture: ComponentFixture<MediaDetailComponent>;

  beforeEach(async () => {

    await TestBed.configureTestingModule({

      declarations: [MediaDetailComponent],

      imports: [HttpClientTestingModule, RouterTestingModule, MaterialModule, NoopAnimationsModule],

      providers: [

        {

          provide: ActivatedRoute,

          useValue: {
            // Provide paramMap as an observable
            paramMap: of({ get: (key: string) => '123' }), // Mock paramMap with 'id' parameter
            snapshot: {

              paramMap: {

                get: () => '123', // or any other mock value

              },

            },

          },

        },
        { provide: Auth, useValue: {
          currentUser: {
            getIdToken: () => Promise.resolve('mock-id-token'),
          },
          signOut: () => Promise.resolve(),
        }},
        { provide: Firestore, useValue: {} },

      ],

    }).compileComponents();



    fixture = TestBed.createComponent(MediaDetailComponent);

    component = fixture.componentInstance;

    fixture.detectChanges();

  });



  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
