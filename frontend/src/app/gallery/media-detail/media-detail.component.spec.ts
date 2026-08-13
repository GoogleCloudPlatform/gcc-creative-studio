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
import {provideRouter} from '@angular/router';
import {provideHttpClient} from '@angular/common/http';
import {provideHttpClientTesting} from '@angular/common/http/testing';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatDialogModule} from '@angular/material/dialog';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {CUSTOM_ELEMENTS_SCHEMA} from '@angular/core';
import {of} from 'rxjs';

import {MediaDetailComponent} from './media-detail.component';
import {GalleryService} from '../gallery.service';
import {AuthService} from '../../common/services/auth.service';
import {LoadingService} from '../../common/services/loading.service';
import {WorkspaceStateService} from '../../services/workspace/workspace-state.service';

describe('MediaDetailComponent', () => {
  let component: MediaDetailComponent;
  let fixture: ComponentFixture<MediaDetailComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [MediaDetailComponent],
      imports: [MatSnackBarModule, MatDialogModule, NoopAnimationsModule],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: GalleryService,
          useValue: {
            getAsset: jasmine.createSpy('getAsset').and.returnValue(of({})),
            getMedia: jasmine.createSpy('getMedia').and.returnValue(of({})),
          },
        },
        {
          provide: AuthService,
          useValue: {
            isUserAdmin: () => false,
          },
        },
        {
          provide: LoadingService,
          useValue: {
            hide: jasmine.createSpy('hide'),
          },
        },
        {
          provide: WorkspaceStateService,
          useValue: {
            getActiveWorkspaceId: () => 1,
          },
        },
      ],
      schemas: [CUSTOM_ELEMENTS_SCHEMA],
    }).compileComponents();

    fixture = TestBed.createComponent(MediaDetailComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
