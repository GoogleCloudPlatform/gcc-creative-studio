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



import { SourceAssetGalleryComponent } from './source-asset-gallery.component';



import { MaterialModule } from '../../material.module';



import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { SourceAssetService } from '../../services/source-asset.service';

import { UserService } from '../../services/user.service';

import { MatDialog } from '@angular/material/dialog';

import { MatSnackBar } from '@angular/material/snack-bar';



describe('SourceAssetGalleryComponent', () => {

  let component: SourceAssetGalleryComponent;

  let fixture: ComponentFixture<SourceAssetGalleryComponent>;



  beforeEach(async () => {

    await TestBed.configureTestingModule({

      declarations: [SourceAssetGalleryComponent],

      imports: [HttpClientTestingModule, MaterialModule, NoopAnimationsModule],

      providers: [

        { provide: SourceAssetService, useValue: {

            isLoading$: { subscribe: () => {} },

            allAssetsLoaded: { subscribe: () => {} },

            assets: { subscribe: () => {} },

            setFilters: () => {},

            loadAssets: () => {},

            deleteAsset: () => ({ pipe: () => ({ subscribe: () => {} }) }),

        }},

        { provide: UserService, useValue: {

            getUserDetails: () => ({ email: 'test@example.com' }),

        }},

        { provide: MatDialog, useValue: {

            open: () => ({ afterClosed: () => ({ subscribe: () => {} }) }),

        }},

        { provide: MatSnackBar, useValue: {

            open: () => {},

        }},

      ],

      schemas: [CUSTOM_ELEMENTS_SCHEMA],

    }).compileComponents();



    fixture = TestBed.createComponent(SourceAssetGalleryComponent);

    component = fixture.componentInstance;

    fixture.detectChanges();

  });



  it('should create', () => {

    expect(component).toBeTruthy();

  });

});


