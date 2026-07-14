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
import {SourceAssetGalleryComponent} from './source-asset-gallery.component';
import {SourceAssetService} from '../../services/source-asset.service';
import {UserService} from '../../services/user.service';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {BehaviorSubject, of, Subject} from 'rxjs';
import {NO_ERRORS_SCHEMA} from '@angular/core';

describe('SourceAssetGalleryComponent', () => {
  let component: SourceAssetGalleryComponent;
  let fixture: ComponentFixture<SourceAssetGalleryComponent>;
  let mockSourceAssetService: any;
  let mockUserService: any;

  beforeEach(async () => {
    mockSourceAssetService = {
      isLoading$: new BehaviorSubject<boolean>(false),
      allAssetsLoaded: new BehaviorSubject<boolean>(false),
      assets: new BehaviorSubject<any[]>([]),
      setFilters: jasmine.createSpy('setFilters'),
      loadAssets: jasmine.createSpy('loadAssets'),
      deleteAsset: jasmine.createSpy('deleteAsset').and.returnValue(of(null)),
    };

    mockUserService = {
      getUserDetails: jasmine
        .createSpy('getUserDetails')
        .and.returnValue({email: 'test@test.com'}),
    };

    await TestBed.configureTestingModule({
      declarations: [SourceAssetGalleryComponent],
      providers: [
        {provide: SourceAssetService, useValue: mockSourceAssetService},
        {provide: UserService, useValue: mockUserService},
        {provide: MatDialog, useValue: {open: jasmine.createSpy('open')}},
        {provide: MatSnackBar, useValue: {open: jasmine.createSpy('open')}},
      ],
      schemas: [NO_ERRORS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(SourceAssetGalleryComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
